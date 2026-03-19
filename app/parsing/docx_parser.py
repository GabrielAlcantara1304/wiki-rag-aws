"""
Word document parser: converts a .docx file into the same ParsedDocument
structure produced by markdown_parser.py.

Strategy:
  - Paragraphs with Heading styles (Heading 1–3) become section boundaries.
  - All other paragraphs accumulate as section content.
  - Tables are converted to plain text (row-by-row, cells separated by " | ").
  - Images are recorded as Asset entries (alt text only — no binary extraction).
  - Title is taken from the first Heading 1, or the filename stem.
"""

import logging
from pathlib import Path
from typing import Optional

from docx import Document as DocxDocument
from docx.oxml.ns import qn

from app.parsing.markdown_parser import ParsedAsset, ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)

_HEADING_STYLES = {"heading 1", "heading 2", "heading 3"}
_HEADING_LEVEL  = {"heading 1": 1, "heading 2": 2, "heading 3": 3}


def parse_docx_file(file_path: str, file_bytes: bytes) -> ParsedDocument:
    """
    Parse a .docx file into a ParsedDocument.

    Args:
        file_path: Relative path within the source folder (used for title fallback).
        file_bytes: Raw bytes of the .docx file.

    Returns:
        ParsedDocument with sections, assets, and plain text.
    """
    import io
    doc = DocxDocument(io.BytesIO(file_bytes))

    title: Optional[str] = None
    sections: list[ParsedSection] = []
    assets: list[ParsedAsset] = []

    current_heading: Optional[str] = None
    current_level: int = 0
    current_lines: list[str] = []
    order_index: int = 0

    def flush_section():
        nonlocal order_index
        content = "\n\n".join(l for l in current_lines if l.strip())
        if content:
            sections.append(ParsedSection(
                heading=current_heading,
                level=current_level,
                content=content,
                order_index=order_index,
            ))
            order_index += 1

    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag

        if tag == "p":
            para = _block_to_paragraph(doc, block)
            if para is None:
                continue

            style_name = (para.style.name if para.style else "").lower()

            if style_name in _HEADING_STYLES:
                flush_section()
                current_heading = para.text.strip()
                current_level   = _HEADING_LEVEL[style_name]
                current_lines   = []

                if title is None and current_level == 1:
                    title = current_heading
            else:
                text = para.text.strip()
                if text:
                    current_lines.append(text)

                # Collect inline images
                for rel in _get_image_rels(para):
                    assets.append(ParsedAsset(
                        file_path=rel,
                        alt_text="",
                        context=para.text.strip()[:200],
                    ))

        elif tag == "tbl":
            table_text = _table_to_text(doc, block)
            if table_text:
                current_lines.append(table_text)

    flush_section()

    if not title:
        title = Path(file_path).stem.replace("-", " ").replace("_", " ")

    rendered_text = "\n\n".join(
        ((s.heading + "\n") if s.heading else "") + s.content
        for s in sections
    )

    return ParsedDocument(
        title=title,
        raw_markdown=rendered_text,   # store plain text in raw_markdown slot
        rendered_text=rendered_text,
        sections=sections,
        assets=assets,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_to_paragraph(doc, block):
    """Wrap a raw lxml paragraph element as a python-docx Paragraph."""
    from docx.text.paragraph import Paragraph
    try:
        return Paragraph(block, doc)
    except Exception:
        return None


def _table_to_text(doc, block) -> str:
    """Convert a raw lxml table element to a plain-text representation."""
    from docx.table import Table
    try:
        table = Table(block, doc)
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
    except Exception:
        return ""


def _get_image_rels(para) -> list[str]:
    """Extract relationship IDs for inline images in a paragraph."""
    rels = []
    for drawing in para._element.findall(".//" + qn("a:blip")):
        embed = drawing.get(qn("r:embed"))
        if embed and embed in para.part.rels:
            target = para.part.rels[embed].target_ref
            rels.append(target)
    return rels
