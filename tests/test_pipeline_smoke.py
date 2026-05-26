"""End-to-end smoke test using the Lang 33 fixture as a synthetic Commit."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.diff_parser import parse_unified_diff
from src.features import extract_evidence
from src.models import Commit, CommitCandidate
from src.scorer import confidence_level, score


def test_lang33_pipeline_yields_high_score_candidate():
    diff = (Path(__file__).parent / "fixtures" / "lang_33.diff").read_text(encoding="utf-8")
    files = parse_unified_diff(diff)
    commit = Commit(
        sha="0603aef594fa60126c2d45f2ab164eee39f7b44c",
        message="LANG-747: ClassUtils.toClass throws NPE for arrays containing null",
        author="Apache Commons developer",
        date=datetime(2011, 9, 5, tzinfo=timezone.utc),
        files=files,
        url="https://github.com/apache/commons-lang/commit/0603aef594fa60126c2d45f2ab164eee39f7b44c",
    )
    evidence = extract_evidence(commit)
    s = score(evidence)
    confidence = confidence_level(s, evidence)
    candidate = CommitCandidate(commit=commit, score=s, confidence=confidence, evidence=evidence)

    assert candidate.evidence.has_null_check_added
    assert candidate.evidence.is_likely_bugfix
    assert candidate.evidence.var_was_used_before
    assert candidate.score >= 0.7  # project requires high-similarity threshold
    assert candidate.confidence == "high"
