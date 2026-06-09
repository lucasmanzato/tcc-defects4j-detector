"""Tests for the missNullCheckP pattern detector.

Uses real Defects4J diffs as fixtures. Each function under test now lives
in ``src/patterns/miss_null_check_p.py``; the detector class
``MissNullCheckPDetector`` orchestrates them through
``extract_evidence`` / ``score`` / ``find_matches``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.diff_parser import parse_unified_diff
from src.patterns.miss_null_check_p import (
    MissNullCheckPDetector,
    adds_new_method_declaration,
    classify_line,
    detect_null_check,
    diff_size_lines,
    fix_replaces_existing_use,
    has_null_check_added,
    is_bugfix_message,
    touches_test_files_only,
    variable_used_before,
)
from src.models import Commit, FileDiff, NullCheckKind

_DETECTOR = MissNullCheckPDetector()
extract_evidence = _DETECTOR.extract_evidence
find_matches = _DETECTOR.find_matches

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _make_commit(message: str, files: tuple[FileDiff, ...]) -> Commit:
    return Commit(
        sha="deadbeef" * 5,
        message=message,
        author="dev",
        date=datetime(2020, 1, 1),
        files=files,
        url="https://example/commit",
    )


# --- detect_null_check -------------------------------------------------------
def test_detect_lang33_classifies_as_ternary():
    files = parse_unified_diff(_read("lang_33.diff"))
    assert detect_null_check(files[0].added_lines) is NullCheckKind.TERNARY


def test_detect_math4_classifies_as_guard_return():
    files = parse_unified_diff(_read("math_4.diff"))
    added = tuple(line for f in files for line in f.added_lines)
    assert detect_null_check(added) is NullCheckKind.GUARD_RETURN


def test_detect_require_non_null_wins_over_guard():
    added = ("Objects.requireNonNull(x);", "if (y == null) throw new RuntimeException();")
    assert detect_null_check(added) is NullCheckKind.REQUIRE_NON_NULL


def test_detect_guard_throw_when_throw_present():
    added = ("if (x == null) {", "throw new IllegalArgumentException();", "}")
    assert detect_null_check(added) is NullCheckKind.GUARD_THROW


def test_detect_returns_none_when_no_null_logic():
    added = ("int total = a + b;", "list.add(total);")
    assert detect_null_check(added) is NullCheckKind.NONE


def test_has_null_check_added_true_for_lang33():
    files = parse_unified_diff(_read("lang_33.diff"))
    assert has_null_check_added(files[0].added_lines) is True


# --- variable_used_before ----------------------------------------------------
def test_variable_used_before_true_when_var_in_context():
    files = parse_unified_diff(_read("lang_33.diff"))
    # "array" is in the context above the changed line in Lang 33.
    assert variable_used_before(files[0]) is True


def test_variable_used_before_false_when_var_brand_new():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=("if (brandNew == null) return;",),
        removed_lines=(),
        context_lines=("public void foo() {", "int other = 1;"),
    )
    assert variable_used_before(fd) is False


# --- fix_replaces_existing_use ----------------------------------------------
def test_fix_replaces_existing_use_true_when_var_in_removed():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=("classes[i] = array[i] == null ? null : array[i].getClass();",),
        removed_lines=("classes[i] = array[i].getClass();",),
        context_lines=(),
    )
    assert fix_replaces_existing_use(fd) is True


def test_fix_replaces_existing_use_false_when_no_removed_uses():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=("if (input == null) return Result.empty();",),
        removed_lines=(),
        context_lines=(),
    )
    assert fix_replaces_existing_use(fd) is False


def test_fix_replaces_existing_use_false_when_unrelated_removal():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=("if (input == null) return;",),
        removed_lines=("logger.info('hi');",),
        context_lines=(),
    )
    assert fix_replaces_existing_use(fd) is False


def test_fix_replaces_use_lang33_fixture():
    files = parse_unified_diff(_read("lang_33.diff"))
    assert fix_replaces_existing_use(files[0]) is True


# --- adds_new_method_declaration --------------------------------------------
def test_adds_new_method_declaration_true_for_pure_addition_of_method():
    """The canonical false positive: a fresh method with a null check at top
    and zero removed lines in the file."""
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=(
            "public Result process(Input input) {",
            "if (input == null) return Result.empty();",
            "return Result.ok(input.value());",
            "}",
        ),
        removed_lines=(),
        context_lines=(),
    )
    assert adds_new_method_declaration(fd) is True


def test_adds_new_method_declaration_true_for_new_class():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=(
            "public class FooHelper {",
            "if (x == null) return;",
            "}",
        ),
        removed_lines=(),
        context_lines=(),
    )
    assert adds_new_method_declaration(fd) is True


def test_adds_new_method_declaration_false_when_file_also_removes_lines():
    """A fix that adds a helper method while also removing code is a refactor
    + fix, not a pure addition. Penalty must NOT fire."""
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=(
            "private void newHelper(Node n) {",
            "if (n == null) return;",
            "n.process();",
            "}",
        ),
        removed_lines=("oldInlineCall(n);",),
        context_lines=(),
    )
    assert adds_new_method_declaration(fd) is False


def test_adds_new_method_declaration_false_when_only_modifying_body():
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=("if (x == null) return null;",),
        removed_lines=("// stub",),
        context_lines=("public void existingMethod() {",),
    )
    assert adds_new_method_declaration(fd) is False


def test_adds_new_method_declaration_false_when_method_moved():
    """A method present in both added and removed lines is a move (refactor)."""
    signature = "public Result existing(Input input) {"
    fd = FileDiff(
        path="Foo.java",
        patch="",
        added_lines=(signature, "if (input == null) return null;", "}"),
        removed_lines=(signature, "// old body", "}"),
        context_lines=(),
    )
    assert adds_new_method_declaration(fd) is False


def test_adds_new_method_declaration_false_on_lang33_fixture():
    """Lang 33 is a one-line fix inside an existing method, never introduces
    a new declaration. This test guards against the regex incorrectly
    matching ordinary code lines."""
    files = parse_unified_diff(_read("lang_33.diff"))
    assert adds_new_method_declaration(files[0]) is False


# --- is_bugfix_message -------------------------------------------------------
@pytest.mark.parametrize(
    "msg,expected",
    [
        ("Fix NPE in toClass when array element is null", True),
        ("Avoid NullPointerException when value missing", True),
        ("handle null input properly", True),
        ("Add new feature for chart rendering", False),
        ("Refactor utility class", False),
        ("", False),
    ],
)
def test_is_bugfix_message(msg: str, expected: bool):
    assert is_bugfix_message(msg) is expected


# --- size / test-only --------------------------------------------------------
def test_diff_size_lines_counts_added_and_removed():
    files = parse_unified_diff(_read("lang_33.diff"))
    size = diff_size_lines(files)
    assert size >= 2  # 1 added + 1 removed minimum


def test_touches_test_files_only_true_for_test_path():
    fd = FileDiff(path="src/test/FooTest.java", patch="", added_lines=(), removed_lines=(), context_lines=())
    assert touches_test_files_only((fd,)) is True


def test_touches_test_files_only_false_when_mixed():
    a = FileDiff(path="src/test/FooTest.java", patch="", added_lines=(), removed_lines=(), context_lines=())
    b = FileDiff(path="src/main/Foo.java", patch="", added_lines=(), removed_lines=(), context_lines=())
    assert touches_test_files_only((a, b)) is False


def test_touches_test_files_only_false_when_no_files():
    assert touches_test_files_only(()) is False


# --- extract_evidence integration -------------------------------------------
def test_extract_evidence_for_lang33_like_commit():
    files = parse_unified_diff(_read("lang_33.diff"))
    commit = _make_commit("LANG-747 fix NPE in ClassUtils.toClass for null elements", files)
    ev = extract_evidence(commit)
    assert ev.has_null_check_added is True
    assert ev.null_check_construct is NullCheckKind.TERNARY
    assert ev.fix_replaces_existing_use is True
    assert ev.var_was_used_before is True
    assert ev.adds_new_method_declaration is False
    assert ev.is_likely_bugfix is True
    assert ev.touches_test_files_only is False
    assert ev.diff_size_lines >= 2


def test_classify_line_recognises_each_construct():
    assert classify_line("if (x == null) return null;") is NullCheckKind.GUARD_RETURN
    assert classify_line(
        "if (x == null) {", neighbours=("throw new RuntimeException();",)
    ) is NullCheckKind.GUARD_THROW
    assert classify_line("if (x == null) {") is NullCheckKind.GUARD_BLOCK
    assert classify_line("y = x == null ? null : x.f();") is NullCheckKind.TERNARY
    assert classify_line("Objects.requireNonNull(x);") is NullCheckKind.REQUIRE_NON_NULL
    assert classify_line("int total = a + b;") is NullCheckKind.NONE


def test_find_matches_for_lang33_returns_one_ternary_with_lineno():
    files = parse_unified_diff(_read("lang_33.diff"))
    commit = _make_commit("LANG-587 fix NPE", files)
    matches = find_matches(commit)
    assert len(matches) == 1
    m = matches[0]
    assert m.file_path.endswith("ClassUtils.java")
    assert m.construct is NullCheckKind.TERNARY
    assert m.line_number > 0
    assert "== null" in m.snippet


def test_find_matches_for_math4_returns_two_guard_returns():
    files = parse_unified_diff(_read("math_4.diff"))
    commit = _make_commit("MATH-1110 fix NPE", files)
    matches = find_matches(commit)
    assert len(matches) == 2
    assert {m.construct for m in matches} == {NullCheckKind.GUARD_RETURN}
    assert {m.file_path for m in matches} == {
        "src/main/java/org/apache/commons/math3/geometry/euclidean/threed/SubLine.java",
        "src/main/java/org/apache/commons/math3/geometry/euclidean/twod/SubLine.java",
    }


def test_find_matches_skips_test_files():
    java_main = FileDiff(
        path="src/main/java/Foo.java",
        patch="",
        added_lines=("if (x == null) return;",),
        removed_lines=(),
        context_lines=(),
        added_with_lineno=((10, "if (x == null) return;"),),
    )
    java_test = FileDiff(
        path="src/test/java/FooTest.java",
        patch="",
        added_lines=("if (x == null) return;",),
        removed_lines=(),
        context_lines=(),
        added_with_lineno=((20, "if (x == null) return;"),),
    )
    commit = _make_commit("fix npe", (java_main, java_test))
    matches = find_matches(commit)
    assert len(matches) == 1
    assert matches[0].file_path == "src/main/java/Foo.java"
    assert matches[0].line_number == 10


def test_extract_evidence_for_unrelated_commit():
    fd = FileDiff(
        path="src/main/Foo.java",
        patch="",
        added_lines=("int total = a + b;",),
        removed_lines=(),
        context_lines=("public void foo() {",),
    )
    commit = _make_commit("Add new feature", (fd,))
    ev = extract_evidence(commit)
    assert ev.has_null_check_added is False
    assert ev.null_check_construct is NullCheckKind.NONE
    assert ev.is_likely_bugfix is False
