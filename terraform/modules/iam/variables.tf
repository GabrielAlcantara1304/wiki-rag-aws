variable "name"            { type = string }
variable "aws_region"      { type = string }
variable "aws_account_id"  { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }
variable "k8s_namespace" {
  type    = string
  default = "wiki-rag"
}
variable "k8s_service_account" {
  type    = string
  default = "wiki-rag"
}
variable "s3_bucket" {
  type        = string
  description = "S3 bucket name for uploads/images"
}
variable "sqs_queue_arn" {
  type        = string
  description = "Ingestion SQS queue ARN"
}
variable "lambda_docx_extractor_arn" {
  type        = string
  description = "Lambda ARN for docx image extraction"
}
variable "tags" {
  type    = map(string)
  default = {}
}
