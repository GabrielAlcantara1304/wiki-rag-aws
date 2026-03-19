variable "name" {
  type        = string
  description = "Secret name — use path format: project/env/purpose"
}

variable "description" {
  type    = string
  default = ""
}

variable "secret_values" {
  type        = map(string)
  sensitive   = true
  description = "Key-value pairs stored as JSON in the secret"
}

variable "recovery_window_in_days" {
  type    = number
  default = 0  # 0 = immediate delete (good for POC teardown)
}

variable "tags" {
  type    = map(string)
  default = {}
}
