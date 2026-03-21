---
tags: [wiki-rag, ingestão, upload, s3, sqs]
---

# Upload de Arquivos e Pastas

Endpoint: `POST /upload`
UI: `/ui/ingest.html` — card "Upload de arquivos"

## O que o usuário pode enviar

- Arquivos individuais (`.md`, `.docx`, `.txt`) arrastados ou selecionados
- Pastas inteiras — o browser percorre subpastas recursivamente via `webkitGetAsEntry()`
- Múltiplos arquivos de uma vez

## Fluxo completo

```
1. Browser
   └─ Usuário arrasta pasta ou clica "Selecionar pasta"
   └─ JS percorre subpastas (DataTransferItem.webkitGetAsEntry)
   └─ Lista arquivos com path relativo (ex: docs/Home.md)
   └─ FormData: fd.append('files', file, relativePath)
   └─ POST /upload  (multipart/form-data)

2. API pod — POST /upload
   ├─ Valida extensões (.md / .docx / .txt)
   ├─ Gera job_id (UUID)
   └─ Para cada arquivo:
        ├─ S3.put_object
        │    Key: uploads/{job_id}/{rel_path}
        │    Ex:  uploads/abc123/docs/Home.md
        │
        └─ SQS.send_message
             {
               "file_key":    "uploads/abc123/docs/Home.md",
               "repo_url":    "upload:abc123",
               "file_name":   "Home.md",
               "rel_path":    "docs/Home.md",
               "job_id":      "abc123"
             }

3. API responde imediatamente
   {
     "status":  "queued",
     "job_id":  "abc123",
     "queued":  582,
     "total":   582,
     "message": "582 arquivo(s) enviado(s) para processamento."
   }

4. Worker processa em background
   └─ Ver [[03-Worker-Processamento]]
```

## Onde ficam os arquivos no S3

| Prefixo | O que é | Lifecycle |
|---|---|---|
| `uploads/{job_id}/` | Staging — arquivo original enviado pelo usuário | Pode ter lifecycle de 7 dias |
| `documents/{repo_hash}/` | Permanente — cópia feita pelo worker após processar | Mantido indefinidamente |

## Por que a resposta é imediata (assíncrona)

O processamento (parse + embedding + banco) pode levar segundos por arquivo.
Para 582 arquivos, o total pode ser 30–50 minutos.
O endpoint retorna o `job_id` na hora; o worker processa em background.

## Como monitorar o progresso

```bash
# Logs do worker em tempo real
kubectl logs -f -l app=wiki-rag-worker -n wiki-rag

# Quantos documentos já foram indexados
# (via bastion → psql)
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL;
```

No Console AWS → SQS → fila `wiki-rag-dev-ingestion`:
- **Messages Available** = ainda na fila
- **Messages in Flight** = sendo processadas agora
- Se `Available = 0` e `In Flight = 0` → tudo processado

## Escalando o worker para processar mais rápido

```bash
kubectl scale deployment wiki-rag-worker --replicas=3 -n wiki-rag
```

3 workers consomem a fila em paralelo, reduzindo o tempo proporcionalmente.
Lembre de voltar para 1 depois para economizar.

## Ver também

- [[03-Worker-Processamento]] — o que acontece depois do SQS
- [[06-Armazenamento]] — S3 vs RDS em detalhe
