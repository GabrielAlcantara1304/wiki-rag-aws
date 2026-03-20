# ── IRSA: IAM Role for wiki-rag pods ─────────────────────────────────────────
# Assumed by both the API pod and the worker pod via OIDC federation.
# Grants Bedrock, Secrets Manager, S3, SQS, and Lambda access.

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "wiki_rag" {
  name               = "${var.name}-wiki-rag"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

# ── Bedrock ───────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "bedrock" {
  name        = "${var.name}-bedrock"
  description = "Allow wiki-rag pods to invoke Bedrock models (Titan Embeddings + Claude)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeBedrockModels"
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
      ]
      Resource = [
        "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "bedrock" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.bedrock.arn
}

# ── Secrets Manager ───────────────────────────────────────────────────────────
resource "aws_iam_policy" "secrets" {
  name = "${var.name}-secrets-read"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadWikiRagSecrets"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.name}/*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "secrets" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.secrets.arn
}

# ── S3 ────────────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "s3" {
  name = "${var.name}-s3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "S3ReadWrite"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        "arn:aws:s3:::${var.s3_bucket}",
        "arn:aws:s3:::${var.s3_bucket}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "s3" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.s3.arn
}

# ── SQS ──────────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "sqs" {
  name = "${var.name}-sqs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SQSIngestion"
      Effect = "Allow"
      Action = [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = var.sqs_queue_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sqs" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.sqs.arn
}

# ── Lambda invoke (docx image extractor) ─────────────────────────────────────
resource "aws_iam_policy" "lambda_invoke" {
  name = "${var.name}-lambda-invoke"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvokeDocxExtractor"
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = var.lambda_docx_extractor_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_invoke" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.lambda_invoke.arn
}
