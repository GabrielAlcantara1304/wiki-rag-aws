# ── IRSA: IAM Role for wiki-rag Service Account ──────────────────────────────
# This role is assumed by the Kubernetes service account via OIDC federation.
# It grants access to Bedrock — no long-lived credentials needed in the pod.

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

# ── Bedrock access policy ────────────────────────────────────────────────────
resource "aws_iam_policy" "bedrock" {
  name        = "${var.name}-bedrock-access"
  description = "Allow wiki-rag to invoke Bedrock models (LLM + Embeddings)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeBedrockModels"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "bedrock" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.bedrock.arn
}

# ── Secrets Manager read policy (optional — used in prod for DB credentials) ─
resource "aws_iam_policy" "secrets" {
  name        = "${var.name}-secrets-read"
  description = "Allow wiki-rag to read its secrets from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadWikiRagSecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.name}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "secrets" {
  role       = aws_iam_role.wiki_rag.name
  policy_arn = aws_iam_policy.secrets.arn
}
