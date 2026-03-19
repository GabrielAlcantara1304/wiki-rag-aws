# ── Security Group ───────────────────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${var.name}-rds"
  description = "Allow PostgreSQL from EKS nodes only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

# ── Subnet Group ─────────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

# ── RDS Instance ─────────────────────────────────────────────────────────────
resource "aws_db_instance" "this" {
  identifier = var.name

  engine         = "postgres"
  engine_version = "16.2"
  instance_class = var.instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Storage
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  # Network
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  # Backups
  backup_retention_period = var.backup_retention_days
  skip_final_snapshot     = var.skip_final_snapshot

  # Maintenance
  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection

  tags = var.tags
}
