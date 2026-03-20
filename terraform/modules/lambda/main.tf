# ── IAM Role ─────────────────────────────────────────────────────────────────
resource "aws_iam_role" "lambda" {
  name = "${var.name}-docx-extractor"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "lambda_s3" {
  name = "${var.name}-docx-extractor-s3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "S3ReadWrite"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = "${var.s3_bucket_arn}/*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.lambda_s3.arn
}

# ── Lambda deployment package ─────────────────────────────────────────────────
# Package is built by deploy.sh before terraform apply.
# The zip file must be created at: lambda/docx_image_extractor.zip
data "archive_file" "docx_extractor" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambda/docx_image_extractor"
  output_path = "${path.module}/docx_image_extractor.zip"
}

# ── Lambda Function ───────────────────────────────────────────────────────────
resource "aws_lambda_function" "docx_extractor" {
  function_name = "${var.name}-docx-extractor"
  role          = aws_iam_role.lambda.arn
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  timeout       = 60
  memory_size   = 512

  filename         = data.archive_file.docx_extractor.output_path
  source_code_hash = data.archive_file.docx_extractor.output_base64sha256

  environment {
    variables = {
      S3_BUCKET = var.s3_bucket
    }
  }

  tags = var.tags
}

# ── CloudWatch Log Group (explicit for lifecycle control) ─────────────────────
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.docx_extractor.function_name}"
  retention_in_days = 7
  tags              = var.tags
}
