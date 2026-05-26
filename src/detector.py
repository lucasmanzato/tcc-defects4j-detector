"""Pipeline orchestration: turn a repo into a ranked list of candidates."""
from __future__ import annotations

from typing import Iterable

from . import config
from .features import extract_evidence, find_matches
from .github_client import GitHubClient
from .logger import get_logger
from .models import Commit, CommitCandidate
from .scorer import confidence_level, score

log = get_logger()


def detect(
    repo: str,
    client: GitHubClient,
    limit: int | None = None,
    min_score: float = config.DEFAULT_MIN_SCORE,
) -> list[CommitCandidate]:
    """Walk a repo's commit history and return candidates above ``min_score``.

    Results are sorted by descending score, then by descending commit date so
    ties favour the most recent fix.
    """
    return rank(client.list_commits(repo, limit=limit), min_score=min_score)


def rank(commits: Iterable[Commit], min_score: float) -> list[CommitCandidate]:
    """Score each commit and keep those above the threshold, sorted desc."""
    candidates: list[CommitCandidate] = []
    inspected = 0
    notified_start = False
    for commit in commits:
        if not notified_start:
            log.info(
                f"Comparando assinatura estrutural · limite mínimo {min_score}"
            )
            notified_start = True
        inspected += 1
        evidence = extract_evidence(commit)
        s = score(evidence)
        if inspected % 25 == 0:
            log.info(
                f"Progresso: {inspected} commits analisados · "
                f"{len(candidates)} candidatos até agora"
            )
        if s < min_score:
            continue
        matches = find_matches(commit)
        log.info(
            f"Candidato: {commit.sha[:10]} score={s:.2f} "
            f"({len(matches)} match{'es' if len(matches) != 1 else ''}) — "
            f"{commit.message.splitlines()[0][:60] if commit.message else ''}"
        )
        candidates.append(
            CommitCandidate(
                commit=commit,
                score=s,
                confidence=confidence_level(s, evidence),
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
