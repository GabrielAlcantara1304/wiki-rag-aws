---
tags: [wiki-rag, evidências, prints, validação]
---

# Evidências de Funcionamento

Checklist de prints para provar que o sistema está funcionando por completo.

---

## 1. CI/CD passando

**Onde:** GitHub → aba Actions → workflow "Deploy to EKS"

**O que mostrar:** Pipeline verde com todos os steps concluídos:
- Checkout ✓
- Configure AWS credentials ✓
- Login to Amazon ECR ✓
- Build and push image ✓
- Configure kubectl ✓
- Apply base manifests ✓
- Run Alembic migrations ✓
- Deploy new image ✓
- Apply HPA ✓

**Prova:** ECR push funcionou + EKS deploy funcionou + Secrets Manager lido.

---

## 2. Pods rodando no EKS

**Onde:** Terminal (bastion ou CI) ou AWS Console → EKS → Workloads

**Comando:**
```bash
kubectl get pods -n wiki-rag
```

**O que mostrar:**
```
NAME                              READY   STATUS    RESTARTS
wiki-rag-xxxxx-yyyyy              1/1     Running   0
wiki-rag-xxxxx-zzzzz              1/1     Running   0
wiki-rag-worker-xxxxx-yyyyy       1/1     Running   0
```

**Prova:** EKS funcionando, imagem do ECR carregada, IRSA injetando credenciais.

---

## 3. Health check

**Onde:** Browser ou curl

```
http://<ELB>/health
```

**O que mostrar:**
```json
{"status": "ok", "environment": "production"}
```

**Prova:** API pod respondendo, banco conectado.

---

## 4. Upload pela UI

**Onde:** `http://<ELB>/ui/ingest.html`

**O que mostrar:** Após arrastar arquivos e clicar "Enviar e ingerir":
```
✓ 5 arquivo(s) enviado(s) para processamento. O worker irá gerar os embeddings em breve.
[Enfileirados: 5]   [Job ID: abc12345…]
```

**Prova:** API pod recebeu o upload, escreveu no S3 e enviou mensagem ao SQS.

---

## 5. Arquivos no S3

**Onde:** AWS Console → S3 → `wiki-rag-dev-{account_id}`

**O que mostrar:**
- Pasta `uploads/{job_id}/` com os arquivos enviados (staging)
- Pasta `documents/{repo_hash}/` com os arquivos permanentes (após o worker processar)

**Prova:** Worker baixou do staging, processou e gravou a cópia permanente.

---

## 6. SQS — mensagens processadas

**Onde:** AWS Console → SQS → `wiki-rag-dev-ingestion` → aba **Monitoring**

**O que mostrar:** Gráfico com:
- `NumberOfMessagesSent` com pico no momento do upload
- `NumberOfMessagesDeleted` com o mesmo número pouco depois

**Ou:** `Messages Available = 0` na fila principal (tudo processado).

**Prova:** Worker consumiu e processou todas as mensagens com sucesso.

---

## 7. Embeddings no banco

**Onde:** Terminal no bastion → psql

```sql
SELECT d.title, d.s3_key, COUNT(c.id) AS chunks
FROM documents d
JOIN sections s ON s.document_id = d.id
JOIN chunks c ON c.section_id = s.id
WHERE c.embedding IS NOT NULL
GROUP BY d.id, d.title, d.s3_key
LIMIT 10;
```

**O que mostrar:** Linhas com `s3_key` preenchido e `chunks > 0`.

**Prova:** Fluxo completo funcionou — upload → S3 → SQS → worker → Bedrock Titan → RDS.

---

## 8. Pergunta e resposta na UI

**Onde:** `http://<ELB>/ui`

**O que mostrar:**
- Campo de pergunta preenchido com algo relacionado ao documento ingerido
- Resposta gerada com fontes citadas embaixo (título do documento, seção, similaridade)

**Prova:** Bedrock Titan (embed da query) + pgvector (busca) + cross-encoder (reranking) + Bedrock Nova Lite (geração) — tudo funcionando.

---

## 9. ECR com imagem

**Onde:** AWS Console → ECR → repositório `wiki-rag-api`

**O que mostrar:** Imagem com tag `:latest` e a tag do commit SHA (ex: `:a1b2c3d4...`), com data recente.

**Prova:** Build Docker funcionou e push para o ECR foi bem-sucedido.

---

## 10. RDS disponível

**Onde:** AWS Console → RDS → instâncias

**O que mostrar:** Instância `wiki-rag-dev` com status **Available**.

**Prova:** Banco provisionado e acessível.

---

## Resumo — qual print prova o quê

| Print | Serviços validados |
|---|---|
| GitHub Actions verde | ECR, EKS, Secrets Manager, GitHub OIDC |
| Pods Running | EKS, ECR, IRSA |
| Health check OK | API pod, RDS |
| Upload com Job ID | API pod, S3, SQS |
| Arquivos em `documents/` no S3 | Worker pod, S3 |
| SQS `Deleted = Sent` | SQS, Worker pod |
| SQL com embeddings | RDS, Bedrock Titan, Worker pod |
| Resposta com fontes na UI | Bedrock Nova Lite, pgvector, cross-encoder |
| ECR com imagem | ECR, Docker build |
| RDS Available | RDS, Terraform |

**O combo mais importante:** prints **7 + 8** — provam o ciclo completo de ingestão e recuperação.
