"""
Git-based wiki repository cloner / updater.

Supports:
  - Initial clone (HTTPS or SSH).
  - Pull to HEAD on subsequent runs.
  - Returns the local path and current commit hash.

The clone directory is namespaced by a sanitised version of the repo URL
so multiple wikis can coexist under WIKI_CLONE_DIR.
"""

import hashlib
import logging
import os
import re
from pathlib import Path

import git

from app.config import settings

logger = logging.getLogger(__name__)


def get_local_repo_path(repo_url: str) -> Path:
    """
    Deterministic local directory for a given repo URL.
    Uses a short hash to avoid filesystem-unsafe characters in the path.
    """
    # Sanitise to a safe name + short hash to avoid collisions
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_url.rstrip("/").split("/")[-1])
    short_hash = hashlib.sha1(repo_url.encode()).hexdigest()[:8]
    return Path(settings.wiki_clone_dir) / f"{slug}_{short_hash}"


def clone_or_pull(repo_url: str) -> tuple[Path, str]:
    """
    Clone the repository if it doesn't exist locally, otherwise pull latest.

    Returns:
        (local_path, current_commit_hash)
    """
    local_path = get_local_repo_path(repo_url)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists() and (local_path / ".git").exists():
        logger.info("Repository already cloned at %s — pulling latest", local_path)
        repo = _pull(local_path, repo_url)
    else:
        logger.info("Cloning %s → %s", repo_url, local_path)
        repo = _clone(repo_url, local_path)

    commit_hash = repo.head.commit.hexsha
    logger.info("Repository at commit %s", commit_hash[:12])
    return local_path, commit_hash


def list_markdown_files(local_path: Path) -> list[Path]:
    """
    Recursively find all .md and .docx files in the repository/folder.
    Returns paths relative to local_path for consistent repo-relative keys.
    """
    files = sorted([
        *local_path.rglob("*.md"),
        *local_path.rglob("*.docx"),
        *local_path.rglob("*.txt"),
    ])
    relative = [f.relative_to(local_path) for f in files]
    logger.debug("Found %d ingestible files in %s", len(relative), local_path)
    return relative


def get_file_commit_hash(local_path: Path, file_relative: Path) -> str | None:
    """
    Return the commit hash of the last commit that modified a specific file.
    Returns None if the file has no commit history (e.g. untracked).
    """
    try:
        repo = git.Repo(local_path)
        commits = list(repo.iter_commits(paths=str(file_relative), max_count=1))
        return commits[0].hexsha if commits else None
    except Exception as exc:
        logger.warning("Could not get commit hash for %s: %s", file_relative, exc)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clone(repo_url: str, local_path: Path) -> git.Repo:
    try:
        return git.Repo.clone_from(repo_url, str(local_path), depth=0)
    except git.GitCommandError as exc:
        logger.error("Clone failed for %s: %s", repo_url, exc)
        raise


def _pull(local_path: Path, repo_url: str) -> git.Repo:
    try:
        repo = git.Repo(str(local_path))
        origin = repo.remotes.origin
        # Ensure remote URL matches (handles URL changes)
        if origin.url != repo_url:
            logger.info("Updating remote URL: %s → %s", origin.url, repo_url)
            origin.set_url(repo_url)
        origin.pull()
        return repo
    except git.GitCommandError as exc:
        logger.error("Pull failed for %s: %s", local_path, exc)
        raise
