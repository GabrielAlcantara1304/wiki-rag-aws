---
tags: [wiki-rag, worker, bedrock, embeddings, rds, s3]
---

# Worker — Processamento de Arquivos

O worker é um pod separado que roda em loop infinito consumindo a fila SQS.
Ele faz todo o trabalho pesado: parse, chunking, embeddings, armazenamento.

## Por que existe um worker separado?

Gerar embeddings via Bedrock leva ~1-3 segundos por arquivo.
Se isso fosse feito no pod da API, o usuário ficaria esperando o upload travar.
O worker desacopla o upload (rápido) do processamento (lento).

## Loop de consumo SQS

```
while True:
    mensagens = SQS.receive_message(
        MaxNumberOfMessages = 10,
        WaitTimeSeconds     = 20   ← long polling, economiza chamadas à API
    )

    para cada mensagem:
        processar(mensagem)
        SQS.delete_message()    ← só deleta se processou com sucesso

        se der erro:
            não deleta           ← SQS retenta automaticamente
            após N tentativas → DLQ (Dead Letter Queue)
```

## Processamento de uma mensagem

```
Mensagem SQS:
{
  "file_key":    "uploads/abc123/docs/Home.md",
  "repo_url":    "upload:abc123",
  "file_name":   "Home.md",
  "rel_path":    "docs/Home.md",
  "commit_hash": "def456..." (ou ausente para uploads)
}

1. S3.download_file
   uploads/abc123/docs/Home.md → /tmp/tmpXXX/docs/Home.md
   (preserva estrutura de pastas)

2. Se .docx e Lambda configurada:
   Lambda.invoke(docx-extractor)  → extrai imagens do .docx

3. Parse do arquivo
   .md   → markdown_parser  → título, seções, assets
   .docx → docx_parser      → mesmo formato
   .txt  → markdown_parser  → trata como markdown simples

4. DELETE do registro antigo no banco (se existia)
   DELETE FROM documents WHERE repo=? AND path=?
   (cascata: apaga sections, chunks, assets)

5. Chunking
   Para cada seção:
     └─ Divide em chunks de ~800 tokens com overlap de 100

6. Bedrock — Titan Text Embeddings V2
   embed_texts([chunk1, chunk2, ..., chunkN])
   └─ 1024 dimensões por chunk
   └─ Chamadas em paralelo para maximizar throughput

7. S3 — armazenamento permanente do documento
   PUT s3://bucket/documents/{repo_hash}/docs/Home.md
   └─ Conteúdo: raw markdown/texto completo

8. RDS — INSERT
   ├─ documents  (título, repo, path, s3_key, commit_hash)
   ├─ sections   (heading, level, order_index, content)
   ├─ chunks     (chunk_text, token_count, embedding[1024])
   └─ assets     (imagens referenciadas)

   Chunks formam lista duplamente encadeada:
   chunk[0].next_chunk_id = chunk[1].id
   chunk[1].prev_chunk_id = chunk[0].id
   (usada na recuperação para expandir contexto)

9. SQS.delete_message  ← processamento concluído
```

## O que fica onde após o processamento

```
S3:
  uploads/abc123/docs/Home.md     ← original (staging, pode expirar)
  documents/{repo_hash}/docs/Home.md  ← permanente

RDS:
  documents  → metadados + s3_key
  sections   → estrutura do documento
  chunks     → texto + embedding vetorial (1024 dims)
  assets     → referências a imagens
```

## Gargalos e performance

| Etapa | Tempo típico | Observação |
|---|---|---|
| S3 download | ~50ms | Rápido, mesma região |
| Parse | ~10ms | CPU local |
| Chunking | ~10ms | CPU local |
| Bedrock embed | ~500ms–2s | Depende do nº de chunks e rate limit |
| S3 upload (permanente) | ~50ms | |
| RDS insert | ~50ms | |
| **Total por arquivo** | **~1–4s** | Bedrock é o gargalo |

Para 582 arquivos: **~10–40 minutos** com 1 worker.

## Escalar o worker

```bash
# Aumentar para 3 workers (processa ~3x mais rápido)
kubectl scale deployment wiki-rag-worker --replicas=3 -n wiki-rag

# Voltar para 1 depois
kubectl scale deployment wiki-rag-worker --replicas=1 -n wiki-rag
```

Cuidado: múltiplos workers podem atingir os rate limits do Bedrock mais rapidamente.

## Monitorar em tempo real

```bash
# Logs do worker
kubectl logs -f -l app=wiki-rag-worker -n wiki-rag

# Progresso no banco
SELECT COUNT(*) as documentos FROM documents;
SELECT COUNT(*) as chunks_com_embedding FROM chunks WHERE embedding IS NOT NULL;
```

## Ver também

- [[01-Upload-e-Ingestão]] — como os arquivos chegam na fila
- [[02-Ingestão-Git]] — ingestão de repositório git
- [[04-QA-Retrieval]] — como os embeddings são usados nas perguntas
- [[06-Armazenamento]] — detalhes do S3 vs RDS
