---
tags: [wiki-rag, kubernetes, eks, k8s, hpa]
---

# Kubernetes — Manifests e Recursos

Diretório: `k8s/`
Namespace: `wiki-rag`

## Recursos criados

| Arquivo | Tipo | Nome |
|---|---|---|
| `namespace.yaml` | Namespace | `wiki-rag` |
| `serviceaccount.yaml` | ServiceAccount | `wiki-rag` |
| `configmap.yaml` | ConfigMap | `wiki-rag-config` |
| `deployment.yaml` | Deployment | `wiki-rag` (API) |
| `worker-deployment.yaml` | Deployment | `wiki-rag-worker` |
| `service.yaml` | Service | `wiki-rag` (LoadBalancer) |
| `hpa.yaml` | HorizontalPodAutoscaler | `wiki-rag` |
| `job-migrate.yaml` | Job | `wiki-rag-migrate` |

## ServiceAccount e IRSA

```yaml
metadata:
  name: wiki-rag
  namespace: wiki-rag
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::406951616480:role/wiki-rag-dev-wiki-rag"
```

A anotação faz o EKS injetar credenciais AWS temporárias nos pods que usam essa ServiceAccount.
Sem isso, os pods não conseguem chamar Bedrock, S3, SQS, etc.

## ConfigMap — variáveis de ambiente

Aplicado pelo CI/CD com os valores reais substituídos via `sed`:

```yaml
AWS_REGION: "us-east-1"
BEDROCK_EMBED_MODEL: "amazon.titan-embed-text-v2:0"
BEDROCK_EMBED_DIMENSIONS: "1024"
BEDROCK_CHAT_MODEL: "amazon.nova-lite-v1:0"
RETRIEVAL_TOP_K: "10"
RETRIEVAL_SIMILARITY_THRESHOLD: "0.5"
CONTEXT_WINDOW_CHUNKS: "2"
MAX_CHUNK_TOKENS: "800"
CHUNK_OVERLAP_TOKENS: "100"
GENERATION_TEMPERATURE: "0.1"
CONVERSATION_HISTORY_TURNS: "3"
SQS_INGESTION_QUEUE_URL: "<injetado pelo CI>"
S3_BUCKET: "<injetado pelo CI>"
LAMBDA_DOCX_EXTRACTOR_NAME: "<injetado pelo CI>"
```

## K8s Secret — credenciais do banco

Criado pelo CI/CD (não está no repositório):
```bash
kubectl create secret generic wiki-rag-db-secret \
  --from-literal=DATABASE_URL="postgresql+asyncpg://..." \
  --from-literal=DATABASE_URL_SYNC="postgresql://..."
```

Os pods carregam via `envFrom.secretRef`.

## Deployment — API pod

```
Réplicas:  2 (mínimo, controlado pelo HPA)
Imagem:    {ECR_URL}:{git_sha}
Comando:   uvicorn app.main:app --host 0.0.0.0 --port 8000
Porta:     8000

envFrom:
  - configMapRef: wiki-rag-config
  - secretRef:    wiki-rag-db-secret

Resources:
  requests: cpu 250m, memory 512Mi
  limits:   cpu 1000m, memory 1Gi

LivenessProbe:  GET /health
ReadinessProbe: GET /health
```

## Deployment — Worker pod

```
Réplicas:  1
Imagem:    mesma do API pod
Comando:   python -m app.ingestion.worker

envFrom:
  - configMapRef: wiki-rag-config
  - secretRef:    wiki-rag-db-secret

Sem porta exposta — só consome SQS
```

Escalar para processar mais rápido:
```bash
kubectl scale deployment wiki-rag-worker --replicas=3 -n wiki-rag
```

## Service — LoadBalancer

```yaml
type: LoadBalancer
port: 80 → targetPort: 8000
```

Cria um AWS Classic Load Balancer automaticamente.
O ELB URL é o endereço público da aplicação.

Pegar o endereço:
```bash
kubectl get svc wiki-rag -n wiki-rag
```

## HPA — Auto Scaling

```
minReplicas: 2
maxReplicas: 10

Escala quando:
  CPU    > 60%
  Memória > 75%
```

O HPA só funciona se o `metrics-server` estiver instalado no cluster.

## Job — Migrations

Roda antes de cada deploy para aplicar as migrations do Alembic:
```bash
alembic upgrade head
```

O CI aguarda o job completar (`kubectl wait --for=condition=complete`) antes de fazer o rollout do deployment. Se falhar, o deploy para.

## Comandos úteis

```bash
# Ver todos os recursos do namespace
kubectl get all -n wiki-rag

# Logs da API
kubectl logs -f -l app=wiki-rag -n wiki-rag

# Logs do worker
kubectl logs -f -l app=wiki-rag-worker -n wiki-rag

# Entrar num pod da API
kubectl exec -it deployment/wiki-rag -n wiki-rag -- bash

# Ver uso de recursos
kubectl top pods -n wiki-rag

# Reiniciar os pods (sem downtime)
kubectl rollout restart deployment/wiki-rag -n wiki-rag
```

## Ver também

- [[07-Infraestrutura-Terraform]] — o EKS que roda esses manifests
- [[05-CI-CD]] — como os manifests são aplicados no deploy
