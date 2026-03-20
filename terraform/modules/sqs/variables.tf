variable "name"                  { type = string }
variable "message_retention_seconds" { type = number; default = 86400 }  # 1 day
variable "max_receive_count"    { type = number; default = 3; description = "Retries before DLQ" }
variable "tags"                 { type = map(string); default = {} }
