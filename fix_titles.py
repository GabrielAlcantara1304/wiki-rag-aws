"""Fix documents with generic titles (e.g. 'Table of contents') using the filename."""
import asyncio
import sys
sys.path.insert(0, "C:/Users/gabriel/wiki-rag")

from pathlib import Path
from sqlalchemy import text
from app.database import AsyncSessionLocal

GENERIC_TITLES = {
    "table of contents", "contents", "index", "readme", "home", "overview",
    "introduction", "welcome", "wiki", "documentation",
}

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id, title, path FROM documents"))
        rows = result.fetchall()

        updated = 0
        for row in rows:
            if row.title.lower().strip() in GENERIC_TITLES:
                new_title = Path(row.path).stem.replace("-", " ").replace("_", " ")
                await db.execute(
                    text("UPDATE documents SET title = :title WHERE id = :id"),
                    {"title": new_title, "id": row.id}
                )
                updated += 1

        await db.commit()
        print(f"Updated {updated} documents out of {len(rows)} total.")

asyncio.run(main())
