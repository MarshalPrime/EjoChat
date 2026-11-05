data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  count   = var.launch_trainer && var.subnet_id == null ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = var.launch_trainer && var.subnet_id == null ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "dlami" {
  count       = var.launch_trainer && var.ami_id == null ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

locals {
  bucket_name = "ejochat-cpt-${data.aws_caller_identity.current.account_id}"
  subnet_id   = var.subnet_id != null ? var.subnet_id : try(data.aws_subnets.default[0].ids[0], null)
  ami_id      = var.ami_id != null ? var.ami_id : try(data.aws_ami.dlami[0].id, null)
  vpc_id      = var.subnet_id != null ? try(data.aws_subnet.selected[0].vpc_id, null) : try(data.aws_vpc.default[0].id, null)
}

resource "aws_s3_bucket" "cpt" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "cpt" {
  bucket = aws_s3_bucket.cpt.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cpt" {
  bucket = aws_s3_bucket.cpt.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cpt" {
  bucket = aws_s3_bucket.cpt.id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_iam_role" "trainer" {
  name = "ejochat-cpt-trainer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.trainer.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "bucket" {
  name = "ejochat-cpt-bucket"
  role = aws_iam_role.trainer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = [aws_s3_bucket.cpt.arn]
      }, {
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = ["${aws_s3_bucket.cpt.arn}/*"]
    }]
  })
}

resource "aws_iam_instance_profile" "trainer" {
  name = "ejochat-cpt-trainer"
  role = aws_iam_role.trainer.name
}

resource "aws_security_group" "trainer" {
  count       = var.launch_trainer ? 1 : 0
  name        = "ejochat-cpt-trainer"
  description = "EjoChat CPT trainer. Inbound SSH only when ssh_cidr is set."
  vpc_id      = coalesce(local.vpc_id, "vpc-00000000")

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.ssh_cidr == null ? [] : [var.ssh_cidr]
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
}

data "aws_subnet" "selected" {
  count = var.launch_trainer && var.subnet_id != null ? 1 : 0
  id    = var.subnet_id
}

resource "aws_instance" "trainer" {
  count                       = var.launch_trainer ? 1 : 0
  ami                         = coalesce(local.ami_id, "ami-00000000000000000")
  instance_type               = var.instance_type
  subnet_id                   = coalesce(local.subnet_id, "subnet-00000000")
  vpc_security_group_ids      = [aws_security_group.trainer[0].id]
  iam_instance_profile        = aws_iam_instance_profile.trainer.name
  associate_public_ip_address = true
  key_name                    = var.ssh_key_name
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    bucket = aws_s3_bucket.cpt.bucket
  })

  root_block_device {
    volume_size           = var.root_volume_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }

  tags = {
    Name    = "ejochat-cpt-trainer"
    Project = "EjoChat"
  }

  depends_on = [aws_iam_role_policy.bucket]
}
