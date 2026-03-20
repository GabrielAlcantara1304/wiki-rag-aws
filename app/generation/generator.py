"""
Answer generation via AWS Bedrock Converse API — Claude 3.5 Haiku.

The generator:
  1. Builds a context block from retrieved chunks + their neighbours.
  2. Instructs the model to answer ONLY from the provided context.
  3. Requires inline citations (document title + section).
  4. Returns the answer text plus a structured list of sources.

Authentication: IRSA (pod IAM role) — no API keys needed.
"""

import asyncio
import logging
from functools import partial

import boto3
from botocore.exceptions import ClientError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.retrieval.retriever import ChunkResult

logger = logging.getLogger(__name__)

_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

def _build_system_instructions() -> str:
    environment_section = (
        f"\n{settings.generation_context}\n"
        if settings.generation_context.strip()
        else ""
    )
    return (
        "Você é um assistente técnico especialista no ambiente cloud documentado abaixo. "
        "Responda sempre em português brasileiro (pt-BR), independentemente do idioma da documentação ou da pergunta."
        + environment_section
        + """

## Postura e tom

Você não é um buscador de documentos — você é um especialista que consultou a documentação e agora explica com suas próprias palavras.

- **Explique, não copie**: sintetize o que a documentação diz em linguagem natural.
- **Conecte conceitos**: relacione o que foi perguntado com o contexto mais amplo do ambiente.
- **Dê recomendações quando fizer sentido**: se a documentação descreve um padrão, oriente o usuário sobre como seguir esse padrão na prática.
- **Seja direto mas completo**: prefira parágrafos curtos e fluidos quando a resposta for conceitual. Use bullets apenas para passos sequenciais.
- **Admita lacunas com clareza**: se algo não está documentado mas você pode inferir, diga: "A documentação não cobre isso diretamente, mas dado o padrão descrito, o esperado seria...".

## Regras inegociáveis

1. Baseie-se sempre no [CONTEXT]. Não invente fatos, URLs ou dados técnicos específicos.
2. Se nenhuma fonte contiver informação relacionada, responda: "Esta informação não foi encontrada na documentação."
3. Separe o que é documentado do que é inferência. Use "a documentação indica..." vs "minha interpretação é...".
4. Ao final, inclua **Fontes:** listando os documentos e seções consultados:
   - [Título do Documento] > [Seção]
"""
    )


_SYSTEM_INSTRUCTIONS = _build_system_instructions()

_USER_TEMPLATE = """[QUESTION]
{question}

[CONTEXT]
{context}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_answer(
    question: str,
    chunks: list[ChunkResult],
    conversation_history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    if not chunks:
        return ("I don't have enough information in the provided documentation to answer this question.", [])

    context_block, sources = _build_context(chunks)
    user_message = _USER_TEMPLATE.format(question=question, context=context_block)

    answer = await _call_bedrock_converse(user_message, conversation_history or [])

    logger.info("Generated answer for '%s' using %d source chunks", question[:60], len(chunks))
    return answer, sources


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context(chunks: list[ChunkResult]) -> tuple[str, list[dict]]:
    seen_ids: set = set()
    context_parts: list[str] = []
    sources: list[dict] = []

    for chunk in chunks:
        if chunk.chunk_id in seen_ids:
            continue
        seen_ids.add(chunk.chunk_id)

        section_label = chunk.section_heading or "Introduction"
        header = f"--- {chunk.document_title} / {section_label} ---"

        all_texts = [chunk.chunk_text]
        for ctx in sorted(chunk.context_chunks, key=lambda c: c.chunk_index):
            if ctx.chunk_id not in seen_ids:
                all_texts.append(ctx.chunk_text)
                seen_ids.add(ctx.chunk_id)

        context_parts.append(header + "\n" + "\n\n".join(all_texts))
        sources.append({
            "document": chunk.document_title,
            "section": section_label,
            "snippet": chunk.chunk_text[:300] + ("..." if len(chunk.chunk_text) > 300 else ""),
            "similarity": chunk.similarity,
            "path": chunk.document_path,
        })

    return "\n\n".join(context_parts), sources


@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(4),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_bedrock_converse(user_message: str, conversation_history: list[dict]) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_invoke_converse, user_message, conversation_history),
    )


def _invoke_converse(user_message: str, conversation_history: list[dict]) -> str:
    messages = []
    for msg in conversation_history[-settings.conversation_history_turns:]:
        messages.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })
    messages.append({"role": "user", "content": [{"text": user_message}]})

    response = _client.converse(
        modelId=settings.bedrock_chat_model,
        system=[{"text": _SYSTEM_INSTRUCTIONS}],
        messages=messages,
        inferenceConfig={
            "temperature": settings.generation_temperature,
            "maxTokens": 4096,
        },
    )
    return response["output"]["message"]["content"][0]["text"]
