terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.common_tags }
}

locals {
  name        = "${var.project}-${var.environment}"
  common_tags = { Project = var.project, Environment = var.environment, ManagedBy = "terraform" }
}

data "aws_caller_identity" "current" {}

# ── VPC ───────────────────────────────────────────────────────────────────────
module "vpc" {
  source          = "../../modules/vpc"
  name            = local.name
  cidr            = var.vpc_cidr
  azs             = var.availability_zones
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs
  region          = var.aws_region
  tags            = local.common_tags
}

# ── EKS ───────────────────────────────────────────────────────────────────────
module "eks" {
  source              = "../../modules/eks"
  name                = local.name
  kubernetes_version  = var.kubernetes_version
  private_subnet_ids  = module.vpc.private_subnet_ids
  node_instance_types = var.eks_node_instance_types
  node_desired_size   = var.eks_node_desired_size
  node_min_size       = var.eks_node_min_size
  node_max_size       = var.eks_node_max_size
  tags                = local.common_tags
}

# ── RDS ───────────────────────────────────────────────────────────────────────
module "rds" {
  source                     = "../../modules/rds"
  name                       = local.name
  vpc_id                     = module.vpc.vpc_id
  private_subnet_ids         = module.vpc.private_subnet_ids
  allowed_security_group_ids = []
  db_password                = var.db_password
  instance_class             = var.rds_instance_class
  skip_final_snapshot        = true
  tags                       = local.common_tags
}

# ── ECR ───────────────────────────────────────────────────────────────────────
module "ecr" {
  source = "../../modules/ecr"
  name   = "${var.project}-api"
  tags   = local.common_tags
}

# ── S3 ────────────────────────────────────────────────────────────────────────
module "s3" {
  source = "../../modules/s3"
  name   = "${local.name}-uploads"
  tags   = local.common_tags
}

# ── SQS ───────────────────────────────────────────────────────────────────────
module "sqs" {
  source = "../../modules/sqs"
  name   = local.name
  tags   = local.common_tags
}

# ── Lambda: docx image extractor ─────────────────────────────────────────────
module "lambda" {
  source        = "../../modules/lambda"
  name          = local.name
  s3_bucket     = module.s3.bucket_name
  s3_bucket_arn = module.s3.bucket_arn
  tags          = local.common_tags
}

# ── IAM / IRSA ────────────────────────────────────────────────────────────────
module "iam" {
  source                    = "../../modules/iam"
  name                      = local.name
  aws_region                = var.aws_region
  aws_account_id            = data.aws_caller_identity.current.account_id
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  s3_bucket                 = module.s3.bucket_name
  sqs_queue_arn             = module.sqs.queue_arn
  lambda_docx_extractor_arn = module.lambda.function_arn
  tags                      = local.common_tags
}

# ── Secrets Manager ───────────────────────────────────────────────────────────
module "secrets" {
  source      = "../../modules/secrets"
  name        = "${local.name}/app"
  description = "wiki-rag application secrets (DB credentials)"
  tags        = local.common_tags

  secret_values = {
    database_url      = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${module.rds.endpoint}/${var.db_name}"
    database_url_sync = "postgresql://${var.db_username}:${var.db_password}@${module.rds.endpoint}/${var.db_name}"
  }
}

# ── Bastion ───────────────────────────────────────────────────────────────────
module "bastion" {
  source           = "../../modules/bastion"
  name             = local.name
  vpc_id           = module.vpc.vpc_id
  public_subnet_id = module.vpc.public_subnet_ids[0]
  vpc_cidr         = var.vpc_cidr
  tags             = local.common_tags
}

# ── CI / GitHub Actions OIDC ─────────────────────────────────────────────────
module "ci" {
  source          = "../../modules/ci"
  name            = local.name
  aws_account_id  = data.aws_caller_identity.current.account_id
  aws_region      = var.aws_region
  github_org      = var.github_org
  github_repo     = var.github_repo
  ecr_repo_arns   = [module.ecr.repository_arn]
  eks_cluster_arn = module.eks.cluster_arn
  tags            = local.common_tags
}
