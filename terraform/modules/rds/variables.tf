variable "name" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "allowed_security_group_ids" { type = list(string) }

variable "db_name" { type = string; default = "wiki_rag" }
variable "db_username" { type = string; default = "wiki_rag" }
variable "db_password" { type = string; sensitive = true }

variable "instance_class" { type = string; default = "db.t3.medium" }
variable "multi_az" { type = bool; default = false }
variable "backup_retention_days" { type = number; default = 7 }
variable "skip_final_snapshot" { type = bool; default = true }
variable "deletion_protection" { type = bool; default = false }

variable "tags" { type = map(string); default = {} }
