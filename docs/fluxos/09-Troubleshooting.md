---
tags: [wiki-rag, troubleshooting, erros, debug]
---

# Troubleshooting — Erros Encontrados e Soluções

Registro dos principais problemas encontrados durante o desenvolvimento e como foram resolvidos.

---

## kubectl: `server has asked for credentials`

**Sintoma:** `kubectl get pods` retorna erro de autenticação.

**Causa:** O IAM Role do GitHub Actions ou do bastion não estava autorizado no EKS.

**Solução:** Adicionar `aws_eks_access_entry` + `aws_eks_access_policy_association` no Terraform para ambos os roles, com policy `AmazonEKSClusterAdminPolicy`.

```hcl
resource "aws_eks_access_entry" "github_actions" {
  cluster_name  = module.eks.cluster_name
  principal_arn = module.ci.github_actions_role_arn
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "github_actions" {
  cluster_name  = module.eks.cluster_name
  principal_arn = module.ci.github_actions_role_arn
  policy_arn    = "arn:aws:iam::aws:policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}
```

---

## Migration job timeout: `DATABASE_URL` não disponível

**Sintoma:** Job `wiki-rag-migrate` falha com `KeyError: DATABASE_URL`.

**Causa:** O pod não tinha acesso à string de conexão do banco — ela estava no Secrets Manager mas não no pod.

**Solução:** CI/CD busca o secret do Secrets Manager e cria um K8s Secret `wiki-rag-db-secret`. Os pods carregam via `envFrom.secretRef`.

```bash
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id wiki-rag-dev/app --query SecretString --output text)
kubectl create secret generic wiki-rag-db-secret \
  --from-literal=DATABASE_URL="$(echo $SECRET_JSON | python3 -c '...')" \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## RDS inacessível dos pods

**Sintoma:** Pods travam na conexão com o banco, timeout.

**Causa:** `allowed_security_group_ids = []` no módulo RDS — nenhum SG tinha permissão de conectar na porta 5432.

**Solução:**
```hcl
allowed_security_group_ids = [module.eks.cluster_security_group_id]
```

---

## ConfigMap com sed substituindo valores errados

**Sintoma:** `SQS_INGESTION_QUEUE_URL` recebia o valor do S3 bucket.

**Causa:** Os três placeholders no ConfigMap eram idênticos (`REPLACE_WITH_TERRAFORM_OUTPUT`). O primeiro `sed` substituía todos.

**Solução:** Placeholders únicos por variável:
```
REPLACE_WITH_TERRAFORM_OUTPUT  → SQS URL
REPLACE_WITH_S3_BUCKET         → S3 bucket
REPLACE_WITH_LAMBDA_NAME       → Lambda name
```

---

## `getpwuid uid not found: 1000`

**Sintoma:** Pod crasha com erro do PyTorch sobre UID 1000.

**Causa:** O Dockerfile criava o usuário sem `--home` e sem entrada no `/etc/passwd`.

**Solução:**
```dockerfile
RUN addgroup --gid 1000 appuser \
 && adduser --uid 1000 --gid 1000 --home /home/appuser \
            --disabled-password --gecos "" appuser
```

---

## `PermissionError` no modelo de reranking

**Sintoma:** Pod crasha ao tentar carregar o cross-encoder.

**Causa:** O modelo tentava escrever cache em `/home/appuser` mas o diretório não existia.

**Solução:** Criar o home directory + pré-baixar o modelo no build:
```dockerfile
RUN python -c "from sentence_transformers import CrossEncoder; \
    CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)"
```

---

## IRSA annotation vazia (ServiceAccount sem role)

**Sintoma:** Pods sem permissão AWS — Bedrock, S3, SQS retornam `AccessDenied`.

**Causa:** `WIKI_RAG_ROLE_ARN` não estava configurado como variável no GitHub.

**Solução:** Hardcodar o ARN diretamente no `k8s/serviceaccount.yaml`:
```yaml
eks.amazonaws.com/role-arn: "arn:aws:iam::406951616480:role/wiki-rag-dev-wiki-rag"
```

---

## Bastion: `i/o timeout` no kubectl

**Sintoma:** `kubectl` funciona no CI mas não no bastion.

**Causa:** O Security Group do bastion não tinha regra para alcançar o endpoint privado do EKS (porta 443).

**Solução:**
```hcl
resource "aws_vpc_security_group_ingress_rule" "eks_from_bastion" {
  security_group_id            = module.eks.cluster_security_group_id
  referenced_security_group_id = module.bastion.security_group_id
  from_port = 443
  to_port   = 443
  ip_protocol = "tcp"
}
```

---

## `ValidationException` no Claude Haiku

**Sintoma:** Bedrock retorna erro ao chamar `anthropic.claude-3-5-haiku-20241022-v1:0`.

**Causa:** Modelos Anthropic em regiões cross-region precisam do prefixo de inference profile.

**Solução:** Usar `us.anthropic.claude-3-5-haiku-20241022-v1:0` — mas mesmo assim exige aceitar os termos no AWS Marketplace.

**Alternativa adotada:** Trocar para `amazon.nova-lite-v1:0` (sem restrições de Marketplace).

---

## `AccessDeniedException` no Nova Lite

**Sintoma:** Bedrock retorna `AccessDeniedException` ao chamar Nova Lite.

**Causa:** O IAM Policy do IRSA não incluía o ARN do Nova Lite nos recursos permitidos.

**Solução:** Adicionar ao módulo IAM:
```hcl
"arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.nova-lite-v1:0",
"arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.nova-micro-v1:0",
```

---

## Disk pressure no node EKS

**Sintoma:** Pod fica em `Pending` com evento `0/1 nodes available: 1 node(s) had untolerated taint {node.kubernetes.io/disk-pressure}`.

**Causa:** Disco de 20GB (padrão do node group) cheio — PyTorch + transformers + modelo de reranking ocupam ~15GB.

**Solução:**
```hcl
resource "aws_eks_node_group" "this" {
  disk_size = 50  # era 20
  ...
}
```

---

## Warning: `Could not get commit hash for arquivo.md: /tmp/tmpXXX`

**Sintoma:** Worker loga WARNING tentando rodar `git log` em diretório temporário.

**Causa:** O pipeline tentava computar o commit hash do git mesmo no worker, onde não há repositório git — apenas o arquivo baixado do S3.

**Solução:** Sentinel `_UNSET` na função `_ingest_file`:
- Default `_UNSET` → computa do git (fluxo `run_ingestion` com repo real)
- `None` explícito → não tenta git, armazena NULL (fluxo worker/upload)
- `str` → usa o hash passado via mensagem SQS (fluxo `/ingest` git)

---

## Frontend: botões de upload não aparecem

**Sintoma:** Ao enviar pasta grande, a lista de arquivos empurra o botão "Enviar" para fora da tela.

**Solução:** `max-height: 260px` + `overflow-y: auto` na `.file-list`.

---

## Ver também

- [[01-Upload-e-Ingestão]] — fluxo de upload
- [[05-CI-CD]] — pipeline de deploy
- [[07-Infraestrutura-Terraform]] — infraestrutura AWS
