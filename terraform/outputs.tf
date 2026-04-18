output "public_ip" {
  description = "Elastic IP — use this as EC2_HOST in GitHub Actions secrets"
  value       = aws_eip.devflow.public_ip
}

output "private_key" {
  description = "SSH private key — use this as EC2_SSH_PRIVATE_KEY in GitHub Actions secrets"
  value       = tls_private_key.devflow.private_key_pem
  sensitive   = true
}
