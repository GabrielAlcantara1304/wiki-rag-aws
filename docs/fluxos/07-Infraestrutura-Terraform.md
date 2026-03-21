---
tags: [wiki-rag, terraform, aws, infraestrutura]
---

# Infraestrutura — Terraform

Diretório: `terraform/`
Ambiente ativo: `terraform/environments/dev/`

## Estrutura de módulos

```
terraform/
├── environments/
│   └── dev/
│       └── main.tf        ← orquestra todos os módulos
└── modules/
    ├── vpc/               ← rede
    ├── eks/               ← cluster Kubernetes
    ├── rds/               ← banco de dados
    ├── ecr/               ← registry de imagens
    ├── s3/                ← armazenamento de documentos
    ├── sqs/               ← fila de ingestão
    ├── lambda/            ← extrator de imagens .docx
    ├── iam/               ← roles dos pods (IRSA)
    ├── secrets/           ← Secrets Manager
    ├── bastion/           ← acesso SSH/SSM
    └── ci/                ← role do GitHub Actions
```

## O que cada módulo cria

### `vpc`
- VPC com CIDR `10.0.0.0/16`
- 2 subnets públicas (para NAT Gateway e bastion)
- 2 subnets privadas (para EKS nodes e RDS)
- Internet Gateway
- NAT Gateway (1x, na subnet pública) ← **principal custo de rede**
- Route tables

### `eks`
- IAM Role para o cluster (`eks.amazonaws.com`)
- EKS Cluster (Kubernetes 1.30)
  - `endpoint_public_access = true` (simplifica acesso inicial)
  - `authentication_mode = "API_AND_CONFIG_MAP"`
- OIDC Provider (necessário para IRSA)
- IAM Role para os nodes (`ec2.amazonaws.com`)
  - Policies: `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`, `AmazonEC2ContainerRegistryReadOnly`
- Node Group
  - `instance_types = ["t3.medium"]`
  - `disk_size = 50` GB (aumentado por causa do PyTorch/transformers)
  - `desired = 2`, `min = 1`, `max = 4`

### `rds`
- Subnet group nas subnets privadas
- Security group — aceita porta 5432 apenas do SG do EKS
- Instância PostgreSQL 16.9
  - `db.t3.medium`
  - `allocated_storage = 20` GB
  - `skip_final_snapshot = true` (para poder destruir sem snapshot)
- Banco criado: `wiki_rag`

### `ecr`
- Repositório `wiki-rag-api`
- `image_tag_mutability = "MUTABLE"` (permite sobrescrever `:latest`)
- Lifecycle policy: mantém as últimas 10 imagens

### `s3`
- Bucket `wiki-rag-dev-{account_id}`
- Versionamento desabilitado (dev)
- Bloqueio de acesso público habilitado

### `sqs`
- Fila principal: `wiki-rag-dev-ingestion`
  - `visibility_timeout = 300s` (tempo para o worker processar um arquivo)
  - `message_retention = 4 dias`
- Dead Letter Queue: `wiki-rag-dev-ingestion-dlq`
  - Recebe mensagens após 3 tentativas falhas
  - Retenção: 14 dias

### `lambda`
- Função `wiki-rag-dev-docx-extractor`
- Runtime: Python 3.11
- Extrai imagens de arquivos `.docx` enviados via S3
- Invocada pelo worker antes de ingerir arquivos `.docx`

### `iam`
- IAM Role `wiki-rag-dev-wiki-rag` (IRSA para os pods)
  - Trust policy: assume via OIDC do EKS para a ServiceAccount `wiki-rag` no namespace `wiki-rag`
  - Policies anexadas:
    - Bedrock: `InvokeModel` nos modelos Titan + Nova Lite
    - Secrets Manager: `GetSecretValue` em `wiki-rag-dev/*`
    - S3: `GetObject`, `PutObject`, `DeleteObject`, `ListBucket`
    - SQS: `SendMessage`, `ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`
    - Lambda: `InvokeFunction` no docx-extractor

### `secrets`
- Secret `wiki-rag-dev/app` no Secrets Manager
- Contém: `database_url`, `database_url_sync`
- Lido pelo CI/CD na hora do deploy para criar o K8s Secret `wiki-rag-db-secret`

### `bastion`
- EC2 `t3.micro` na subnet pública
- IAM Role com `AmazonSSMManagedInstanceCore` (acesso via SSM, sem abrir porta 22)
- Security group sem inbound rules (acesso só via SSM Session Manager)
- Usado para: acessar RDS, rodar `kubectl`, debug

### `ci`
- IAM Role `wiki-rag-dev-github-actions`
  - Trust policy: assume via OIDC do GitHub Actions (repositório específico)
  - Policies: ECR push, EKS `update-kubeconfig`, Secrets Manager read, S3 state

## Comandos

```bash
# Inicializar (primeira vez)
cd terraform/environments/dev
terraform init

# Ver o que vai criar/modificar
terraform plan

# Aplicar
terraform apply

# Destruir tudo
terraform destroy

# Ver outputs (URLs, ARNs, nomes)
terraform output
```

## Remote state

O state do Terraform fica num bucket S3 separado:
- Bucket: `wiki-rag-terraform-state-{account_id}`
- Key: `dev/terraform.tfstate`
- Locking via DynamoDB: `wiki-rag-terraform-locks`

Esse bucket **não é destruído** pelo `terraform destroy` — é criado manualmente antes do primeiro apply.

## Ver também

- [[05-CI-CD]] — como o GitHub Actions usa a infraestrutura
- [[08-Kubernetes]] — os manifests que rodam no EKS
