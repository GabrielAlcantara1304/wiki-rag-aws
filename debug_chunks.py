"""Debug script — writes chunk content to file to avoid cp1252 terminal issues."""
import asyncio
import sys
sys.path.insert(0, "C:/Users/gabriel/wiki-rag")

from app.database import AsyncSessionLocal
from app.retrieval.retriever import search

async def main():
    async with AsyncSessionLocal() as db:
        chunks = await search(db, "what is AWS Landing Zone?")

    output = []
    output.append(f"Total chunks: {len(chunks)}\n")
    for i, c in enumerate(chunks):
        output.append(f"\n--- Chunk {i+1} ---")
        output.append(f"Doc: {c.document_title}")
        output.append(f"Section: {c.section_heading}")
        output.append(f"Similarity: {c.similarity:.4f}")
        output.append(f"Text (first 600 chars):\n{c.chunk_text[:600]}")
        output.append("")

    with open("C:/Users/gabriel/wiki-rag/chunks_debug.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print("Done — see chunks_debug.txt")

asyncio.run(main())
