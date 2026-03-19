resource "aws_secretsmanager_secret" "this" {
  name                    = var.name
  description             = var.description
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "this" {
  secret_id = aws_secretsmanager_secret.this.id
  secret_string = jsonencode(var.secret_values)

  lifecycle {
    # Prevent Terraform from overwriting secrets updated outside of TF (e.g., rotation)
    ignore_changes = [secret_string]
  }
}
