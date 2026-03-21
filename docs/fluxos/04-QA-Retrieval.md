---
tags: [wiki-rag, qa, retrieval, bedrock, pgvector, reranker]
---

# Q&A — Fluxo de Pergunta e Resposta

Endpoint: `POST /ask`
UI: `/ui` — campo de pergunta

## Fluxo completo

```
1. Usuário digita: "Como configurar o PIM?"

2. POST /ask
   {
     "question": "Como configurar o PIM?",
     "history":  [ ... últimas 3 trocas ... ]
   }

3. API pod — pipeline de recuperação

   3.1 Embed da pergunta
       Bedrock Titan Text V2
       "Como configurar o PIM?" → vetor[1024]

   3.2 Busca vetorial no RDS (pgvector)
       SELECT chunks.*, cosine_distance(embedding, $query_vec)
       FROM chunks
       JOIN sections ON ...
       JOIN documents ON ...
       ORDER BY embedding <=> $query_vec
       LIMIT 50   ← top_k * 5 candidatos

   3.3 Filtragem
       └─ Remove chunks com < 20 tokens (só heading, sem conteúdo)
       └─ Deduplica por chunk_text

   3.4 Cross-encoder Reranking
       Modelo: cross-encoder/ms-marco-MiniLM-L-6-v2 (local, CPU)
       Para cada chunk candidato:
         score = reranker.predict(("Como configurar o PIM?", chunk_text))
       Ordena por score → top 10

   3.5 Expansão de contexto
       Para cada chunk selecionado:
         └─ Busca chunk anterior (previous_chunk_id) e posterior (next_chunk_id)
         └─ Adiciona ao contexto se não estiver já incluído
       (A lista encadeada no banco torna isso eficiente — sem JOIN extra)

   3.6 Monta contexto para o LLM
       [Chunk 1]: <documento: Home.md, seção: Configuração>
       texto do chunk 1...

       [Chunk 2]: <documento: PIM-Setup.md, seção: Pré-requisitos>
       texto do chunk 2...
       ...

4. Geração da resposta
   Bedrock Amazon Nova Lite (Converse API)

   System prompt:
     "Você é um assistente especializado. Responda apenas com base
      nos trechos fornecidos. Se não souber, diga que não sabe."

   Mensagens:
     [histórico das últimas 3 trocas]
     [contexto recuperado]
     [pergunta atual]

   Resposta: texto gerado pelo LLM

5. Detecção de lacuna de conhecimento
   Se max_similarity < 0.45:
     INSERT INTO knowledge_gaps (question, max_similarity, ...)
     (aparece no painel "Lacunas de conhecimento" da UI)

6. Resposta ao cliente
   {
     "answer":  "Para configurar o PIM, acesse...",
     "sources": [
       { "title": "PIM-Setup.md", "section": "Configuração", "similarity": 0.87 },
       ...
     ],
     "images":  []
   }
```

## Parâmetros de recuperação (ConfigMap)

| Parâmetro | Valor padrão | Significado |
|---|---|---|
| `RETRIEVAL_TOP_K` | 10 | Chunks finais enviados ao LLM |
| `RETRIEVAL_SIMILARITY_THRESHOLD` | 0.5 | Similaridade mínima para incluir chunk |
| `CONTEXT_WINDOW_CHUNKS` | 2 | Vizinhos expandidos por chunk selecionado |
| `GENERATION_TEMPERATURE` | 0.1 | Quão "criativo" o LLM é (baixo = mais factual) |
| `CONVERSATION_HISTORY_TURNS` | 3 | Quantas trocas anteriores incluir |

## Modelos utilizados

| Modelo | Onde roda | Para quê |
|---|---|---|
| `amazon.titan-embed-text-v2:0` | Bedrock (AWS) | Embed da pergunta + chunks na ingestão |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Local no pod (CPU) | Reranking dos candidatos |
| `amazon.nova-lite-v1:0` | Bedrock (AWS) | Geração da resposta final |

## Por que dois modelos de ranking?

1. **Busca vetorial (pgvector)** — rápida, mas usa embeddings individuais (sem contexto cruzado entre query e chunk)
2. **Cross-encoder (reranker)** — mais preciso, analisa query + chunk juntos, mas lento demais para rodar nos 1000+ chunks do banco. Roda só nos 50 candidatos pré-filtrados.

## Lacunas de conhecimento

Quando nenhum chunk tem similaridade > `gap_similarity_threshold` (0.45), a pergunta é registrada como lacuna. Visível em `/ui/ingest.html` → "Lacunas de conhecimento". Serve para identificar o que falta na base de conhecimento.

## Ver também

- [[03-Worker-Processamento]] — como os embeddings foram gerados
- [[06-Armazenamento]] — estrutura do banco de dados
