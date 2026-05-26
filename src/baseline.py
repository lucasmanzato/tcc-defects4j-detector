"""Naive baseline: classify a commit purely by keywords in its message.

Used as the comparison line in the evaluation report. The classifier returns
True when the message mentions any of the canonical NPE keywords.
"""
from __future__ import annotations

from .models import Commit

KEYWORDS: tuple[str, ...] = (
    "null",
    "npe",
    "nullpointerexception",
    "null pointer",
)


def baseline_classify(commit: Commit) -> bool:
    """True if the commit message mentions any of the null-related keywords."""
    if not commit.message:
        return False
    lower = commit.message.lower()
    return any(kw in lower for kw in KEYWORDS)
