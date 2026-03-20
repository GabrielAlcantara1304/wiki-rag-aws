resource "aws_s3_bucket" "this" {
  bucket        = var.name
  force_destroy = true   # allows terraform destroy to empty the bucket
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle: delete extracted images older than 30 days (already stored in DB as Assets)
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "expire-images"
    status = "Enabled"
    filter { prefix = "images/" }
    expiration { days = 30 }
  }

  rule {
    id     = "expire-uploads"
    status = "Enabled"
    filter { prefix = "uploads/" }
    expiration { days = 7 }
  }
}
