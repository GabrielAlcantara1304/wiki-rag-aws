output "instance_id" {
  description = "Bastion instance ID — use with: aws ssm start-session --target <id>"
  value       = aws_instance.bastion.id
}

output "instance_arn" {
  value = aws_instance.bastion.arn
}
