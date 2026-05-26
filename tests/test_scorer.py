"""Tests for the scorer: weight math and confidence thresholds."""
from __future__ import annotations

import pytest

from src import config
from src.models import Evidence, NullCheckKind
from src.scorer import confidence_level, score


def _ev(
    *,
    has_null: bool = True,
    kind: NullCheckKind = NullCheckKind.GUARD_RETURN,
    replaces_use: bool = True,
    used_before: bool = True,
    new_method: bool = False,
    bugfix: bool = True,
    size: int = 10,
    tests_only: bool = False,
) -> Evidence:
    return Evidence(
        has_null_check_added=has_null,
        null_check_construct=kind,
        fix_replaces_existing_use=replaces_use,
        var_was_used_before=used_before,
        adds_new_method_declaration=new_method,
        is_likely_bugfix=bugfix,
        diff_size_lines=size,
        touches_test_files_only=tests_only,
    )


def test_score_zero_when_no_null_check():
    assert score(_ev(has_null=False, kind=NullCheckKind.NONE)) == 0.0


def test_score_full_evidence_reaches_one():
    assert score(_ev()) == pytest.approx(1.0)


def test_score_zero_when_construct_is_none_even_with_null_flag():
    # Eliminatory rule: a null check without a recognised canonical construct
    # is treated as no-match, regardless of the descriptive evidences.
    assert score(_ev(kind=NullCheckKind.NONE)) == 0.0


def test_score_null_check_plus_canonical_only():
    s = score(_ev(replaces_use=False, used_before=False, bugfix=False))
    assert s == pytest.approx(config.W_NULL_CHECK_ADDED + config.W_CANONICAL_CONSTRUCT)


def test_score_canonical_plus_var_used_before():
    s = score(_ev(replaces_use=False, bugfix=False))
    expected = (
        config.W_NULL_CHECK_ADDED
        + config.W_CANONICAL_CONSTRUCT
        + config.W_VAR_USED_BEFORE
    )
    assert s == pytest.approx(expected)


def test_score_fix_replaces_use_adds_weight():
    """When the fix replaces an existing use, score gets ``W_FIX_REPLACES_USE``."""
    s_with = score(_ev(used_before=False, bugfix=False))           # replaces_use=True
    s_without = score(_ev(replaces_use=False, used_before=False, bugfix=False))
    assert s_with - s_without == pytest.approx(config.W_FIX_REPLACES_USE)


def test_score_penalty_when_new_method_added():
    """Adding a new method should subtract ``PENALTY_ADDS_NEW_METHOD``."""
    s_clean = score(_ev())                # all positives, no penalty
    s_penalised = score(_ev(new_method=True))
    assert s_clean - s_penalised == pytest.approx(config.PENALTY_ADDS_NEW_METHOD)


def test_score_clamped_to_zero_when_only_new_method_signal():
    """Adding a new method with only the eliminatory evidences must not go negative."""
    s = score(_ev(replaces_use=False, used_before=False, bugfix=False, new_method=True))
    expected = (
        config.W_NULL_CHECK_ADDED
        + config.W_CANONICAL_CONSTRUCT
        - config.PENALTY_ADDS_NEW_METHOD
    )
    assert s == pytest.approx(max(0.0, expected))
    assert s >= 0.0


def test_score_new_method_pushes_weak_candidate_below_threshold():
    """A candidate that only has E1+E2+E4 falls below 0.7 once new method fires.

    This is the exact scenario v0.2.0 is designed to remove: a commit that
    adds a null check inside a brand-new method, has no replaced use, no
    prior variable, but happens to have bugfix-style language in the
    message.
    """
    s = score(_ev(
        replaces_use=False, used_before=False, bugfix=True, new_method=True,
    ))
    assert s < config.DEFAULT_MIN_SCORE


def test_score_above_threshold_for_strong_evidence():
    assert score(_ev()) >= config.DEFAULT_MIN_SCORE


def test_confidence_low_below_05():
    s = config.SCORE_LOW_MAX - 0.01
    assert confidence_level(s, _ev()) == "low"


def test_confidence_medium_between_05_and_07():
    assert confidence_level(0.6, _ev()) == "medium"


def test_confidence_high_for_clean_strong_match():
    assert confidence_level(0.85, _ev(size=20)) == "high"


def test_confidence_medium_when_diff_is_huge():
    assert confidence_level(0.85, _ev(size=config.LARGE_DIFF_LINES + 1)) == "medium"


def test_confidence_medium_when_only_tests_touched():
    assert confidence_level(0.85, _ev(tests_only=True)) == "medium"
