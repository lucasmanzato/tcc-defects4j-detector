"""Immutable domain models shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal


class NullCheckKind(str, Enum):
    NONE = "none"
    GUARD_RETURN = "guard_return"
    GUARD_THROW = "guard_throw"
    GUARD_BLOCK = "guard_block"
    TERNARY = "ternary"
    REQUIRE_NON_NULL = "requireNonNull"


ConfidenceLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class FileDiff:
    """Parsed diff for a single file in a commit.

    ``added_with_lineno`` carries the same content as ``added_lines`` but with
    each line paired with its target-file line number, so downstream
    detection can emit precise location matches without re-parsing.
    """

    path: str
    patch: str
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]
    context_lines: tuple[str, ...]
    added_with_lineno: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class Match:
    """A single occurrence of the ``missNullCheckP`` pattern in a commit.

    Multiple ``Match`` instances may originate from the same commit when the
    fix touches more than one location.
    """

    file_path: str
    line_number: int
    construct: "NullCheckKind"
    snippet: str


@dataclass(frozen=True)
class Commit:
    """A commit retrieved from the GitHub API."""

    sha: str
    message: str
    author: str
    date: datetime
    files: tuple[FileDiff, ...]
    url: str


@dataclass(frozen=True)
class CommitCandidate:
    """A scored commit returned by the detector.

    ``evidence`` is a pattern-specific record (subclass of
    :class:`src.patterns.base.BaseEvidence`); its concrete fields depend on
    which :class:`PatternDetector` produced it.
    """

    commit: Commit
    score: float
    confidence: ConfidenceLevel
    evidence: object
    matches: tuple[Match, ...] = ()
