"""Thin GitHub REST API client for commit listing and detail retrieval.

Only the endpoints we actually need are wrapped. The client handles
authentication, pagination, and rate-limit waits, but does not retry
arbitrary failures: errors surface as :class:`GitHubError` so the caller can
decide.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Iterator

import requests

from . import config
from .diff_parser import parse_file_patch
from .logger import get_logger
from .models import Commit, FileDiff

log = get_logger()

API_ROOT = "https://api.github.com"
PER_PAGE = 100
RATE_LIMIT_PAUSE_THRESHOLD = 10


class GitHubError(RuntimeError):
    """Raised when the GitHub API returns an unrecoverable error."""


class GitHubClient:
    """Authenticated client for the few endpoints this project needs."""

    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        if not token:
            raise ValueError("GitHub token is required (set GITHUB_TOKEN)")
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "tcc-v2-missnullcheck-detector",
            }
        )

    def list_commits(self, repo: str, limit: int | None = None) -> Iterator[Commit]:
        """Yield commits for ``owner/name``, newest first.

        Iterates all pages by default. Each yielded commit includes file-level
        patches. ``limit`` is optional and primarily useful for debugging.
        """
        url = f"{API_ROOT}/repos/{repo}/commits"
        params = {"per_page": PER_PAGE}
        yielded = 0
        page = 0
        log.info(f"Lendo repositório {repo}...")
        while url:
            page += 1
            response = self._get(url, params=params)
            params = None  # parameters carried inside ``url`` from the next-page link.
            batch = response.json()
            log.info(f"Página {page} obtida ({len(batch)} commits)")
            for raw in batch:
                yield self.get_commit(repo, raw["sha"])
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            url = _next_link(response.headers.get("Link"))

    def get_commit(self, repo: str, sha: str) -> Commit:
        """Fetch a single commit by SHA, including its per-file patches."""
        url = f"{API_ROOT}/repos/{repo}/commits/{sha}"
        data = self._get(url).json()
        return _to_commit(repo, data)

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        self._wait_for_rate_limit()
        response = self._session.get(url, params=params, timeout=30)
        self._last_rate_headers = {
            "X-RateLimit-Remaining": response.headers.get("X-RateLimit-Remaining"),
            "X-RateLimit-Reset": response.headers.get("X-RateLimit-Reset"),
        }
        if response.status_code >= 400:
            raise GitHubError(f"GET {url} -> {response.status_code}: {response.text[:300]}")
        return response

    def _wait_for_rate_limit(self) -> None:
        last = getattr(self, "_last_rate_headers", None)
        if not last or not last.get("X-RateLimit-Remaining"):
            return
        remaining = int(last["X-RateLimit-Remaining"])
        if remaining > RATE_LIMIT_PAUSE_THRESHOLD:
            return
        reset = int(last.get("X-RateLimit-Reset") or "0")
        delay = max(0, reset - int(time.time())) + 1
        if delay > 0:
            time.sleep(delay)


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if section.endswith('rel="next"'):
            url = section[: section.index(";")].strip()
            return url[1:-1] if url.startswith("<") and url.endswith(">") else url
    return None


def _to_commit(repo: str, data: dict) -> Commit:
    sha = data["sha"]
    commit_meta = data["commit"]
    message: str = commit_meta["message"]
    author = (commit_meta.get("author") or {}).get("name") or "unknown"
    date_str = (commit_meta.get("author") or {}).get("date") or "1970-01-01T00:00:00Z"
    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    # Only materialise files whose extension is in ANALYZED_EXTENSIONS. The
    # detector targets Java; non-Java files (Python, YAML, Markdown, etc.) are
    # silently discarded here so they never reach downstream feature
    # extraction, scoring, or the diff-size penalty.
    raw_files = [f for f in (data.get("files") or []) if f.get("patch")]
    relevant = [f for f in raw_files if _is_analyzed(f.get("filename", ""))]
    files = tuple(_to_file_diff(f) for f in relevant)
    skipped = len(raw_files) - len(relevant)
    if skipped:
        log.debug(
            f"commit {sha[:10]}: {skipped} arquivo(s) ignorado(s) "
            f"(extensão não analisada)"
        )
    url = data.get("html_url") or f"https://github.com/{repo}/commit/{sha}"
    return Commit(sha=sha, message=message, author=author, date=date, files=files, url=url)


def _is_analyzed(filename: str) -> bool:
    return any(filename.endswith(ext) for ext in config.ANALYZED_EXTENSIONS)


def _to_file_diff(raw: dict) -> FileDiff:
    return parse_file_patch(raw["patch"], raw["filename"])
