---
tags: [wiki-rag, cicd, github-actions, ecr, eks, terraform]
---

# CI/CD — Pipeline de Deploy

Arquivo: `.github/workflows/deploy.yml`
Trigger: push na branch `main` ou `workflow_dispatch` manual

## Sem credenciais de longa duração

O pipeline usa **OIDC federation** — o GitHub Actions obtém um token temporário e assume um IAM Role na AWS. Nenhuma `AWS_ACCESS_KEY_ID` fica armazenada no repositório.

```
GitHub Actions token (OIDC)
  └─ assume IAM Role: wiki-rag-dev-github-actions
       └─ permissões: ECR push, EKS deploy, Secrets Manager read
```

## Steps do pipeline

```
Step 1 — Checkout
  git checkout do repositório

Step 2 — AWS credentials (OIDC)
  aws-actions/configure-aws-credentials@v4
  role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
  Sem senha — token temporário via OIDC

Step 3 — Login no ECR
  aws-actions/amazon-ecr-login@v2
  Obtém token de autenticação Docker para o registry

Step 4 — Build e push da imagem Docker
  docker build -t {ECR_URL}:{git_sha} .
  docker push {ECR_URL}:{git_sha}
  docker tag  {ECR_URL}:latest
  docker push {ECR_URL}:latest

Step 5 — Configurar kubectl
  aws eks update-kubeconfig --name wiki-rag-dev
  Configura acesso ao cluster EKS

Step 6 — Aplicar manifests base
  kubectl apply -f k8s/namespace.yaml
  kubectl apply -f k8s/serviceaccount.yaml

  # Injeta valores do Terraform nos placeholders do ConfigMap
  sed -i "s|REPLACE_WITH_TERRAFORM_OUTPUT|{SQS_URL}|" k8s/configmap.yaml
  sed -i "s|REPLACE_WITH_S3_BUCKET|{S3_BUCKET}|"     k8s/configmap.yaml
  sed -i "s|REPLACE_WITH_LAMBDA_NAME|{LAMBDA}|"       k8s/configmap.yaml
  kubectl apply -f k8s/configmap.yaml

  # Busca DATABASE_URL do Secrets Manager e cria Secret no K8s
  SECRET_JSON = aws secretsmanager get-secret-value --secret-id wiki-rag-dev/app
  kubectl create secret generic wiki-rag-db-secret \
    --from-literal=DATABASE_URL=...
    --from-literal=DATABASE_URL_SYNC=...
    --dry-run=client -o yaml | kubectl apply -f -

Step 7 — Migrations Alembic
  Substitui placeholder de imagem no job-migrate.yaml
  kubectl apply -f k8s/job-migrate.yaml
  kubectl wait --for=condition=complete job/wiki-rag-migrate --timeout=120s
  kubectl delete job wiki-rag-migrate

Step 8 — Deploy da nova imagem
  sed "s|PLACEHOLDER|{ECR_URL}:{git_sha}|" k8s/deployment.yaml | kubectl apply -f -
  sed "s|PLACEHOLDER|{ECR_URL}:{git_sha}|" k8s/worker-deployment.yaml | kubectl apply -f -
  kubectl apply -f k8s/service.yaml
  kubectl rollout status deployment/wiki-rag --timeout=300s

Step 9 — Aplicar HPA
  kubectl apply -f k8s/hpa.yaml
  (min 2, max 10 réplicas da API; escala por CPU 60% / memória 75%)

Step 10 — Resumo
  Imprime imagem deployada, cluster, lista de pods
```

## Variáveis e secrets necessários

| Nome | Tipo GitHub | De onde vem |
|---|---|---|
| `AWS_ROLE_ARN` | Secret | `terraform output github_actions_role_arn` |
| `AWS_REGION` | Variable | `us-east-1` |
| `ECR_REPOSITORY` | Variable | `terraform output ecr_repository_url` |
| `EKS_CLUSTER_NAME` | Variable | `terraform output eks_cluster_name` |
| `SQS_INGESTION_QUEUE_URL` | Variable | `terraform output sqs_ingestion_queue_url` |
| `S3_BUCKET` | Variable | `terraform output s3_bucket_name` |
| `LAMBDA_DOCX_EXTRACTOR_NAME` | Variable | `terraform output lambda_docx_extractor_name` |

## IRSA — Identidade dos pods

Os pods usam uma ServiceAccount com anotação IRSA:
```yaml
eks.amazonaws.com/role-arn: "arn:aws:iam::406951616480:role/wiki-rag-dev-wiki-rag"
```

Esse role tem permissões para:
- Bedrock: InvokeModel (Titan + Nova Lite)
- S3: GetObject, PutObject, DeleteObject, ListBucket
- SQS: SendMessage, ReceiveMessage, DeleteMessage
- Secrets Manager: GetSecretValue (`wiki-rag-dev/*`)
- Lambda: InvokeFunction (docx extractor)

## Configurar após o primeiro terraform apply

```bash
gh secret set AWS_ROLE_ARN \
  --body "$(terraform -chdir=terraform/environments/dev output -raw github_actions_role_arn)"

gh variable set AWS_REGION          --body "us-east-1"
gh variable set ECR_REPOSITORY      --body "$(terraform ... output -raw ecr_repository_url)"
gh variable set EKS_CLUSTER_NAME    --body "$(terraform ... output -raw eks_cluster_name)"
gh variable set SQS_INGESTION_QUEUE_URL --body "$(terraform ... output -raw sqs_ingestion_queue_url)"
gh variable set S3_BUCKET           --body "$(terraform ... output -raw s3_bucket_name)"
gh variable set LAMBDA_DOCX_EXTRACTOR_NAME --body "$(terraform ... output -raw lambda_docx_extractor_name)"
```

## Ver também

- [[00-Visão-Geral]] — arquitetura completa
- [[06-Armazenamento]] — o que o Terraform provisiona
