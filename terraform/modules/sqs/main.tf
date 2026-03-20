# ── Dead Letter Queue ─────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-ingestion-dlq"
  message_retention_seconds = 1209600  # 14 days — time to investigate failures
  tags                      = var.tags
}

# ── Ingestion Queue ───────────────────────────────────────────────────────────
resource "aws_sqs_queue" "ingestion" {
  name                       = "${var.name}-ingestion"
  message_retention_seconds  = var.message_retention_seconds
  visibility_timeout_seconds = 300   # 5 min — must be >= Lambda/worker timeout
  receive_wait_time_seconds  = 20    # long polling
  tags                       = var.tags

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}
