---
tags: [wiki-rag, ingestão, git, s3, sqs]
---

# Ingestão de Repositório Git

Endpoint: `POST /ingest`
UI: `/ui/ingest.html` — card "Pasta local (servidor)"
Também aceita: `repo_url` (git clone remoto) ou `local_path` (pasta já no servidor)

## Diferença em relação ao upload

| | Upload (`/upload`) | Ingest Git (`/ingest`) |
|---|---|---|
| Fonte | Arquivos enviados pelo browser | Repositório git ou pasta do servidor |
| Detecção de mudanças | Sempre processa tudo | Compara commit hash — pula arquivos não alterados |
| `commit_hash` no SQS | Não tem (NULL) | Tem — usado para detecção incremental futura |

## Fluxo completo

```
1. POST /ingest  { "repo_url": "https://github.com/org/wiki.git", "force_all": false }

2. API pod
   ├─ Se repo_url: git clone / git pull → /tmp/wiki_repos/{hash}/
   ├─ Se local_path: usa a pasta diretamente
   │
   ├─ Lista todos os .md / .docx / .txt
   │
   ├─ Detecta arquivos alterados (DB)
   │    SELECT commit_hash FROM documents WHERE repo=? AND path=?
   │    Compara com git log --format=%H -1 -- <arquivo>
   │    Resultado: [changed_files], [unchanged_files]
   │
   └─ Para cada arquivo alterado:
        ├─ Lê conteúdo do disco
        ├─ get_file_commit_hash(local_path, rel_path) → "abc123..."
        │
        ├─ S3.put_object
        │    Key: uploads/{job_id}/{rel_path}
        │
        └─ SQS.send_message
             {
               "file_key":    "uploads/{job_id}/docs/Home.md",
               "repo_url":    "https://github.com/org/wiki.git",
               "file_name":   "Home.md",
               "rel_path":    "docs/Home.md",
               "commit_hash": "abc123...",
               "job_id":      "{job_id}"
             }

3. API responde imediatamente
   {
     "status":  "queued",
     "job_id":  "...",
     "queued":  12,
     "skipped": 570,   ← arquivos sem alteração
     "total":   582,
     "message": "12 arquivo(s) enfileirado(s). 570 ignorado(s)."
   }

4. Worker processa os 12 alterados
   └─ Ver [[03-Worker-Processamento]]
```

## Detecção incremental

Na segunda ingestão do mesmo repo, o sistema compara o commit SHA de cada arquivo com o que está salvo no banco. Só os arquivos que mudaram desde a última ingestão são reprocessados.

Para forçar reprocessar tudo:
```json
{ "repo_url": "...", "force_all": true }
```

## O commit_hash no banco

Após o worker processar, o documento fica salvo com:
```
documents.commit_hash = "abc123..."   ← hash do git no momento da ingestão
documents.s3_key      = "documents/{repo_hash}/docs/Home.md"
```

Na próxima ingestão, esse hash é comparado com o atual do repositório para decidir se reprocessa.

## Ver também

- [[01-Upload-e-Ingestão]] — upload pelo browser (sem git)
- [[03-Worker-Processamento]] — o que o worker faz com cada arquivo
