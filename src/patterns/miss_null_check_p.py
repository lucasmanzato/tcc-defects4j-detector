"""Detector for the Defects4J ``missNullCheckP`` pattern.

The pattern fires when the commit adds a null comparison or
``Objects.requireNonNull``/``checkNotNull`` call. Five canonical forms are
recognised (guard_return, guard_throw, guard_block, ternary,
requireNonNull). Two structural evidences are eliminatory: presence of the
null check and presence of a canonical form.

All weights and regexes for this pattern live in this single file so that
adding or modifying another pattern never touches this one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Sequence

from .. import config
from ..models import Commit, ConfidenceLevel, FileDiff, Match, NullCheckKind
from .base import BaseEvidence, PatternDetector


# ============================================================================
# Pattern-specific weights
# ============================================================================
# Calibrated empirically on the 18 reachable Defects4J missNullCheckP bugs.
# See ARCHITECTURE.md and CHANGELOG.md for the calibration rationale.

W_NULL_CHECK_ADDED = 0.50          # eliminatory
W_CANONICAL_CONSTRUCT = 0.25        # eliminatory
W_FIX_REPLACES_USE = 0.15           # strong positive
W_VAR_USED_BEFORE = 0.05            # weak positive (context-only check)
W_BUGFIX_MESSAGE = 0.05             # very weak (commit messages lie)
PENALTY_ADDS_NEW_METHOD = 0.20      # subtracted after positives

DEFAULT_MIN_SCORE = config.DEFAULT_MIN_SCORE
SCORE_LOW_MAX = config.SCORE_LOW_MAX
SCORE_MEDIUM_MAX = config.SCORE_MEDIUM_MAX
LARGE_DIFF_LINES = config.LARGE_DIFF_LINES


# ============================================================================
# Regex catalogue — the structural mask
# ============================================================================
# Match "<expr> == null" or "null == <expr>", where <expr> may be a bare
# identifier, an indexed access (a[i]), member access (a.b.c), or method
# call (a.b()).
_NULL_COMPARISON = re.compile(
    r"(?:\w+\s*\([^)]*\)|\w+(?:\s*\[[^\]]*\]|\s*\.\w+)*)\s*==\s*null"
    r"|null\s*==\s*(?:\w+\s*\([^)]*\)|\w+(?:\s*\[[^\]]*\]|\s*\.\w+)*)"
)
_REQUIRE_NON_NULL = re.compile(r"\b(?:Objects\.requireNonNull|checkNotNull)\s*\(")
_GUARD_RETURN = re.compile(r"==\s*null\b.*\breturn\b", re.DOTALL)
_GUARD_THROW = re.compile(r"==\s*null\b.*\bthrow\b", re.DOTALL)
_TERNARY = re.compile(r"==\s*null\s*\?")

# Variable name extracted from "<expr> == null" or "null == <expr>".
_VAR_FROM_NULL_CMP = re.compile(
    r"(?:^|[^\w.])(\w+)(?:\s*\[[^\]]*\]|\s*\.\w+(?:\s*\([^)]*\))?)*\s*==\s*null\b"
    r"|\bnull\s*==\s*(\w+)\b"
)
_VAR_FROM_REQUIRE = re.compile(
    r"\brequireNonNull\s*\(\s*(\w+)|\bcheckNotNull\s*\(\s*(\w+)"
)

# Method/type declaration regexes (shared structural signal across patterns).
_NEW_METHOD_DECL = re.compile(
    r"\b(?:public|private|protected)\s+"
    r"(?:static\s+|final\s+|abstract\s+|synchronized\s+)*"
    r"[\w<>\[\],\s?]+?\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{?"
)
_NEW_TYPE_DECL = re.compile(
    r"\b(?:public|private|protected)\s+"
    r"(?:static\s+|final\s+|abstract\s+)*"
    r"(?:class|interface|enum|record)\s+\w+"
)


# ============================================================================
# Pattern-specific evidence
# ============================================================================
@dataclass(frozen=True, kw_only=True)
class NullCheckEvidence(BaseEvidence):
    """Evidences specific to ``missNullCheckP``."""

    has_null_check_added: bool
    null_check_construct: NullCheckKind


# ============================================================================
# Pure functions (regex-level)
# ============================================================================
def classify_line(line: str, *, neighbours: Sequence[str] = ()) -> NullCheckKind:
    """Classify a single added line into a :class:`NullCheckKind`."""
    haystack = " ".join((line, *neighbours))
    if _REQUIRE_NON_NULL.search(line):
        return NullCheckKind.REQUIRE_NON_NULL
    if _TERNARY.search(line):
        return NullCheckKind.TERNARY
    if not _NULL_COMPARISON.search(line):
        return NullCheckKind.NONE
    if _GUARD_THROW.search(haystack):
        return NullCheckKind.GUARD_THROW
    if _GUARD_RETURN.search(haystack):
        return NullCheckKind.GUARD_RETURN
    return NullCheckKind.GUARD_BLOCK


def detect_null_check(added_lines: Sequence[str]) -> NullCheckKind:
    """Classify the aggregate added lines into a :class:`NullCheckKind`."""
    joined = " ".join(added_lines)
    if _REQUIRE_NON_NULL.search(joined):
        return NullCheckKind.REQUIRE_NON_NULL
    if _TERNARY.search(joined):
        return NullCheckKind.TERNARY
    if not _NULL_COMPARISON.search(joined):
        return NullCheckKind.NONE
    if _GUARD_THROW.search(joined):
        return NullCheckKind.GUARD_THROW
    if _GUARD_RETURN.search(joined):
        return NullCheckKind.GUARD_RETURN
    return NullCheckKind.GUARD_BLOCK


def has_null_check_added(added_lines: Sequence[str]) -> bool:
    return detect_null_check(added_lines) is not NullCheckKind.NONE


def variable_used_before(file_diff: FileDiff) -> bool:
    candidates = _variables_protected_by_null_check(file_diff.added_lines)
    if not candidates:
        return False
    haystack = (
        " ".join(file_diff.context_lines)
        + " "
        + " ".join(file_diff.removed_lines)
    )
    return any(re.search(rf"\b{re.escape(v)}\b", haystack) for v in candidates)


def fix_replaces_existing_use(file_diff: FileDiff) -> bool:
    candidates = _variables_protected_by_null_check(file_diff.added_lines)
    if not candidates:
        return False
    removed_text = " ".join(file_diff.removed_lines)
    if not removed_text.strip():
        return False
    return any(re.search(rf"\b{re.escape(v)}\b", removed_text) for v in candidates)


def adds_new_method_declaration(file_diff: FileDiff) -> bool:
    added_decls = _declarations_in(file_diff.added_lines)
    if not added_decls:
        return False
    removed_decls = _declarations_in(file_diff.removed_lines)
    if not (added_decls - removed_decls):
        return False
    if file_diff.removed_lines:
        return False
    return True


def is_bugfix_message(message: str) -> bool:
    if not message:
        return False
    lower = message.lower()
    return any(kw in lower for kw in config.BUGFIX_KEYWORDS)


def diff_size_lines(files: Sequence[FileDiff]) -> int:
    return sum(len(f.added_lines) + len(f.removed_lines) for f in files)


def touches_test_files_only(files: Sequence[FileDiff]) -> bool:
    if not files:
        return False
    return all(_is_test_path(f.path) for f in files)


# ============================================================================
# Detector class
# ============================================================================
class MissNullCheckPDetector(PatternDetector):
    """Detector for the ``missNullCheckP`` Defects4J pattern."""

    name: ClassVar[str] = "missNullCheckP"
    description: ClassVar[str] = (
        "Adição de verificação de valor vazio ausente "
        "(causa de NullPointerException)"
    )

    def extract_evidence(self, commit: Commit) -> NullCheckEvidence:
        java_files = tuple(f for f in commit.files if f.path.endswith(".java"))
        production_files = tuple(f for f in java_files if not _is_test_path(f.path))
        target_files = production_files

        all_added = tuple(line for f in target_files for line in f.added_lines)

        construct = detect_null_check(all_added)
        null_check = construct is not NullCheckKind.NONE
        var_used_before = any(variable_used_before(f) for f in target_files)
        replaces_use = any(fix_replaces_existing_use(f) for f in target_files)
        new_method = any(adds_new_method_declaration(f) for f in target_files)
        bugfix = is_bugfix_message(commit.message)
        size = diff_size_lines(commit.files)
        tests_only = touches_test_files_only(commit.files)

        return NullCheckEvidence(
            has_null_check_added=null_check,
            null_check_construct=construct,
            fix_replaces_existing_use=replaces_use,
            var_was_used_before=var_used_before,
            adds_new_method_declaration=new_method,
            is_likely_bugfix=bugfix,
            diff_size_lines=size,
            touches_test_files_only=tests_only,
        )

    def score(self, evidence: BaseEvidence) -> float:
        if not isinstance(evidence, NullCheckEvidence):
            raise TypeError(
                f"{type(self).__name__} requires NullCheckEvidence, "
                f"got {type(evidence).__name__}"
            )
        if not evidence.has_null_check_added:
            return 0.0
        if evidence.null_check_construct is NullCheckKind.NONE:
            return 0.0

        total = W_NULL_CHECK_ADDED + W_CANONICAL_CONSTRUCT
        if evidence.fix_replaces_existing_use:
            total += W_FIX_REPLACES_USE
        if evidence.var_was_used_before:
            total += W_VAR_USED_BEFORE
        if evidence.is_likely_bugfix:
            total += W_BUGFIX_MESSAGE
        if evidence.adds_new_method_declaration:
            total -= PENALTY_ADDS_NEW_METHOD
        total = max(0.0, min(1.0, total))
        return round(total, 4)

    def confidence_level(self, score_value: float, evidence: BaseEvidence) -> ConfidenceLevel:
        if score_value < SCORE_LOW_MAX:
            return "low"
        if score_value < SCORE_MEDIUM_MAX:
            return "medium"
        if evidence.diff_size_lines > LARGE_DIFF_LINES:
            return "medium"
        if evidence.touches_test_files_only:
            return "medium"
        return "high"

    def find_matches(self, commit: Commit) -> tuple[Match, ...]:
        matches: list[Match] = []
        for file_diff in commit.files:
            if not file_diff.path.endswith(".java"):
                continue
            if _is_test_path(file_diff.path):
                continue
            lines_with_lineno = file_diff.added_with_lineno
            for index, (lineno, text) in enumerate(lines_with_lineno):
                neighbours = tuple(
                    t for _, t in lines_with_lineno[index + 1 : index + 3]
                )
                kind = classify_line(text, neighbours=neighbours)
                if kind is NullCheckKind.NONE:
                    continue
                matches.append(
                    Match(
                        file_path=file_diff.path,
                        line_number=lineno,
                        construct=kind,
                        snippet=text,
                    )
                )
        return tuple(matches)


# ============================================================================
# Helpers
# ============================================================================
def _variables_protected_by_null_check(added_lines: Sequence[str]) -> tuple[str, ...]:
    found: list[str] = []
    for line in added_lines:
        for m in _VAR_FROM_NULL_CMP.finditer(line):
            name = m.group(1) or m.group(2)
            if name:
                found.append(name)
        for m in _VAR_FROM_REQUIRE.finditer(line):
            name = m.group(1) or m.group(2)
            if name:
                found.append(name)
    seen: set[str] = set()
    unique: list[str] = []
    for v in found:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return tuple(unique)


def _is_test_path(path: str) -> bool:
    return any(marker in path for marker in config.JAVA_TEST_PATH_MARKERS)


def _declarations_in(lines: Sequence[str]) -> set[str]:
    decls: set[str] = set()
    for line in lines:
        for match in _NEW_METHOD_DECL.finditer(line):
            decls.add(_normalise_signature(match.group(0)))
        for match in _NEW_TYPE_DECL.finditer(line):
            decls.add(_normalise_signature(match.group(0)))
    return decls


def _normalise_signature(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip("{").strip()
