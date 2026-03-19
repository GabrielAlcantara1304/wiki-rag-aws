variable "name" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }
variable "k8s_namespace" { type = string; default = "wiki-rag" }
variable "k8s_service_account" { type = string; default = "wiki-rag" }
variable "tags" { type = map(string); default = {} }
