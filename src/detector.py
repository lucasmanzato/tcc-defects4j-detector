"""Pipeline orchestration: turn a repo into a ranked list of candidates.

The detector is *pattern-agnostic*: it accepts any :class:`PatternDetector`
and delegates evidence extraction, scoring, and match finding to it. New
patterns plug in by registering themselves in :mod:`src.patterns`.
"""
from __future__ import annotations

from typing import Iterable

from . import config
from .github_client import GitHubClient
from .logger import get_logger
from .models import Commit, CommitCandidate
from .patterns import PatternDetector, get_detector
from .patterns.miss_null_check_p import MissNullCheckPDetector

log = get_logger()

# Default detector preserved for backward compatibility with v0.1/v0.2 callers.
_DEFAULT_DETECTOR: PatternDetector = MissNullCheckPDetector()


def detect(
    repo: str,
    client: GitHubClient,
    limit: int | None = None,
    min_score: float = config.DEFAULT_MIN_SCORE,
    pattern: PatternDetector | str | None = None,
) -> list[CommitCandidate]:
    """Walk a repo's commit history and return candidates above ``min_score``.

    ``pattern`` accepts either a :class:`PatternDetector` instance, a name
    string (e.g. ``"missNullCheckP"``), or ``None`` (uses
    ``missNullCheckP`` for backward compatibility).
    """
    detector = _resolve_pattern(pattern)
    return rank(
        client.list_commits(repo, limit=limit),
        detector=detector,
        min_score=min_score,
    )


def rank(
    commits: Iterable[Commit],
    detector: PatternDetector | str | None = None,
    min_score: float = config.DEFAULT_MIN_SCORE,
) -> list[CommitCandidate]:
    """Score each commit with ``detector`` and keep those above the threshold."""
    detector = _resolve_pattern(detector)
    candidates: list[CommitCandidate] = []
    inspected = 0
    notified_start = False
    for commit in commits:
        if not notified_start:
            log.info(
                f"Comparando assinatura estrutural · padrão {detector.name} · "
                f"limite mínimo {min_score}"
            )
            notified_start = True
        inspected += 1
        evidence = detector.extract_evidence(commit)
        s = detector.score(evidence)
        if inspected % 25 == 0:
            log.info(
                f"Progresso: {inspected} commits analisados · "
                f"{len(candidates)} candidatos até agora"
            )
        if s < min_score:
            continue
        matches = detector.find_matches(commit)
        log.info(
            f"Candidato: {commit.sha[:10]} score={s:.2f} "
            f"({len(matches)} match{'es' if len(matches) != 1 else ''}) — "
            f"{commit.message.splitlines()[0][:60] if commit.message else ''}"
        )
        candidates.append(
            CommitCandidate(
                commit=commit,
                score=s,
                confidence=detector.confidence_level(s, evidence),
                evidence=evidence,
                matches=matches,
            )
        )
    candidates.sort(key=lambda c: (c.score, c.commit.date), reverse=True)
    log.info(
        f"Análise concluída · {inspected} commits inspecionados · "
        f"{len(candidates)} flagrados"
    )
    return candidates


def _resolve_pattern(value: PatternDetector | str | None) -> PatternDetector:
    if value is None:
        return _DEFAULT_DETECTOR
    if isinstance(value, str):
        return get_detector(value)
    return value
