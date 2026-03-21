---
tags: [wiki-rag, arquitetura, aws]
---

# Wiki RAG — Visão Geral

Sistema de perguntas e respostas sobre documentação interna, rodando na AWS com EKS, Bedrock, RDS (pgvector), S3 e SQS.

## Componentes principais

| Componente | Tecnologia | Função |
|---|---|---|
| API pod | FastAPI (Python) | Recebe uploads, responde perguntas |
| Worker pod | Python | Consome SQS, processa e indexa arquivos |
| Banco de dados | RDS PostgreSQL + pgvector | Guarda embeddings e metadados |
| Armazenamento | S3 | Guarda documentos completos |
| Fila | SQS | Desacopla upload de processamento |
| IA — Embeddings | Bedrock Titan Text V2 (1024 dims) | Vetoriza chunks de texto |
| IA — Chat | Bedrock Amazon Nova Lite | Gera respostas |
| Container registry | ECR | Imagens Docker |
| Orquestração | EKS (Kubernetes 1.30) | Roda os pods |
| CI/CD | GitHub Actions | Build, push, deploy |

## Fluxos documentados

- [[01-Upload-e-Ingestão]] — Como arquivos e pastas chegam ao sistema
- [[02-Ingestão-Git]] — Como repositórios git são indexados
- [[03-Worker-Processamento]] — O que o worker faz com cada arquivo
- [[04-QA-Retrieval]] — Como uma pergunta vira uma resposta
- [[05-CI-CD]] — Pipeline de deploy automatizado
- [[06-Armazenamento]] — O que fica no S3 vs RDS
- [[07-Infraestrutura-Terraform]] — Módulos Terraform e o que cada um cria
- [[08-Kubernetes]] — Manifests K8s, HPA, IRSA
- [[09-Troubleshooting]] — Erros encontrados e como foram resolvidos
- [[10-Monitoramento]] — Logs, métricas, custo e como parar tudo
- [[11-Evidências]] — Checklist de prints para validar o sistema

## Diagrama macro

```
Browser / API Client
       │
       ▼
  ┌─────────┐   uploads/   ┌─────┐   mensagens   ┌────────┐
  │ API pod │ ────────────▶│ S3  │               │  SQS   │
  │  :8000  │ ────────────────────────────────▶  │  fila  │
  └─────────┘              └─────┘               └────────┘
       │                      │                       │
       │ (perguntas)           │                       ▼
       ▼                       │                ┌──────────────┐
  ┌─────────┐                  │                │  Worker pod  │
  │   RDS   │◀─────────────────┘ (documents/)   │              │
  │pgvector │◀────────────────────────────────  │ parse+embed  │
  └─────────┘   embeddings + s3_key             └──────────────┘
                                                       │
                                                       ▼
                                               ┌──────────────┐
                                               │   Bedrock    │
                                               │ Titan Embed  │
                                               └──────────────┘
```
