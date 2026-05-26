"""Tests for diff_parser using real Defects4J diffs as fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.diff_parser import (
    is_noise_line,
    normalize_line,
    parse_file_patch,
    parse_unified_diff,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_lang33_single_file_with_ternary_null_check():
    files = parse_unified_diff(_read("lang_33.diff"))
    assert len(files) == 1
    fd = files[0]
    assert fd.path.endswith("ClassUtils.java")
    assert any("== null ?" in l or "== null?" in l or "== null " in l for l in fd.added_lines), fd.added_lines
    # The original line without null check was removed.
    assert any("array[i].getClass()" in l for l in fd.removed_lines)


def test_parse_math4_multiple_files_each_with_guard_return():
    files = parse_unified_diff(_read("math_4.diff"))
    assert len(files) == 2
    for fd in files:
        joined = " ".join(fd.added_lines)
        assert "== null" in joined
        assert "return null" in joined


def test_parse_mockito38_ternary():
    files = parse_unified_diff(_read("mockito_38.diff"))
    assert len(files) == 1
    joined = " ".join(files[0].added_lines)
    assert "== null" in joined and "?" in joined


def test_empty_patch_returns_empty_tuple():
    assert parse_unified_diff("") == ()
    assert parse_unified_diff("   \n  ") == ()


def test_parse_file_patch_synthesises_headers():
    patch = (
        "@@ -1,3 +1,4 @@\n"
        " a\n"
        "-b\n"
        "+if (x == null) return;\n"
        "+b\n"
        " c\n"
    )
    fd = parse_file_patch(patch, "Foo.java")
    assert fd.path == "Foo.java"
    assert "if (x == null) return;" in fd.added_lines
    assert "b" in fd.removed_lines


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", True),
        ("    ", True),
        ("{", True),
        ("}", True),
        ("// comment", True),
        ("/* block start", True),
        (" * javadoc line", True),
        ("end */", True),
        ("if (x == null) return null;", False),
        ("Objects.requireNonNull(x);", False),
    ],
)
def test_is_noise_line(raw: str, expected: bool):
    assert is_noise_line(raw) is expected


def test_normalize_line_strips_whitespace():
    assert normalize_line("    foo();   ") == "foo();"
