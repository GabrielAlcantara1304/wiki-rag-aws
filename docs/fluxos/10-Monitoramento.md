---
tags: [wiki-rag, monitoramento, logs, kubectl, cloudwatch, sqs]
---

# Monitoramento

## Logs dos pods (tempo real)

```bash
# API pod
kubectl logs -f -l app=wiki-rag -n wiki-rag

# Worker pod
kubectl logs -f -l app=wiki-rag-worker -n wiki-rag

# Últimas 100 linhas
kubectl logs --tail=100 -l app=wiki-rag-worker -n wiki-rag
```

---

## Progresso da ingestão

### Via banco (psql no bastion)

```bash
# Conectar ao RDS via bastion
psql $DATABASE_URL_SYNC
```

```sql
-- Resumo geral
SELECT
  COUNT(DISTINCT d.id)   AS documentos,
  COUNT(DISTINCT s.id)   AS secoes,
  COUNT(c.id)            AS chunks_total,
  COUNT(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS chunks_indexados
FROM documents d
LEFT JOIN sections s ON s.document_id = d.id
LEFT JOIN chunks   c ON c.section_id  = s.id;

-- Últimos documentos processados
SELECT title, path, s3_key, created_at
FROM documents
ORDER BY created_at DESC
LIMIT 20;

-- Documentos sem s3_key (não processados pelo worker ainda)
SELECT COUNT(*) FROM documents WHERE s3_key IS NULL;
```

### Via SQS (Console AWS)

`AWS Console → SQS → wiki-rag-dev-ingestion`

| Métrica | Significado |
|---|---|
| Messages Available | Ainda aguardando o worker |
| Messages in Flight | Sendo processadas agora |
| Messages Delayed | Agendadas para retry |

Quando `Available = 0` e `In Flight = 0` → tudo processado.

Aba **Monitoring** mostra gráficos de:
- `NumberOfMessagesSent` — enviadas pela API
- `NumberOfMessagesDeleted` — processadas com sucesso pelo worker
- `ApproximateAgeOfOldestMessage` — se crescer, worker está lento ou parado

### Dead Letter Queue

`AWS Console → SQS → wiki-rag-dev-ingestion-dlq`

Se tiver mensagens aqui, significa que um arquivo falhou 3 vezes.
Para reprocessar:
1. Ver o conteúdo da mensagem (qual arquivo falhou)
2. Corrigir o problema
3. Mover as mensagens de volta para a fila principal

---

## Status dos pods

```bash
# Ver todos os pods
kubectl get pods -n wiki-rag

# Ver uso de CPU e memória
kubectl top pods -n wiki-rag

# Ver eventos (útil para debug de CrashLoop)
kubectl describe pod <nome-do-pod> -n wiki-rag

# HPA — ver quando está escalando
kubectl get hpa -n wiki-rag
```

---

## Health check da aplicação

```
GET http://<ELB>/health
```

Resposta esperada:
```json
{"status": "ok", "environment": "production"}
```

```
GET http://<ELB>/docs
```

Swagger UI com todos os endpoints.

---

## CloudWatch Logs

`AWS Console → CloudWatch → Log Groups`

Os logs do EKS ficam em `/aws/eks/wiki-rag-dev/cluster`.
Os logs dos containers ficam no Fluent Bit (se configurado) ou só via `kubectl logs`.

---

## Evidências de funcionamento (prints)

Ver [[11-Evidências]] para a lista completa de prints que provam o sistema funcionando.

---

## Custo estimado (quando rodando)

| Serviço | Custo/hora | Custo/mês |
|---|---|---|
| EKS nodes (2x t3.medium) | ~$0.08 | ~$60 |
| NAT Gateway | ~$0.045 | ~$35 |
| RDS db.t3.medium | ~$0.068 | ~$50 |
| Load Balancer | ~$0.025 | ~$18 |
| Bedrock (por uso) | variável | depende do volume |
| S3, SQS, ECR | ~$0 | <$5 |
| **Total estimado** | **~$0.22/h** | **~$165/mês** |

### Parar tudo para economizar

```bash
# 1. Remove o Load Balancer (não gerenciado pelo Terraform)
kubectl delete namespace wiki-rag

# 2. Destrói toda a infraestrutura
cd terraform/environments/dev
terraform destroy -auto-approve
```

### Recriar tudo

```bash
terraform apply -auto-approve
# Depois rodar o pipeline no GitHub Actions (push na main)
```

O código e histórico ficam no GitHub. Os documentos precisam ser re-ingeridos (RDS é novo).

## Ver também

- [[03-Worker-Processamento]] — o que o worker processa
- [[06-Armazenamento]] — queries úteis no banco
