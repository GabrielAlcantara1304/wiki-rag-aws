output "github_actions_role_arn" {
  description = "Set this as AWS_ROLE_ARN secret in GitHub repo settings"
  value       = aws_iam_role.github_actions.arn
}
