# ── IRSA: IAM Role for wiki-rag Service Account ──────────────────────────────
# Assumed by the Kubernetes pod via OIDC federation (no long-lived credentials).
# Grants Secrets Manager access only — OpenAI calls go directly over the internet.

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

# ── Secrets Manager read policy ───────────────────────────────────────────────
# Allows the pod to read DATABASE_URL and OPENAI_API_KEY at startup.
resource "aws_iam_policy" "secrets" {
  name        = "${var.name}-secrets-read"
  description = "Allow wiki-rag pod to read its secrets from Secrets Manager"

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
