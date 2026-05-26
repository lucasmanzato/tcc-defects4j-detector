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
class Evidence:
    """Structural evidences extracted from a commit's diff.

    Fields:
        has_null_check_added: a null comparison or requireNonNull was added.
            Eliminatory: absence forces score = 0.
        null_check_construct: which canonical form (guard_return, ternary, ...).
            Eliminatory: NONE forces score = 0.
        fix_replaces_existing_use: the variable now being null-guarded also
            appears in the same file's removed lines. Strong signal that the
            commit replaces a buggy use with a protected one (real bug fix),
            as opposed to introducing fresh defensive code.
        var_was_used_before: the protected variable appears in the hunk's
            context lines. Weaker confirmation than fix_replaces_existing_use
            because the context window is only ~3 lines.
        adds_new_method_declaration: the commit's added lines introduce a new
            method or type declaration. When True together with the null
            check, the change is more likely defensive scaffolding in new
            code than a fix to existing logic. Used as a score penalty.
        is_likely_bugfix: commit message contains bugfix-language. Weakest
            evidence because messages are unreliable.
        diff_size_lines: total added + removed lines (used only for
            confidence downgrade, not for scoring).
        touches_test_files_only: every changed file is a test (used only
            for confidence downgrade, not for scoring).
    """

    has_null_check_added: bool
    null_check_construct: NullCheckKind
    fix_replaces_existing_use: bool
    var_was_used_before: bool
    adds_new_method_declaration: bool
    is_likely_bugfix: bool
    diff_size_lines: int
    touches_test_files_only: bool


@dataclass(frozen=True)
class CommitCandidate:
    """A scored commit returned by the detector.

    ``matches`` lists every individual location in the commit's diff where the
    pattern fired. ``len(matches)`` is the per-commit occurrence count.
    """

    commit: Commit
    score: float
    confidence: ConfidenceLevel
    evidence: Evidence
    matches: tuple[Match, ...] = ()
