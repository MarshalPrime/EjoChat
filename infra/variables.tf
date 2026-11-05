variable "aws_region" {
  description = "Region where the checkpoint bucket and trainer are created. Use a region where your account has GPU quota."
  type        = string
  default     = "us-east-1"
}

variable "launch_trainer" {
  description = "Create the GPU instance. Leave false while editing locally. True starts on-demand GPU charges."
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "GPU machine for full CPT. p5.48xlarge is 8x H100 for Qwen3-8B. p4de.24xlarge is 8x A100 80GB and is the Qwen3-4B machine."
  type        = string
  default     = "p5.48xlarge"
}

variable "subnet_id" {
  description = "Subnet for the trainer. Empty uses the first subnet in the default VPC. p5 capacity is limited to specific availability zones."
  type        = string
  default     = null
}

variable "ami_id" {
  description = "GPU AMI. Empty looks up the Deep Learning Base Ubuntu 22.04 AMI."
  type        = string
  default     = null
}

variable "root_volume_gb" {
  description = "Scratch disk on the trainer for the mixture, Hugging Face cache, and checkpoints."
  type        = number
  default     = 1000
}

variable "ssh_key_name" {
  description = "Optional EC2 key pair. Leave empty to use SSM only."
  type        = string
  default     = null
}

variable "ssh_cidr" {
  description = "Optional CIDR allowed to SSH. Leave empty to keep port 22 closed."
  type        = string
  default     = null
}
