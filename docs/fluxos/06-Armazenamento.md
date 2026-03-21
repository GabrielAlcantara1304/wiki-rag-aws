---
tags: [wiki-rag, s3, rds, pgvector, banco-de-dados, armazenamento]
---

# Armazenamento — S3 vs RDS

## Princípio

> **S3 guarda os documentos completos. RDS guarda apenas embeddings e metadados.**

Antes desta separação, o RDS armazenava `raw_markdown` e `rendered_text` de cada documento — o conteúdo completo ficava duplicado no banco. Isso foi removido na migration `004`.

## S3

Bucket: `wiki-rag-dev-{account_id}`

### Estrutura de prefixos

```
bucket/
├── uploads/
│   └── {job_id}/
│       └── docs/Home.md          ← arquivo original enviado (staging)
│                                   pode ter lifecycle de 7 dias
│
└── documents/
    └── {repo_hash}/              ← primeiros 12 chars do SHA256 do repo_url
        └── docs/Home.md          ← cópia permanente, gravada pelo worker
```

### Quando cada prefixo é escrito

| Quem escreve | Prefixo | Momento |
|---|---|---|
| API pod (`/upload`, `/ingest`) | `uploads/` | Na hora do upload/ingest |
| Worker pod (pipeline) | `documents/` | Após processar com sucesso |

### `s3_key` no banco

A tabela `documents` guarda o campo `s3_key` com o path permanente:
```
documents.s3_key = "documents/a1b2c3d4e5f6/docs/Home.md"
```

Para recuperar o arquivo completo:
```python
s3.get_object(Bucket="wiki-rag-dev-...", Key=document.s3_key)
```

## RDS — PostgreSQL 16 + pgvector

Instância: `db.t3.medium`, Multi-AZ desabilitado (dev)
Banco: `wiki_rag`

### Tabelas

#### `documents`
Metadados do documento. **Não contém o texto completo.**

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | UUID PK | |
| `repo` | VARCHAR(500) | URL do repo ou identificador de upload |
| `path` | VARCHAR(1000) | Path relativo dentro do repo (ex: `docs/Home.md`) |
| `title` | VARCHAR(500) | Primeiro H1 ou nome do arquivo |
| `s3_key` | VARCHAR(1000) | Onde está o documento completo no S3 |
| `commit_hash` | VARCHAR(40) | SHA do git no momento da ingestão (para detecção incremental) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

Constraint única: `(repo, path)` — impede duplicação.

#### `sections`
Seções do documento (delimitadas por headings H1–H3).

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK → documents | |
| `heading` | VARCHAR(500) | Texto do heading (NULL para conteúdo antes do primeiro heading) |
| `level` | INTEGER | 0=raiz, 1=H1, 2=H2, 3=H3 |
| `content` | TEXT | Texto completo da seção |
| `order_index` | INTEGER | Posição dentro do documento |

#### `chunks` ← **tabela principal para retrieval**
Fatias de seções com embeddings vetoriais.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | UUID PK | |
| `section_id` | UUID FK → sections | |
| `chunk_index` | INTEGER | Posição dentro da seção |
| `chunk_text` | TEXT | Texto do chunk (enviado ao Bedrock + retornado como fonte) |
| `token_count` | INTEGER | |
| `embedding` | Vector(1024) | Vetor gerado pelo Titan Text V2 |
| `previous_chunk_id` | UUID FK → chunks | Lista encadeada para expansão de contexto |
| `next_chunk_id` | UUID FK → chunks | |

Índice HNSW no campo `embedding`:
```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

#### `assets`
Imagens e mídias referenciadas nos documentos.

| Coluna | Tipo | Descrição |
|---|---|---|
| `document_id` | UUID FK | |
| `file_path` | VARCHAR(1000) | Path/URL como aparece no markdown |
| `alt_text` | TEXT | |
| `context` | TEXT | Parágrafo ao redor da imagem |

#### `knowledge_gaps`
Perguntas sem resposta boa (similaridade baixa).

| Coluna | Tipo | Descrição |
|---|---|---|
| `question` | TEXT | Pergunta que não teve resposta |
| `max_similarity` | FLOAT | Maior similaridade encontrada |
| `source` | VARCHAR(20) | `auto` (baixa sim.) ou `manual` (feedback) |
| `status` | VARCHAR(20) | `open` ou `resolved` |
| `detected_at` | TIMESTAMP | |

### Migrations Alembic

| Arquivo | O que fez |
|---|---|
| `001_initial_schema` | Criou todas as tabelas com Vector(1536) — OpenAI |
| `002_knowledge_gaps` | Adicionou tabela `knowledge_gaps` |
| `003_bedrock_embeddings` | Trocou Vector(1536) → Vector(1024) para Titan V2 |
| `004_s3_document_storage` | Removeu `raw_markdown` e `rendered_text`, adicionou `s3_key` |

### Consultas úteis

```sql
-- Quantos documentos e chunks indexados
SELECT
  COUNT(DISTINCT d.id)               AS documentos,
  COUNT(DISTINCT s.id)               AS secoes,
  COUNT(c.id)                        AS chunks,
  COUNT(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS chunks_com_embedding
FROM documents d
LEFT JOIN sections s ON s.document_id = d.id
LEFT JOIN chunks   c ON c.section_id  = s.id;

-- Documentos com s3_key preenchido (processados pelo worker)
SELECT title, path, s3_key, commit_hash
FROM documents
WHERE s3_key IS NOT NULL
ORDER BY created_at DESC
LIMIT 20;

-- Lacunas abertas
SELECT question, max_similarity, detected_at
FROM knowledge_gaps
WHERE status = 'open'
ORDER BY detected_at DESC;
```

## Ver também

- [[03-Worker-Processamento]] — quando e como os dados são gravados
- [[04-QA-Retrieval]] — como o pgvector é consultado nas perguntas
