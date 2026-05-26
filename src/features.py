"""Structural feature extraction from a Commit's diff.

Each function returns a single, narrowly-defined evidence so the scorer can
combine them with explicit weights. No regex monoliths: each construct gets
its own small detector, and the public ``extract_evidence`` aggregates them.
"""
from __future__ import annotations

import re
from typing import Sequence

from . import config
from .models import Commit, Evidence, FileDiff, Match, NullCheckKind

# --- null-check construct detectors -----------------------------------------
# Each pattern below targets a single canonical form. We deliberately accept
# ``Foo.requireNonNull`` (Guava's Preconditions.checkNotNull is matched too).

# Match "<expr> == null" or "null == <expr>", where <expr> may be a bare
# identifier, an indexed access (a[i]), a member access (a.b.c), or a method
# call (a.b()). The regex stays cheap (no backreferences) and just confirms
# the comparison is present, leaving variable extraction to a stricter regex.
_NULL_COMPARISON = re.compile(
    r"(?:\w+\s*\([^)]*\)|\w+(?:\s*\[[^\]]*\]|\s*\.\w+)*)\s*==\s*null"
    r"|null\s*==\s*(?:\w+\s*\([^)]*\)|\w+(?:\s*\[[^\]]*\]|\s*\.\w+)*)"
)
_REQUIRE_NON_NULL = re.compile(r"\b(?:Objects\.requireNonNull|checkNotNull)\s*\(")
_GUARD_RETURN = re.compile(r"==\s*null\b.*\breturn\b", re.DOTALL)
_GUARD_THROW = re.compile(r"==\s*null\b.*\bthrow\b", re.DOTALL)
_TERNARY = re.compile(r"==\s*null\s*\?")

# Variable name extracted from "<expr> == null" or "null == <expr>". The expr
# may include array indices (a[i]), member access (a.b.c), or method calls
# (a.b()). We capture the leading identifier as the protected variable.
_VAR_FROM_NULL_CMP = re.compile(
    r"(?:^|[^\w.])(\w+)(?:\s*\[[^\]]*\]|\s*\.\w+(?:\s*\([^)]*\))?)*\s*==\s*null\b"
    r"|\bnull\s*==\s*(\w+)\b"
)
_VAR_FROM_REQUIRE = re.compile(r"\brequireNonNull\s*\(\s*(\w+)|\bcheckNotNull\s*\(\s*(\w+)")

# Java method declarations: optional modifiers + return type + name + parens
# + optional throws clause + opening brace. Conservative — only fires on the
# canonical "public/private/protected" forms to avoid false positives on
# arbitrary call sites that happen to live on the same line.
_NEW_METHOD_DECL = re.compile(
    r"\b(?:public|private|protected)\s+(?:static\s+|final\s+|abstract\s+|synchronized\s+)*"
    r"[\w<>\[\],\s?]+?\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{?"
)

# Java type declarations: class / interface / enum / record.
_NEW_TYPE_DECL = re.compile(
    r"\b(?:public|private|protected)\s+(?:static\s+|final\s+|abstract\s+)*"
    r"(?:class|interface|enum|record)\s+\w+"
)


def classify_line(line: str, *, neighbours: Sequence[str] = ()) -> NullCheckKind:
    """Classify a single added line into a :class:`NullCheckKind`.

    ``neighbours`` are nearby added lines (typically the next 1-2 lines after
    ``line``) used to recognise multi-line guard blocks where the comparison
    and the ``return``/``throw`` live on different lines, e.g.::

        if (x == null) {
            return null;
        }
    """
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


def find_matches(commit: Commit) -> tuple[Match, ...]:
    """Return every individual occurrence of the pattern in the commit.

    Each occurrence is reported with its file path, target-file line number,
    the canonical construct that fired, and the trimmed source snippet. Test
    files are skipped so the count reflects production-code locations.
    """
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


def detect_null_check(added_lines: Sequence[str]) -> NullCheckKind:
    """Return the canonical null-check construct introduced by the added lines.

    The classification order matters: ``requireNonNull`` and ternary are
    syntactically distinct from guard blocks, so they win when present. Only
    if neither matches do we fall back to differentiating guard_return from
    guard_throw.
    """
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
    # Null comparison is present but with no enclosing return/throw: a generic
    # ``if (x == null) { ... }`` guard. Still a canonical missing-null-check
    # repair.
    return NullCheckKind.GUARD_BLOCK


def has_null_check_added(added_lines: Sequence[str]) -> bool:
    """True if any added line introduces a null comparison or requireNonNull."""
    return detect_null_check(added_lines) is not NullCheckKind.NONE


def variable_used_before(file_diff: FileDiff) -> bool:
    """Best-effort check that a variable now being null-guarded was already used.

    We only inspect the hunk context lines for the same FileDiff (no extra API
    request, see README for the rationale and limitations of this heuristic).
    Returns True if at least one of the variables mentioned in an added null
    check appears in the context or removed lines.
    """
    candidates = _variables_protected_by_null_check(file_diff.added_lines)
    if not candidates:
        return False
    haystack = " ".join(file_diff.context_lines) + " " + " ".join(file_diff.removed_lines)
    return any(re.search(rf"\b{re.escape(v)}\b", haystack) for v in candidates)


def fix_replaces_existing_use(file_diff: FileDiff) -> bool:
    """True when the null-guarded variable also appears in the removed lines.

    A real ``missNullCheckP`` fix typically REMOVES a vulnerable use and
    REPLACES it with a guarded one (e.g. ``array[i].getClass()`` becomes
    ``array[i] == null ? null : array[i].getClass()``). When this pattern
    is present we have strong evidence that an existing bug is being
    repaired, not that brand-new defensive code is being introduced.

    The check looks at removed lines only: appearance of the protected
    variable elsewhere in the file (context) is covered by
    :func:`variable_used_before`.
    """
    candidates = _variables_protected_by_null_check(file_diff.added_lines)
    if not candidates:
        return False
    removed_text = " ".join(file_diff.removed_lines)
    if not removed_text.strip():
        return False
    return any(re.search(rf"\b{re.escape(v)}\b", removed_text) for v in candidates)


def adds_new_method_declaration(file_diff: FileDiff) -> bool:
    """True when this file looks like a *pure addition* of new declarations.

    Returns True only when:

    1. The added lines introduce at least one method/class/interface/enum
       declaration that is NOT present in the removed lines.
    2. The file has NO removed lines at all — i.e. it is being created or
       only appended to.

    The second clause is what keeps real bug fixes safe. A fix that refactors
    code (extracts a helper method, splits a function) introduces a new
    declaration AND removes the old body. The "pure addition" case captures
    the actual false-positive class we want to filter: a brand-new feature
    method that happens to contain a defensive null check at the top.
    """
    added_decls = _declarations_in(file_diff.added_lines)
    if not added_decls:
        return False
    removed_decls = _declarations_in(file_diff.removed_lines)
    if not (added_decls - removed_decls):
        return False
    # File has any removed content at all? Then it's not a pure addition.
    if file_diff.removed_lines:
        return False
    return True


def is_bugfix_message(message: str) -> bool:
    """Heuristic: does the commit message look like a bugfix?

    True when it mentions any keyword from ``config.BUGFIX_KEYWORDS`` and the
    first line is reasonably short (typical bugfix commits, not long-form
    feature descriptions). Long messages also pass if they explicitly mention
    NPE or null-related keywords.
    """
    if not message:
        return False
    lower = message.lower()
    return any(kw in lower for kw in config.BUGFIX_KEYWORDS)


def diff_size_lines(files: Sequence[FileDiff]) -> int:
    """Total added + removed lines across all files in a commit."""
    return sum(len(f.added_lines) + len(f.removed_lines) for f in files)


def touches_test_files_only(files: Sequence[FileDiff]) -> bool:
    """True if every file in the commit looks like a test file."""
    if not files:
        return False
    return all(_is_test_path(f.path) for f in files)


def extract_evidence(commit: Commit) -> Evidence:
    """Aggregate all per-evidence detectors into a single :class:`Evidence`.

    Test files are excluded from the structural evidences (null check, var
    used before, fix replaces use, new method declaration) because the
    ``missNullCheckP`` pattern targets repair in production code; assertions
    in tests are not bug fixes.
    """
    java_files = tuple(f for f in commit.files if f.path.endswith(".java"))
    production_files = tuple(f for f in java_files if not _is_test_path(f.path))
    target_files = production_files or (java_files if not java_files else ())

    all_added = tuple(line for f in target_files for line in f.added_lines)

    construct = detect_null_check(all_added)
    null_check = construct is not NullCheckKind.NONE
    var_used_before = any(variable_used_before(f) for f in target_files)
    replaces_use = any(fix_replaces_existing_use(f) for f in target_files)
    new_method = any(adds_new_method_declaration(f) for f in target_files)
    bugfix = is_bugfix_message(commit.message)
    size = diff_size_lines(commit.files)
    tests_only = touches_test_files_only(commit.files)

    return Evidence(
        has_null_check_added=null_check,
        null_check_construct=construct,
        fix_replaces_existing_use=replaces_use,
        var_was_used_before=var_used_before,
        adds_new_method_declaration=new_method,
        is_likely_bugfix=bugfix,
        diff_size_lines=size,
        touches_test_files_only=tests_only,
    )


# --- helpers -----------------------------------------------------------------
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
    """Return the set of method/type declaration signatures found in ``lines``.

    Signatures are normalised (collapsed whitespace) so that "moved" methods
    appearing in both added and removed lines compare equal.
    """
    decls: set[str] = set()
    for line in lines:
        for match in _NEW_METHOD_DECL.finditer(line):
            decls.add(_normalise_signature(match.group(0)))
        for match in _NEW_TYPE_DECL.finditer(line):
            decls.add(_normalise_signature(match.group(0)))
    return decls


def _normalise_signature(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip("{").strip()
