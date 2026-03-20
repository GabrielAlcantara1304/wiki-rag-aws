terraform {
  backend "s3" {
    bucket  = "wiki-rag-terraform-state-406951616480"
    key     = "wiki-rag/dev/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
