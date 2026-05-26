"""Structured parsing of unified diffs.

Wraps the ``unidiff`` library to expose a small, project-specific surface:
per-file added, removed, and context lines, normalized so downstream feature
extraction does not have to worry about whitespace or pure-syntax noise such
as braces and comment-only lines.
"""
from __future__ import annotations

from typing import Iterable

from unidiff import PatchSet

from .models import FileDiff


def parse_unified_diff(patch_text: str) -> tuple[FileDiff, ...]:
    """Parse a unified diff containing one or more files.

    GitHub's commit ``patch`` field comes as a single string with multiple
    file headers. We return one :class:`FileDiff` per file, with whitespace-
    stripped lines and noise lines removed.
    """
    if not patch_text.strip():
        return ()
    patches = PatchSet.from_string(_normalize_line_endings(patch_text))
    return tuple(_to_file_diff(p) for p in patches)


def parse_file_patch(patch_text: str, file_path: str) -> FileDiff:
    """Parse a patch that already targets a single file (GitHub `files[].patch`).

    GitHub returns per-file patches without the ``--- a/...`` header, so we
    prepend a synthetic header before delegating to ``unidiff``.
    """
    header = f"--- a/{file_path}\n+++ b/{file_path}\n"
    body = patch_text if patch_text.startswith("@@") else patch_text.lstrip("\n")
    patches = PatchSet.from_string(_normalize_line_endings(header + body))
    if not patches:
        return FileDiff(path=file_path, patch=patch_text, added_lines=(), removed_lines=(), context_lines=())
    return _to_file_diff(patches[0], override_path=file_path, raw_patch=patch_text)


def normalize_line(line: str) -> str:
    """Strip whitespace and return the line content."""
    return line.strip()


def is_noise_line(line: str) -> bool:
    """Return True for lines we do not want to feed into feature extraction.

    Noise covers empty lines, lone braces, lines that are entirely a Java
    block-comment marker, and single-line comments. These contribute nothing
    to a structural detection of added null checks.
    """
    s = line.strip()
    if not s:
        return True
    if s in {"{", "}", "};", "});"}:
        return True
    if s.startswith("//"):
        return True
    if s.startswith("*") or s.startswith("/*") or s.endswith("*/"):
        return True
    return False


def _filter_noise(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(normalize_line(l) for l in lines if not is_noise_line(l))


def _normalize_line_endings(text: str) -> str:
    """Normalise diff text so unidiff parses cleanly.

    - Collapses CRLF/CR line endings to LF.
    - Strips ``\\ No newline at end of file`` metadata markers that GitHub
      includes when a file has no trailing newline; ``unidiff`` does not
      tolerate them and raises ``UnidiffParseError``.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(
        line for line in normalized.split("\n") if not line.startswith("\\ ")
    )


def _to_file_diff(patched_file, override_path: str | None = None, raw_patch: str | None = None) -> FileDiff:
    added: list[str] = []
    added_with_lineno: list[tuple[int, str]] = []
    removed: list[str] = []
    context: list[str] = []
    for hunk in patched_file:
        for line in hunk:
            if line.is_added:
                added.append(line.value)
                if line.target_line_no is not None:
                    added_with_lineno.append((line.target_line_no, line.value))
            elif line.is_removed:
                removed.append(line.value)
            elif line.is_context:
                context.append(line.value)
    path = override_path or patched_file.path
    patch_str = raw_patch if raw_patch is not None else str(patched_file)
    return FileDiff(
        path=path,
        patch=patch_str,
        added_lines=_filter_noise(added),
        removed_lines=_filter_noise(removed),
        context_lines=_filter_noise(context),
        added_with_lineno=tuple(
            (lineno, normalize_line(text))
            for lineno, text in added_with_lineno
            if not is_noise_line(text)
        ),
    )
