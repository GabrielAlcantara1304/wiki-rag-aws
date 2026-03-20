variable "name"           { type = string }
variable "aws_account_id" { type = string }
variable "aws_region"     { type = string }
variable "github_org"     { type = string; description = "GitHub organization or username" }
variable "github_repo"    { type = string; description = "Repository name (without org)" }
variable "ecr_repo_arns"  { type = list(string); description = "ECR repository ARNs the pipeline can push to" }
variable "eks_cluster_arn" { type = string; description = "EKS cluster ARN for kubectl access" }
variable "tags"           { type = map(string); default = {} }
