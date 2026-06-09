"""Detector for the Defects4J ``condBlockRetAdd`` pattern.

The pattern fires when the commit adds an ``if (condition) { return ...; }``
guard clause. The condition is arbitrary (any boolean expression), unlike
``missNullCheckP`` which only fires on ``== null`` comparisons. The two
patterns therefore overlap when the condition involves a null check; the
classification preserves both labels in the ground truth.

Four canonical forms are recognised:

- ``bare_return``      ``if (cond) { return; }``
- ``return_value``     ``if (cond) { return value; }``
- ``return_expression`` ``if (cond) { return foo(bar); }`` / ``return -1;``
- ``compact_one_line``  ``if (cond) return ...;`` (no braces)

A null-check-flavoured guard like ``if (x == null) return null;`` would be
caught both here and by ``missNullCheckP``. That is the intended behaviour:
``missNullCheckP guard_return`` is a *specialisation* of this pattern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Sequence

from .. import config
from ..models import Commit, ConfidenceLevel, FileDiff, Match
from .base import BaseEvidence, PatternDetector


# ============================================================================
# Pattern-specific weights
# ============================================================================
# Calibrated on the 71 reachable condBlockRetAdd bugs from Defects4J
# Dissection. Mirrors the missNullCheckP weights (v0.2.0) with one key
# difference, documented below.
#
# The pure-addition new-method PENALTY that v0.2.0 added to missNullCheckP
# is intentionally DROPPED here. Empirical reason: in condBlockRetAdd,
# adding a guard-return at the top of a freshly declared method is a
# common LEGITIMATE fix shape (e.g. overriding equals/compareTo to handle
# specific cases, Lang 23 and Lang 64 in the ground truth). For
# missNullCheckP the same shape is a false positive (defensive code), but
# for the broader condBlockRetAdd it would cost recall (~3.5 percentage
# points on the reachable ground truth) without a clear FP-reduction win.

W_GUARD_ADDED = 0.50                # eliminatory (the if-return was added)
W_CANONICAL_FORM = 0.25             # eliminatory (matches one of the 4 forms)
W_FIX_REPLACES_USE = 0.15           # positive confirmation
W_CONDITION_VAR_USED_BEFORE = 0.05  # weak positive
W_BUGFIX_MESSAGE = 0.05             # weak descriptive
# PENALTY_ADDS_NEW_METHOD intentionally omitted — see comment above.

DEFAULT_MIN_SCORE = config.DEFAULT_MIN_SCORE
SCORE_LOW_MAX = config.SCORE_LOW_MAX
SCORE_MEDIUM_MAX = config.SCORE_MEDIUM_MAX
LARGE_DIFF_LINES = config.LARGE_DIFF_LINES


# ============================================================================
# Canonical forms (the "shapes" of an if-return guard)
# ============================================================================
class CondReturnKind(str, Enum):
    NONE = "none"
    BARE_RETURN = "bare_return"
    RETURN_VALUE = "return_value"
    RETURN_EXPRESSION = "return_expression"
    COMPACT_ONE_LINE = "compact_one_line"


# ============================================================================
# Regex catalogue — the structural mask
# ============================================================================
# Lightweight detectors. They only test the *shape* of a line; the exact
# condition is extracted afterwards with a balanced-paren scanner so that
# deeply nested method calls inside the condition still match.
_IF_OPEN = re.compile(r"\bif\s*\(")
_RETURN_TOKEN = re.compile(r"\breturn\b")
_TRAILING_BRACE = re.compile(r"\)\s*\{?\s*$")

# ``return <expr>;`` standalone (for multi-line blocks).
_RETURN_LINE = re.compile(r"^\s*return\b\s*(?P<val>[^;]*?)\s*;\s*$")

# Identifier extraction from a condition expression — used to test whether
# the variables involved already existed in the surrounding code.
_IDENT = re.compile(r"\b([A-Za-z_]\w*)\b")
_JAVA_KEYWORDS: frozenset[str] = frozenset(
    {
        "if", "else", "return", "null", "true", "false", "this",
        "new", "for", "while", "do", "switch", "case", "break",
        "continue", "throw", "throws", "instanceof", "and", "or", "not",
    }
)

# Method/type declarations — reused from missNullCheckP heuristic.
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
class CondReturnEvidence(BaseEvidence):
    """Evidences specific to ``condBlockRetAdd``."""

    has_guard_added: bool
    cond_return_form: CondReturnKind


# ============================================================================
# Pure functions — match a single line, then aggregate
# ============================================================================
def classify_line(line: str, *, neighbours: Sequence[str] = ()) -> CondReturnKind:
    """Classify a single added line (plus optional follow-up lines) into a
    :class:`CondReturnKind`.

    Four shapes are recognised:

    - ``COMPACT_ONE_LINE``: ``if (cond) return ...;`` on one line.
    - ``BARE_RETURN`` / ``RETURN_VALUE`` / ``RETURN_EXPRESSION``: this line
      is the opening of an ``if (cond) {`` block; a following neighbour
      line carries the ``return ...;`` statement.

    Condition extraction uses a balanced-parenthesis scanner across ``line``
    AND, if needed, the first few ``neighbours`` — that is what lets
    multi-line conditions like::

        if (var != null
            && var.getParentNode().isCatch()) {

    be recognised. Deeply nested method calls inside the condition
    (``if (a.equals(b.foo()))``) are handled by the same scanner.
    """
    cond_end = _consume_if_condition(line, neighbours=neighbours)
    if cond_end is None:
        return CondReturnKind.NONE

    after = cond_end.tail
    extra_neighbours_skipped = cond_end.neighbours_used

    # Compact form: same line (or final continuation line) contains the return.
    tail = after.lstrip()
    if _RETURN_TOKEN.match(tail):
        return CondReturnKind.COMPACT_ONE_LINE

    # Block opener: must look like ``if (cond) {`` or ``if (cond)`` with the
    # ``{`` on the next line. Reject anything else (e.g. ``if (cond) doX();``).
    stripped_tail = tail.strip()
    if stripped_tail not in {"", "{"} and not stripped_tail.startswith("{"):
        return CondReturnKind.NONE

    # Look ahead for a ``return ...;`` statement in the *remaining*
    # neighbours (we skip the ones that were consumed by the multi-line
    # condition continuation).
    for neighbour in neighbours[extra_neighbours_skipped:]:
        ret = _RETURN_LINE.search(neighbour)
        if ret:
            value = ret.group("val").strip()
            return _classify_return_value(value)
    return CondReturnKind.NONE


@dataclass(frozen=True)
class _ConditionMatch:
    tail: str
    neighbours_used: int


def _consume_if_condition(
    line: str, *, neighbours: Sequence[str] = ()
) -> _ConditionMatch | None:
    """Return the position after a balanced ``if (...)`` clause.

    ``tail`` is the substring AFTER the closing parenthesis. If the closing
    parenthesis is not on ``line`` itself, the scanner continues into
    ``neighbours`` line-by-line and records how many were consumed.
    Returns ``None`` when no ``if (`` is found, or when the parens never
    balance even with all neighbours appended.
    """
    match = _IF_OPEN.search(line)
    if not match:
        return None
    start = match.end()
    sources = [line, *neighbours]
    depth = 1
    src_index = 0
    pos = start
    while src_index < len(sources):
        text = sources[src_index]
        while pos < len(text):
            ch = text[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return _ConditionMatch(
                        tail=text[pos + 1 :],
                        neighbours_used=src_index,
                    )
            pos += 1
        # Move to the next continuation line.
        src_index += 1
        pos = 0
    return None  # unbalanced even after all neighbours


def _classify_return_value(value: str) -> CondReturnKind:
    """Classify a ``return <value>;`` into one of the value-shape kinds."""
    if not value:
        return CondReturnKind.BARE_RETURN
    # Single token: literal or identifier.
    if re.fullmatch(r"[A-Za-z_]\w*|true|false|null|-?\d+(?:\.\d+)?[fFdDlL]?|\".*\"", value):
        return CondReturnKind.RETURN_VALUE
    return CondReturnKind.RETURN_EXPRESSION


def detect_cond_return_in_file(file_diff: FileDiff) -> CondReturnKind:
    """Return the strongest form fired by any added line in this file."""
    lines = file_diff.added_with_lineno or tuple(
        (i + 1, line) for i, line in enumerate(file_diff.added_lines)
    )
    best = CondReturnKind.NONE
    for idx, (_, text) in enumerate(lines):
        neighbours = tuple(t for _, t in lines[idx + 1 : idx + 6])
        kind = classify_line(text, neighbours=neighbours)
        if kind is not CondReturnKind.NONE:
            # Any concrete form is treated as "fired"; we don't need the
            # strongest one for evidence purposes, just the first.
            return kind
    return best


def has_guard_added(files: Sequence[FileDiff]) -> bool:
    return any(
        detect_cond_return_in_file(f) is not CondReturnKind.NONE for f in files
    )


def fix_replaces_existing_use(file_diff: FileDiff) -> bool:
    """True when an identifier from the added guard's condition also appears
    in the removed lines — the canonical fix shape (replaced existing use).
    """
    identifiers = _identifiers_in_added_guards(file_diff)
    if not identifiers:
        return False
    removed_text = " ".join(file_diff.removed_lines)
    if not removed_text.strip():
        return False
    return any(re.search(rf"\b{re.escape(v)}\b", removed_text) for v in identifiers)


def condition_var_used_before(file_diff: FileDiff) -> bool:
    """True when at least one identifier from the guard's condition appears
    in the surrounding hunk context (or removed lines).
    """
    identifiers = _identifiers_in_added_guards(file_diff)
    if not identifiers:
        return False
    haystack = (
        " ".join(file_diff.context_lines)
        + " "
        + " ".join(file_diff.removed_lines)
    )
    return any(re.search(rf"\b{re.escape(v)}\b", haystack) for v in identifiers)


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
class CondBlockRetAddDetector(PatternDetector):
    """Detector for the ``condBlockRetAdd`` Defects4J pattern."""

    name: ClassVar[str] = "condBlockRetAdd"
    description: ClassVar[str] = (
        "Adição de bloco condicional com return antecipado "
        "(guard clause / early return)"
    )

    def extract_evidence(self, commit: Commit) -> CondReturnEvidence:
        java_files = tuple(f for f in commit.files if f.path.endswith(".java"))
        production_files = tuple(f for f in java_files if not _is_test_path(f.path))
        target_files = production_files

        form = CondReturnKind.NONE
        for f in target_files:
            file_form = detect_cond_return_in_file(f)
            if file_form is not CondReturnKind.NONE:
                form = file_form
                break

        guard_added = form is not CondReturnKind.NONE
        replaces_use = any(fix_replaces_existing_use(f) for f in target_files)
        var_used_before = any(condition_var_used_before(f) for f in target_files)
        bugfix = is_bugfix_message(commit.message)
        size = diff_size_lines(commit.files)
        tests_only = touches_test_files_only(commit.files)

        return CondReturnEvidence(
            has_guard_added=guard_added,
            cond_return_form=form,
            fix_replaces_existing_use=replaces_use,
            var_was_used_before=var_used_before,
            # Penalty disabled for this pattern (see weights section).
            adds_new_method_declaration=False,
            is_likely_bugfix=bugfix,
            diff_size_lines=size,
            touches_test_files_only=tests_only,
        )

    def score(self, evidence: BaseEvidence) -> float:
        if not isinstance(evidence, CondReturnEvidence):
            raise TypeError(
                f"{type(self).__name__} requires CondReturnEvidence, "
                f"got {type(evidence).__name__}"
            )
        if not evidence.has_guard_added:
            return 0.0
        if evidence.cond_return_form is CondReturnKind.NONE:
            return 0.0

        total = W_GUARD_ADDED + W_CANONICAL_FORM
        if evidence.fix_replaces_existing_use:
            total += W_FIX_REPLACES_USE
        if evidence.var_was_used_before:
            total += W_CONDITION_VAR_USED_BEFORE
        if evidence.is_likely_bugfix:
            total += W_BUGFIX_MESSAGE
        # No new-method penalty for condBlockRetAdd — see weights section.
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
            lines = file_diff.added_with_lineno
            for idx, (lineno, text) in enumerate(lines):
                neighbours = tuple(t for _, t in lines[idx + 1 : idx + 6])
                kind = classify_line(text, neighbours=neighbours)
                if kind is CondReturnKind.NONE:
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
def _identifiers_in_added_guards(file_diff: FileDiff) -> tuple[str, ...]:
    """Pull identifier tokens out of conditions in any added if-guards.

    Uses the same balanced-paren scanner as :func:`classify_line`, so
    multi-line conditions and nested method calls are extracted correctly.
    """
    identifiers: list[str] = []
    seen: set[str] = set()
    added = list(file_diff.added_lines)
    for idx, line in enumerate(added):
        cond_text = _extract_condition_text(line, neighbours=added[idx + 1 : idx + 4])
        if not cond_text:
            continue
        for match in _IDENT.finditer(cond_text):
            name = match.group(1)
            if name in _JAVA_KEYWORDS:
                continue
            if name in seen:
                continue
            seen.add(name)
            identifiers.append(name)
    return tuple(identifiers)


def _extract_condition_text(line: str, *, neighbours: Sequence[str] = ()) -> str | None:
    """Return the literal text of the ``if (...)`` condition or ``None``.

    Mirrors :func:`_consume_if_condition` but returns the inside of the
    parens rather than the tail. Used purely for identifier extraction.
    """
    match = _IF_OPEN.search(line)
    if not match:
        return None
    start = match.end()
    sources = [line, *neighbours]
    depth = 1
    src_index = 0
    pos = start
    captured: list[str] = []
    # Track which source we're currently consuming text from.
    chunk_start = start
    while src_index < len(sources):
        text = sources[src_index]
        if src_index == 0:
            chunk_start = start
        else:
            chunk_start = 0
        while pos < len(text):
            ch = text[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    captured.append(text[chunk_start:pos])
                    return " ".join(s.strip() for s in captured if s.strip())
            pos += 1
        captured.append(text[chunk_start:])
        src_index += 1
        pos = 0
    return None


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
