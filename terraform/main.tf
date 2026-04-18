terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "tls_private_key" "devflow" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "devflow" {
  key_name   = "devflow-key"
  public_key = tls_private_key.devflow.public_key_openssh
}

resource "aws_security_group" "devflow" {
  name        = "devflow-sg"
  description = "DevFlow app security group"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "devflow" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.devflow.key_name
  vpc_security_group_ids = [aws_security_group.devflow.id]

  user_data = file("${path.module}/../deploy/setup.sh")

  tags = {
    Name = "devflow"
  }
}

resource "aws_eip" "devflow" {
  instance = aws_instance.devflow.id
}
