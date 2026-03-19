"""Check for duplicate chunks in the DB."""
import asyncio
import sys
sys.path.insert(0, "C:/Users/gabriel/wiki-rag")

from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        # Count total chunks
        result = await db.execute(text("SELECT COUNT(*) FROM chunks"))
        total = result.scalar()

        # Find duplicate chunk texts
        result = await db.execute(text("""
            SELECT chunk_text, COUNT(*) as cnt
            FROM chunks
            GROUP BY chunk_text
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 10
        """))
        dupes = result.fetchall()

        # Check AWS Multiworkload Platform specifically
        result = await db.execute(text("""
            SELECT d.title, s.heading, c.chunk_index, c.id, LEFT(c.chunk_text, 100) as snippet
            FROM chunks c
            JOIN sections s ON c.section_id = s.id
            JOIN documents d ON s.document_id = d.id
            WHERE d.title = 'AWS Multiworkload Platform'
              AND s.heading LIKE '%Prerequisites%'
            ORDER BY c.id
        """))
        prereq_chunks = result.fetchall()

    lines = [f"Total chunks in DB: {total}\n"]
    lines.append(f"Duplicate chunk texts (top 10): {len(dupes)}")
    for text_val, cnt in dupes:
        lines.append(f"  x{cnt}: {repr(text_val[:80])}")

    lines.append(f"\nAWS Multiworkload Platform / Prerequisites chunks: {len(prereq_chunks)}")
    for row in prereq_chunks:
        lines.append(f"  doc={row.title} | section={row.heading} | idx={row.chunk_index} | id={row.id}")
        lines.append(f"    {repr(row.snippet)}")

    with open("C:/Users/gabriel/wiki-rag/dupes_debug.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Done — see dupes_debug.txt")

asyncio.run(main())
