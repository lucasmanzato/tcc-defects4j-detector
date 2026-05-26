"""Evidence-to-score combination and confidence labeling.

The score is a linear combination of weights defined in :mod:`src.config`,
each weight applied to a single boolean evidence. Keeping the formula linear
and the weights inspectable preserves the deterministic, interpretable
character that the project requires.
"""
from __future__ import annotations

from . import config
from .models import ConfidenceLevel, Evidence, NullCheckKind

_CANONICAL_KINDS: frozenset[NullCheckKind] = frozenset(
    {
        NullCheckKind.GUARD_RETURN,
        NullCheckKind.GUARD_THROW,
        NullCheckKind.GUARD_BLOCK,
        NullCheckKind.REQUIRE_NON_NULL,
        NullCheckKind.TERNARY,
    }
)


def score(evidence: Evidence) -> float:
    """Combine evidences into a 0.0-1.0 score.

    Two structural evidences are eliminatory: a commit must add a null check
    AND the check must match a canonical construct. Either being absent
    forces the score to zero, regardless of the other evidences. The
    remaining two evidences (variable previously used, bugfix-style message)
    are descriptive confirmations and only adjust the score upward.
    """
    if not evidence.has_null_check_added:
        return 0.0
    if evidence.null_check_construct not in _CANONICAL_KINDS:
        return 0.0

    total = config.W_NULL_CHECK_ADDED + config.W_CANONICAL_CONSTRUCT
    if evidence.var_was_used_before:
        total += config.W_VAR_USED_BEFORE
    if evidence.is_likely_bugfix:
        total += config.W_BUGFIX_MESSAGE
    return round(total, 4)


def confidence_level(commit_score: float, evidence: Evidence) -> ConfidenceLevel:
    """Map a score plus evidence-based penalties to a confidence label.

    A high raw score is downgraded to ``medium`` when the diff is very large
    (likely refactor noise) or when the change touches only test files.
    """
    if commit_score < config.SCORE_LOW_MAX:
        return "low"
    if commit_score < config.SCORE_MEDIUM_MAX:
        return "medium"
    if evidence.diff_size_lines > config.LARGE_DIFF_LINES:
        return "medium"
    if evidence.touches_test_files_only:
        return "medium"
    return "high"
