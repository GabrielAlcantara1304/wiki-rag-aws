"""List Landing Zone related documents."""
import asyncio
import sys
sys.path.insert(0, "C:/Users/gabriel/wiki-rag")

from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT d.path, d.title, COUNT(c.id) as chunk_count
            FROM documents d
            LEFT JOIN sections s ON s.document_id = d.id
            LEFT JOIN chunks c ON c.section_id = s.id
            WHERE d.title ILIKE '%landing%zone%'
               OR d.path ILIKE '%landing%zone%'
            GROUP BY d.path, d.title
            ORDER BY d.path
        """))
        rows = result.fetchall()

    lines = [f"Landing Zone documents: {len(rows)}\n"]
    for row in rows:
        lines.append(f"  path={row.path}")
        lines.append(f"    title={row.title} | chunks={row.chunk_count}")

    with open("C:/Users/gabriel/wiki-rag/lz_docs.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Done — see lz_docs.txt")

asyncio.run(main())
