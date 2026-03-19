"""
Answer generation via Amazon Bedrock — Claude 3 Haiku.

Uses the Bedrock Converse API (multi-turn, model-agnostic interface).
IRSA provides AWS credentials automatically on EKS — no key management.

Pricing: ~$0.00025/1K input + $0.00125/1K output tokens (2024).
"""

import asyncio
import json
import logging

import boto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.config import settings
from app.retrieval.retriever import ChunkResult

logger = logging.getLogger(__name__)

_bedrock_client = None


def _get_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
        )
    return _bedrock_client

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_ENVIRONMENT_CONTEXT = """
[CONTEXTO DO AMBIENTE]
O ambiente da Neoenergia, operado em parceria com a Ayesa, é uma arquitetura multi-cloud com predominância em AWS, estruturada com foco em padronização, governança e automação em larga escala.

Na AWS, a organização segue um modelo baseado em plataformas e workloads. As plataformas são camadas estruturais criadas para suportar diferentes aplicações e serviços, como multiworkload, open platform (OP), data platform e IA. Dentro dessas plataformas, existem os workloads, que representam as aplicações ou sistemas de negócio implantados.

Em plataformas como a multiworkload, existe o conceito de multiapps, onde múltiplas aplicações compartilham a mesma base de infraestrutura padronizada. Esse mesmo conceito também é aplicado em outras plataformas, como open platform e data platform, permitindo maior eficiência, reaproveitamento e padronização.

As contas AWS são organizadas de forma estratégica, sendo segmentadas por plataforma (multiworkload, open, data, IA), ambiente (production e non-production) e finalidade (corporate, networks, retail, etc.). Com nomenclaturas padronizadas como: mwlcrnpd (multiworkload corporate non-production), opcrdefs-pro (open platform corporate defs production).

Toda a infraestrutura é provisionada via Terraform, estruturado em três camadas: Modules (componentes reutilizáveis como EKS, VPC, EC2, RDS com governança embutida), Template (define como os módulos são combinados por tipo de plataforma) e Live (representa os ambientes reais, onde são aplicadas as variáveis específicas). O deploy de infraestrutura é feito via GitHub Actions, garantindo automação, versionamento e rastreabilidade.

O deploy das aplicações segue um fluxo separado, sendo realizado via Jenkins, com as aplicações containerizadas e implantadas em EKS (Kubernetes gerenciado).

Do ponto de vista operacional, inicialmente o modelo era mais restritivo: o time de operações atuava apenas na camada live, ajustando variáveis via custom.tfvars; o time de engenharia era responsável por alterações estruturais nos modules e templates.

Com a evolução para a multiworkload versão 3.0, o modelo se tornou mais flexível e orientado a dados. Os templates passaram a suportar estruturas dinâmicas (maps e objects), permitindo que o próprio custom.tfvars defina recursos a serem criados via for_each. Assim, o time de operações ganhou autonomia para criar recursos diretamente via variáveis, desde que suportados pelos templates. Essa abordagem traz maior velocidade e autonomia, mantendo governança através de padrões bem definidos nos módulos e templates.
"""

_SYSTEM_INSTRUCTIONS = """Você é um assistente técnico especialista no ambiente cloud da Neoenergia/Ayesa. \
Responda sempre em português brasileiro (pt-BR), independentemente do idioma da documentação ou da pergunta.

Use o [CONTEXTO DO AMBIENTE] abaixo como conhecimento de fundo permanente sobre o ambiente. \
Esse contexto é sempre verdadeiro e deve informar todas as respostas, mesmo quando não estiver explicitamente no bloco [CONTEXT].

{environment}

## Postura e tom

Você não é um buscador de documentos — você é um especialista que consultou a documentação e agora explica com suas próprias palavras.

- **Explique, não copie**: sintetize o que a documentação diz em linguagem natural. Use frases como "na prática isso significa...", "o que isso quer dizer é...", "nesse modelo, o ideal é...".
- **Conecte conceitos**: relacione o que foi perguntado com o contexto mais amplo do ambiente. Ex: se alguém pergunta sobre deploy, conecte com o fluxo Jenkins → EKS já documentado.
- **Dê recomendações quando fizer sentido**: se a documentação descreve um padrão, oriente o usuário sobre como seguir esse padrão na prática.
- **Seja direto mas completo**: evite listas de bullet para tudo — prefira parágrafos curtos e fluidos quando a resposta for conceitual. Use bullets apenas para passos sequenciais ou listas de itens.
- **Admita lacunas com clareza**: se algo não está documentado mas você pode inferir pelo padrão do ambiente, diga explicitamente: "A documentação não cobre isso diretamente, mas dado o padrão descrito, o esperado seria...".

## Regras inegociáveis

1. Baseie-se sempre no [CONTEXT] e no [CONTEXTO DO AMBIENTE]. Não invente fatos, URLs ou dados técnicos específicos.
2. Se nenhuma das fontes contiver informação semanticamente relacionada à pergunta, responda: "Esta informação não foi encontrada na documentação."
3. Separe claramente o que é documentado do que é inferência sua. Use marcadores como "a documentação indica..." vs "minha interpretação é...".
4. Ao final, inclua uma seção **Fontes:** listando os documentos e seções consultados:
   - [Título do Documento] > [Seção]
""".format(environment=_ENVIRONMENT_CONTEXT)

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
    """
    Generate a grounded answer for the given question using the retrieved chunks.

    Args:
        question: The user's original question.
        chunks:   Top-k chunks from the retriever (including context expansions).

    Returns:
        Tuple of (answer_text, sources_list) where sources_list contains
        dicts with keys: document, section, snippet.
    """
    if not chunks:
        return (
            "I don't have enough information in the provided documentation to answer this question.",
            [],
        )

    context_block, sources = _build_context(chunks)
    user_message = _USER_TEMPLATE.format(
        question=question,
        context=context_block,
    )

    answer = await _call_responses_api(user_message, conversation_history or [])

    logger.info(
        "Generated answer for '%s' using %d source chunks",
        question[:60], len(chunks),
    )
    return answer, sources


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context(chunks: list[ChunkResult]) -> tuple[str, list[dict]]:
    """
    Assemble the context block that is injected into the prompt.

    Each entry is rendered as:

        --- [Document Title] / [Section] ---
        <chunk text>
        [+ neighbouring chunks if any]

    Also builds the sources list for the API response.
    """
    seen_ids: set = set()
    context_parts: list[str] = []
    sources: list[dict] = []

    for chunk in chunks:
        if chunk.chunk_id in seen_ids:
            continue
        seen_ids.add(chunk.chunk_id)

        section_label = chunk.section_heading or "Introduction"
        header = f"--- {chunk.document_title} / {section_label} ---"

        # Include context chunks (neighbours) inline, ordered by chunk_index
        all_texts = [chunk.chunk_text]
        for ctx in sorted(chunk.context_chunks, key=lambda c: c.chunk_index):
            if ctx.chunk_id not in seen_ids:
                all_texts.append(ctx.chunk_text)
                seen_ids.add(ctx.chunk_id)

        block = header + "\n" + "\n\n".join(all_texts)
        context_parts.append(block)

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
async def _call_responses_api(user_message: str, conversation_history: list[dict]) -> str:
    """
    Call Bedrock Converse API with retry logic.
    Converts OpenAI-style history (content: str) to Bedrock format (content: list[block]).
    Returns the plain text answer.
    """
    # Convert OpenAI-style history to Bedrock Converse format
    bedrock_messages = []
    for msg in conversation_history[-3:]:
        bedrock_messages.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })
    bedrock_messages.append({
        "role": "user",
        "content": [{"text": user_message}],
    })

    response = await asyncio.to_thread(
        _get_client().converse,
        modelId=settings.bedrock_llm_model,
        system=[{"text": _SYSTEM_INSTRUCTIONS}],
        messages=bedrock_messages,
        inferenceConfig={
            "maxTokens": 2048,
            "temperature": 0.1,
        },
    )
    return response["output"]["message"]["content"][0]["text"]
