"""Base interfaces for pattern detectors.

A *pattern detector* encapsulates everything needed to recognise one
Defects4J repair pattern in a commit: the structural mask (regex), the
evidence model, the scoring weights, and the per-occurrence match builder.

The orchestration in :mod:`src.detector` knows nothing about specific
patterns — it just iterates commits and asks each registered detector
whether the commit matches.

This separation is what makes the project extensible: adding a new pattern
means writing one module under ``src/patterns/`` and registering it in
``src/patterns/__init__.py``. Nothing in the pipeline (GitHub client, diff
parser, CLIs, report builder) needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..models import Commit, ConfidenceLevel, Match


@dataclass(frozen=True, kw_only=True)
class BaseEvidence:
    """Evidences shared by every pattern detector.

    Only truly transversal fields live here. The pattern-specific "match flag"
    (e.g. ``has_null_check_added`` vs ``has_guard_added``) belongs to the
    subclass so each pattern keeps natural, domain-specific names. The
    ``kw_only=True`` flag avoids ordering issues when subclasses add their own
    required fields without defaults.
    """

    fix_replaces_existing_use: bool
    var_was_used_before: bool
    adds_new_method_declaration: bool
    is_likely_bugfix: bool
    diff_size_lines: int
    touches_test_files_only: bool


class PatternDetector(ABC):
    """Abstract contract every pattern detector must implement.

    Concrete subclasses live under ``src/patterns/`` and are registered
    in ``src/patterns/__init__.py``. The orchestration code
    (``src/detector.py``) depends only on this interface.
    """

    name: ClassVar[str]
    """Short identifier used in CLI flags and reports (e.g. ``missNullCheckP``)."""

    description: ClassVar[str]
    """One-line human-friendly description for menus and reports."""

    @abstractmethod
    def extract_evidence(self, commit: Commit) -> BaseEvidence:
        """Build the evidence record for one commit (no scoring decision yet)."""

    @abstractmethod
    def score(self, evidence: BaseEvidence) -> float:
        """Combine evidences into a 0.0–1.0 score."""

    @abstractmethod
    def confidence_level(self, score_value: float, evidence: BaseEvidence) -> ConfidenceLevel:
        """Map score + penalties to ``low`` / ``medium`` / ``high``."""

    @abstractmethod
    def find_matches(self, commit: Commit) -> tuple[Match, ...]:
        """Return every location in the commit where the pattern fired."""
