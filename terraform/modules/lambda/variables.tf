variable "name"         { type = string }
variable "s3_bucket"    { type = string }
variable "s3_bucket_arn" { type = string }
variable "tags"         { type = map(string); default = {} }
