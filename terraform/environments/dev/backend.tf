# Remote state: S3 bucket + DynamoDB lock table must exist before running init.
# Create them manually once:
#   aws s3 mb s3://<your-bucket> --region us-east-1
#   aws dynamodb create-table --table-name terraform-locks \
#     --attribute-definitions AttributeName=LockID,AttributeType=S \
#     --key-schema AttributeName=LockID,KeyType=HASH \
#     --billing-mode PAY_PER_REQUEST

terraform {
  backend "s3" {
    bucket         = "CHANGE_ME-terraform-state"
    key            = "wiki-rag/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-locks"
    encrypt        = true
  }
}
