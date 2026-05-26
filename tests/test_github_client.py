"""Unit tests for github_client helpers (no network calls).

We exercise the bits that are safe to test offline: the next-link parser,
the analyzed-extension filter, and the ``_to_commit`` conversion that filters
non-Java files out before any of the downstream pipeline can see them.
"""
from __future__ import annotations

from src.github_client import _is_analyzed, _next_link, _to_commit


def test_is_analyzed_accepts_java_only():
    assert _is_analyzed("src/main/java/Foo.java") is True
    assert _is_analyzed("Foo.java") is True
    # Anything else must be rejected.
    assert _is_analyzed("scripts/run.py") is False
    assert _is_analyzed("README.md") is False
    assert _is_analyzed("config.yml") is False
    assert _is_analyzed("data.xml") is False
    assert _is_analyzed("Foo.kt") is False
    # Edge cases.
    assert _is_analyzed("") is False
    assert _is_analyzed("javac") is False  # not a .java extension


def test_next_link_parses_github_pagination_header():
    header = (
        '<https://api.github.com/foo?page=2>; rel="next", '
        '<https://api.github.com/foo?page=10>; rel="last"'
    )
    assert _next_link(header) == "https://api.github.com/foo?page=2"


def test_next_link_returns_none_when_absent():
    assert _next_link(None) is None
    assert _next_link('<https://api.github.com/foo?page=10>; rel="last"') is None


def test_to_commit_drops_non_java_files():
    raw = {
        "sha": "deadbeef" * 5,
        "html_url": "https://github.com/owner/repo/commit/x",
        "commit": {
            "message": "fix NPE",
            "author": {"name": "dev", "date": "2024-01-15T10:00:00Z"},
        },
        "files": [
            {
                "filename": "src/main/java/Foo.java",
                "patch": (
                    "@@ -1,2 +1,3 @@\n"
                    " a\n"
                    "+if (x == null) return;\n"
                    " b\n"
                ),
            },
            {
                "filename": "scripts/build.py",
                "patch": "@@ -1,1 +1,1 @@\n-print('a')\n+print('b')\n",
            },
            {
                "filename": "README.md",
                "patch": "@@ -1,1 +1,1 @@\n-foo\n+bar\n",
            },
            {
                "filename": "Foo.kt",
                "patch": "@@ -1,1 +1,1 @@\n-foo\n+bar\n",
            },
        ],
    }
    commit = _to_commit("owner/repo", raw)
    assert len(commit.files) == 1
    assert commit.files[0].path == "src/main/java/Foo.java"


def test_to_commit_returns_empty_files_when_no_java():
    raw = {
        "sha": "deadbeef" * 5,
        "html_url": "https://github.com/owner/repo/commit/x",
        "commit": {
            "message": "doc only",
            "author": {"name": "dev", "date": "2024-01-15T10:00:00Z"},
        },
        "files": [
            {"filename": "README.md", "patch": "@@ -1 +1 @@\n-a\n+b\n"},
            {"filename": "scripts/run.py", "patch": "@@ -1 +1 @@\n-a\n+b\n"},
        ],
    }
    commit = _to_commit("owner/repo", raw)
    assert commit.files == ()
    assert commit.sha == "deadbeef" * 5
    assert commit.message == "doc only"
