"""
Markdown parser: converts a raw .md file into structured data.

Extracts:
  - Document title (first H1 or filename stem)
  - Sections (flat list bounded by headings H1–H3)
  - Assets (images with alt-text and surrounding context)
  - Plain-text rendering (for display and full-text search)

Design decision: sections are FLAT, not nested.  Each section captures
the heading text + all content until the NEXT heading.  This keeps the
schema simple and avoids deep nesting that complicates retrieval.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import markdown
from bs4 import BeautifulSoup

# Regex patterns
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)", re.MULTILINE)
_HEADING_LEVELS = {1, 2, 3}  # We only create sections at H1-H3


@dataclass
class ParsedSection:
    heading: Optional[str]
    level: int          # 0 = root content before first heading
    content: str        # Everything in this section, excluding the heading line
    order_index: int    # Position within the document


@dataclass
class ParsedAsset:
    file_path: str
    alt_text: str
    context: str        # Paragraph surrounding the image reference


@dataclass
class ParsedDocument:
    title: str
    raw_markdown: str
    rendered_text: str
    sections: list[ParsedSection] = field(default_factory=list)
    assets: list[ParsedAsset] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_markdown_file(file_path: str, content: str) -> ParsedDocument:
    """
    Full parse of a single .md file.

    Args:
        file_path: Relative path within the repo (used to derive fallback title).
        content:   Raw markdown string.

    Returns:
        ParsedDocument with all extracted data.
    """
    title = _extract_title(content, file_path)
    rendered_text = _render_to_plain_text(content)
    sections = _extract_sections(content)
    assets = _extract_assets(content)

    return ParsedDocument(
        title=title,
        raw_markdown=content,
        rendered_text=rendered_text,
        sections=sections,
        assets=assets,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GENERIC_TITLES = {
    "table of contents", "contents", "index", "readme", "home", "overview",
    "introduction", "welcome", "wiki", "documentation",
}


def _extract_title(content: str, file_path: str) -> str:
    """
    Title preference order:
    1. First H1 heading, unless it's a generic title (e.g. "Table of contents").
    2. Filename stem with hyphens/underscores replaced by spaces.
    """
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in _GENERIC_TITLES:
            return candidate
    return Path(file_path).stem.replace("-", " ").replace("_", " ")


def _render_to_plain_text(content: str) -> str:
    """
    Convert markdown → HTML → plain text.
    Preserves sentence structure and strips all markup.
    """
    html = markdown.markdown(content, extensions=["tables", "fenced_code"])
    soup = BeautifulSoup(html, "html.parser")
    # Replace block elements with newlines so text stays readable
    for tag in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_after("\n")
    text = soup.get_text(separator="\n")
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_sections(content: str) -> list[ParsedSection]:
    """
    Split the document into flat sections at every H1–H3 boundary.

    Algorithm:
    1. Find all heading positions.
    2. Slice the text between consecutive headings.
    3. The content before the first heading becomes a level-0 root section.
    """
    sections: list[ParsedSection] = []
    order = 0

    # Collect all H1-H3 heading matches
    headings = [
        (m.start(), len(m.group(1)), m.group(2).strip())   # (pos, level, text)
        for m in _HEADING_RE.finditer(content)
        if len(m.group(1)) in _HEADING_LEVELS
    ]

    if not headings:
        # No headings at all — the entire file is one root section
        text = content.strip()
        if text:
            sections.append(ParsedSection(
                heading=None, level=0, content=text, order_index=order
            ))
        return sections

    # Content before the first heading (preamble / intro)
    preamble = content[: headings[0][0]].strip()
    if preamble:
        sections.append(ParsedSection(
            heading=None, level=0, content=preamble, order_index=order
        ))
        order += 1

    # Slice between each heading and the next
    for idx, (pos, level, heading_text) in enumerate(headings):
        # Find the start of this section's body (after the heading line)
        line_end = content.index("\n", pos) if "\n" in content[pos:] else len(content)
        body_start = line_end + 1

        # The body ends at the start of the next heading (or EOF)
        if idx + 1 < len(headings):
            body_end = headings[idx + 1][0]
        else:
            body_end = len(content)

        body = content[body_start:body_end].strip()

        # Always create a section even if body is empty — the heading itself
        # carries semantic value and may be useful for navigation.
        sections.append(ParsedSection(
            heading=heading_text,
            level=level,
            content=body,
            order_index=order,
        ))
        order += 1

    return sections


def _extract_assets(content: str) -> list[ParsedAsset]:
    """
    Find all Markdown image references and capture surrounding context
    (the paragraph that contains the image).
    """
    assets: list[ParsedAsset] = []
    paragraphs = content.split("\n\n")

    for para in paragraphs:
        for match in _IMAGE_RE.finditer(para):
            alt_text = match.group(1).strip()
            file_path = match.group(2).strip()
            # Strip the image tag itself for a cleaner context string
            context = _IMAGE_RE.sub("", para).strip()
            assets.append(ParsedAsset(
                file_path=file_path,
                alt_text=alt_text,
                context=context[:500],  # cap context length
            ))

    return assets
