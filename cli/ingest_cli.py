"""
CLI for triggering wiki ingestion without the HTTP API.

Usage:
    python -m cli.ingest_cli --repo-url https://github.com/org/wiki.git
    python -m cli.ingest_cli --repo-url https://github.com/org/wiki.git --force-all
    python -m cli.ingest_cli --repo-url https://github.com/org/wiki.git --dry-run

The CLI shares the same ingestion pipeline as the API, so the output
is identical whether you trigger via HTTP or the command line.
"""

import asyncio
import sys

import click

from app.config import settings
from app.database import AsyncSessionLocal
from app.ingestion.cloner import clone_or_pull, list_markdown_files
from app.ingestion.pipeline import run_ingestion
from app.utils.logging import configure_logging

configure_logging()

import logging
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """Wiki RAG — command line tools."""


@cli.command("ingest")
@click.option(
    "--repo-url",
    default=None,
    help="Git URL of the wiki to ingest. Defaults to WIKI_REPO_URL env var.",
)
@click.option(
    "--local-path",
    default=None,
    help="Caminho local para uma wiki já clonada (alternativa ao --repo-url).",
)
@click.option(
    "--force-all",
    is_flag=True,
    default=False,
    help="Re-ingest ALL files, ignoring change detection.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Clone/pull and list changed files but do not write to the database.",
)
def ingest_command(repo_url: str | None, local_path: str | None, force_all: bool, dry_run: bool) -> None:
    """
    Ingest (or re-ingest) a GitHub Wiki repository.

    Examples:\n
        python -m cli.ingest_cli ingest --repo-url https://github.com/org/wiki.git\n
        python -m cli.ingest_cli ingest --force-all\n
        python -m cli.ingest_cli ingest --dry-run
    """
    url = repo_url or settings.wiki_repo_url

    if not url and not local_path:
        click.echo("ERRO: informe --repo-url ou --local-path.", err=True)
        sys.exit(1)

    if dry_run:
        _dry_run(local_path or url)
        return

    asyncio.run(_run_ingest(url or "", force_all, local_path or ""))


@cli.command("list-files")
@click.option("--repo-url", default=None, help="Git URL of the wiki.")
def list_files_command(repo_url: str | None) -> None:
    """Clone/pull and list all Markdown files without ingesting."""
    url = repo_url or settings.wiki_repo_url
    if not url:
        click.echo("ERROR: No repo URL provided.", err=True)
        sys.exit(1)

    local_path, commit = clone_or_pull(url)
    files = list_markdown_files(local_path)
    click.echo(f"\nRepo: {url}")
    click.echo(f"Commit: {commit[:12]}")
    click.echo(f"Markdown files ({len(files)}):")
    for f in files:
        click.echo(f"  {f}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dry_run(repo_url: str) -> None:
    """Show what would be ingested without touching the DB."""
    click.echo(f"DRY RUN for: {repo_url}")
    local_path, commit = clone_or_pull(repo_url)
    files = list_markdown_files(local_path)
    click.echo(f"Commit: {commit[:12]}")
    click.echo(f"Files that would be evaluated ({len(files)}):")
    for f in files:
        click.echo(f"  {f}")
    click.echo("\n[dry-run] No changes written to the database.")


async def _run_ingest(repo_url: str, force_all: bool, local_path: str = "") -> None:
    async with AsyncSessionLocal() as session:
        try:
            label = local_path or repo_url
            click.echo(f"Iniciando ingestão: {label}")
            stats = await run_ingestion(
                db=session,
                repo_url=repo_url,
                force_all=force_all,
                local_path_override=local_path,
            )
            await session.commit()
            click.echo(
                f"\n✓ Done — processed={stats['processed']}  "
                f"skipped={stats['skipped']}  failed={stats['failed']}"
            )
            if stats["failed"] > 0:
                sys.exit(1)
        except Exception as exc:
            await session.rollback()
            click.echo(f"\n✗ Ingestion failed: {exc}", err=True)
            logger.error("CLI ingestion error", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    cli()
