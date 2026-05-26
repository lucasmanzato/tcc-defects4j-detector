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
    forces the score to zero, regardless of the other evidences.

    Positive confirmations add to the score:

    - ``fix_replaces_existing_use`` (0.15): the protected variable also
      appears in removed lines — strong fix signal.
    - ``var_was_used_before`` (0.05): protected variable appears in context.
    - ``is_likely_bugfix`` (0.05): bugfix-style commit message.

    A negative signal subtracts after the positives:

    - ``adds_new_method_declaration`` (-0.20): the commit introduces a new
      method/type alongside the null check, suggesting defensive scaffolding
      in fresh code rather than a fix to existing logic.

    The final value is clamped to the [0.0, 1.0] interval.
    """
    if not evidence.has_null_check_added:
        return 0.0
    if evidence.null_check_construct not in _CANONICAL_KINDS:
        return 0.0

    total = config.W_NULL_CHECK_ADDED + config.W_CANONICAL_CONSTRUCT
    if evidence.fix_replaces_existing_use:
        total += config.W_FIX_REPLACES_USE
    if evidence.var_was_used_before:
        total += config.W_VAR_USED_BEFORE
    if evidence.is_likely_bugfix:
        total += config.W_BUGFIX_MESSAGE
    if evidence.adds_new_method_declaration:
        total -= config.PENALTY_ADDS_NEW_METHOD
    total = max(0.0, min(1.0, total))
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
