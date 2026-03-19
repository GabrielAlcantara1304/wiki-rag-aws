"""Check content of Landing Zone Introduction chunk."""
import asyncio
import sys
sys.path.insert(0, "C:/Users/gabriel/wiki-rag")

from app.database import AsyncSessionLocal
from app.retrieval.retriever import search

async def main():
    async with AsyncSessionLocal() as db:
        chunks = await search(db, "what is AWS Landing Zone?")

    with open("C:/Users/gabriel/wiki-rag/intro_debug.txt", "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            f.write(f"\n{'='*60}\n")
            f.write(f"Chunk {i+1}: [{c.similarity:.3f}] {c.document_title} > {c.section_heading}\n")
            f.write(f"Path: {c.document_path}\n")
            f.write(f"Text:\n{c.chunk_text}\n")
            if c.context_chunks:
                f.write(f"\nContext chunks ({len(c.context_chunks)}):\n")
                for ctx in c.context_chunks:
                    f.write(f"  [{ctx.chunk_index}] {ctx.chunk_text[:200]}\n")

    print("Done — see intro_debug.txt")

asyncio.run(main())
