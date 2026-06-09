"""Tests for the condBlockRetAdd pattern detector.

Covers all four canonical forms recognised by the detector, the
balanced-paren scanner used for nested method calls and multi-line
conditions, and the eliminatory rules in the scorer.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.models import Commit, FileDiff
from src.patterns.cond_block_ret_add import (
    CondBlockRetAddDetector,
    CondReturnEvidence,
    CondReturnKind,
    classify_line,
    condition_var_used_before,
    detect_cond_return_in_file,
    fix_replaces_existing_use,
)

_DETECTOR = CondBlockRetAddDetector()


def _commit(message: str, files: tuple[FileDiff, ...]) -> Commit:
    return Commit(
        sha="deadbeef" * 5,
        message=message,
        author="dev",
        date=datetime(2020, 1, 1),
        files=files,
        url="https://example/commit",
    )


def _java(
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
    context: tuple[str, ...] = (),
    path: str = "src/main/java/Foo.java",
) -> FileDiff:
    """Build a FileDiff with line numbers attached (simulated)."""
    with_lineno = tuple((10 + i, line) for i, line in enumerate(added))
    return FileDiff(
        path=path,
        patch="",
        added_lines=added,
        removed_lines=removed,
        context_lines=context,
        added_with_lineno=with_lineno,
    )


# --- classify_line: the four canonical forms --------------------------------
def test_classify_compact_one_line():
    assert classify_line("if (x == null) return null;") is CondReturnKind.COMPACT_ONE_LINE


def test_classify_compact_with_negation_and_function_call():
    assert classify_line("if (!list.isEmpty()) return list.size();") is CondReturnKind.COMPACT_ONE_LINE


def test_classify_bare_return_block():
    assert classify_line(
        "if (!removeGlobals) {",
        neighbours=("return;", "}"),
    ) is CondReturnKind.BARE_RETURN


def test_classify_return_value_block():
    assert classify_line(
        "if (n.isDelProp()) {",
        neighbours=("return true;", "}"),
    ) is CondReturnKind.RETURN_VALUE


def test_classify_return_expression_block():
    assert classify_line(
        "if (size > MAX) {",
        neighbours=("return defaultValue();", "}"),
    ) is CondReturnKind.RETURN_EXPRESSION


def test_classify_returns_none_when_no_if():
    assert classify_line("foo.bar();") is CondReturnKind.NONE
    assert classify_line("return null;") is CondReturnKind.NONE
    assert classify_line("") is CondReturnKind.NONE


def test_classify_returns_none_for_if_without_return():
    assert classify_line(
        "if (x == null) {",
        neighbours=("doSomething();", "}"),
    ) is CondReturnKind.NONE


# --- nested parens (real-world case that broke initial regex) --------------
def test_classify_handles_deeply_nested_method_calls():
    line = "if (Modifier.isAbstract(invocation.getMethod().getModifiers())) {"
    assert classify_line(line, neighbours=("return new GloballyConfiguredAnswer().answer(invocation);",)) is CondReturnKind.RETURN_EXPRESSION


def test_classify_handles_multi_line_condition():
    """The condition spans two added lines — Closure 3 in the ground truth."""
    line = "if (var != null"
    neighbours = ("&& var.getParentNode().isCatch()) {", "return true;", "}")
    assert classify_line(line, neighbours=neighbours) is CondReturnKind.RETURN_VALUE


# --- detect_cond_return_in_file ---------------------------------------------
def test_detect_in_file_picks_up_any_form():
    fd = _java(
        added=(
            "// no match here",
            "if (size > MAX) return null;",
        ),
    )
    assert detect_cond_return_in_file(fd) is CondReturnKind.COMPACT_ONE_LINE


def test_detect_in_file_returns_none_when_absent():
    fd = _java(added=("int total = a + b;", "list.add(total);"))
    assert detect_cond_return_in_file(fd) is CondReturnKind.NONE


# --- fix_replaces_existing_use ----------------------------------------------
def test_fix_replaces_use_true_when_var_in_removed():
    fd = _java(
        added=("if (list.isEmpty()) return;",),
        removed=("list.size();",),
    )
    assert fix_replaces_existing_use(fd) is True


def test_fix_replaces_use_false_when_no_removed():
    fd = _java(added=("if (input == null) return;",), removed=())
    assert fix_replaces_existing_use(fd) is False


# --- condition_var_used_before ----------------------------------------------
def test_condition_var_used_before_true_when_in_context():
    fd = _java(
        added=("if (cache.isEmpty()) return null;",),
        context=("Map<String, Object> cache = new HashMap<>();",),
    )
    assert condition_var_used_before(fd) is True


def test_condition_var_used_before_false_for_brand_new_var():
    fd = _java(
        added=("Foo brandNew = build();", "if (brandNew == null) return;"),
        context=("public void start() {",),
    )
    assert condition_var_used_before(fd) is False


# --- extract_evidence + score: integration ---------------------------------
def _evidence(form: CondReturnKind = CondReturnKind.RETURN_VALUE, **fields) -> CondReturnEvidence:
    defaults = dict(
        has_guard_added=True,
        cond_return_form=form,
        fix_replaces_existing_use=False,
        var_was_used_before=False,
        adds_new_method_declaration=False,
        is_likely_bugfix=False,
        diff_size_lines=4,
        touches_test_files_only=False,
    )
    defaults.update(fields)
    return CondReturnEvidence(**defaults)


def test_score_zero_when_no_guard_added():
    ev = _evidence(has_guard_added=False, cond_return_form=CondReturnKind.NONE)
    assert _DETECTOR.score(ev) == 0.0


def test_score_zero_when_form_is_none():
    ev = _evidence(cond_return_form=CondReturnKind.NONE)
    assert _DETECTOR.score(ev) == 0.0


def test_score_eliminatory_minimum_passes_threshold():
    """Just E1 + E2 (no other signals) must already reach >= 0.7 because the
    threshold is calibrated on these structural evidences alone."""
    ev = _evidence()
    assert _DETECTOR.score(ev) >= 0.7


def test_score_full_evidence_reaches_one():
    ev = _evidence(
        fix_replaces_existing_use=True,
        var_was_used_before=True,
        is_likely_bugfix=True,
    )
    assert _DETECTOR.score(ev) == pytest.approx(1.0)


def test_score_does_not_apply_new_method_penalty():
    """condBlockRetAdd intentionally drops the new-method penalty from
    missNullCheckP v0.2.0. Fixes that add a guard at the top of a freshly
    declared override (Lang 23, Lang 64) must not be penalised."""
    with_penalty_field = _evidence(adds_new_method_declaration=True)
    without = _evidence(adds_new_method_declaration=False)
    assert _DETECTOR.score(with_penalty_field) == _DETECTOR.score(without)


# --- end-to-end: extract evidence + find matches ----------------------------
def test_extract_evidence_for_canonical_fix():
    fd = _java(
        added=(
            "if (!removeGlobals) {",
            "return;",
            "}",
        ),
        context=("private void process() {",),
    )
    commit = _commit("Fix: skip processing when globals are kept", (fd,))
    ev = _DETECTOR.extract_evidence(commit)
    assert ev.has_guard_added is True
    assert ev.cond_return_form is CondReturnKind.BARE_RETURN
    assert _DETECTOR.score(ev) >= 0.7


def test_find_matches_reports_line_numbers():
    fd = _java(
        added=("if (foo == null) return null;",),
    )
    commit = _commit("Fix NPE in foo handler", (fd,))
    matches = _DETECTOR.find_matches(commit)
    assert len(matches) == 1
    assert matches[0].line_number == 10
    assert matches[0].construct is CondReturnKind.COMPACT_ONE_LINE


def test_find_matches_skips_test_files():
    fd_main = _java(
        added=("if (x == null) return;",),
        path="src/main/java/Foo.java",
    )
    fd_test = _java(
        added=("if (x == null) return;",),
        path="src/test/java/FooTest.java",
    )
    commit = _commit("fix", (fd_main, fd_test))
    matches = _DETECTOR.find_matches(commit)
    assert len(matches) == 1
    assert matches[0].file_path == "src/main/java/Foo.java"
