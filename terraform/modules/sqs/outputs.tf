output "queue_url"  { value = aws_sqs_queue.ingestion.url }
output "queue_arn"  { value = aws_sqs_queue.ingestion.arn }
output "dlq_url"    { value = aws_sqs_queue.dlq.url }
output "dlq_arn"    { value = aws_sqs_queue.dlq.arn }
