output "bucket_name" {
  description = "S3 bucket for code, the CMS mixture, and checkpoints."
  value       = aws_s3_bucket.cpt.bucket
}

output "aws_region" {
  value = var.aws_region
}

output "instance_id" {
  description = "SSM target. Null until launch_trainer is true."
  value       = try(aws_instance.trainer[0].id, null)
}

output "instance_type" {
  value = var.instance_type
}
