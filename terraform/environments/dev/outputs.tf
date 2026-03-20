output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "rds_endpoint" {
  value     = module.rds.endpoint
  sensitive = true
}

output "wiki_rag_role_arn" {
  value = module.iam.wiki_rag_role_arn
}

output "secret_name" {
  value = module.secrets.secret_name
}

output "bastion_instance_id" {
  description = "Connect with: aws ssm start-session --target <id> --region <region>"
  value       = module.bastion.instance_id
}

output "github_actions_role_arn" {
  description = "Set as AWS_ROLE_ARN secret in GitHub repository settings"
  value       = module.ci.github_actions_role_arn
}
