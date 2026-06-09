"""Registry of pattern detectors available to the orchestration layer.

Adding a new pattern is a 2-step process:

1. Create ``src/patterns/<your_pattern>.py`` exporting a class that
   inherits :class:`PatternDetector`.
2. Import and register the class in :data:`PATTERNS` below.

Nothing else in the codebase needs to change.
"""
from __future__ import annotations

from .base import BaseEvidence, PatternDetector
from .cond_block_ret_add import CondBlockRetAddDetector
from .miss_null_check_p import MissNullCheckPDetector

# Registry: maps the canonical pattern name to a singleton detector instance.
# CLI flags and reports use the names exactly as written here.
PATTERNS: dict[str, PatternDetector] = {
    MissNullCheckPDetector.name: MissNullCheckPDetector(),
    CondBlockRetAddDetector.name: CondBlockRetAddDetector(),
}


def get_detector(name: str) -> PatternDetector:
    """Return the detector registered under ``name``.

    Raises :class:`KeyError` with the list of valid names if not registered.
    """
    if name not in PATTERNS:
        raise KeyError(
            f"Unknown pattern: {name!r}. "
            f"Available: {', '.join(sorted(PATTERNS))}"
        )
    return PATTERNS[name]


def available_patterns() -> tuple[str, ...]:
    return tuple(PATTERNS.keys())


__all__ = [
    "BaseEvidence",
    "PatternDetector",
    "PATTERNS",
    "get_detector",
    "available_patterns",
]
