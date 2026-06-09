"""CLI: evaluate the detector and baseline against the Defects4J ground truth.

For each repo in the ground truth, walks its commit history (paginated all
the way) until every ground-truth fix-SHA has been encountered or the history
ends. Then aggregates Precision / Recall / F1 across repos and produces a
markdown report.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import load_dotenv  # noqa: E402

load_dotenv()

from src import config  # noqa: E402
from src.baseline import baseline_classify  # noqa: E402
from src.evaluation import Metrics, evaluate, render_report  # noqa: E402
from src.github_client import GitHubClient  # noqa: E402
from src.models import CommitCandidate  # noqa: E402
from src.patterns.miss_null_check_p import MissNullCheckPDetector  # noqa: E402

_DETECTOR = MissNullCheckPDetector()
extract_evidence = _DETECTOR.extract_evidence
score = _DETECTOR.score
confidence_level = _DETECTOR.confidence_level


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate the detector against ground truth.")
    p.add_argument("--ground-truth", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path, help="Markdown report path")
    p.add_argument("--min-score", type=float, default=config.DEFAULT_MIN_SCORE)
    p.add_argument(
        "--max-commits-per-repo",
        type=int,
        default=None,
        help="Hard cap on commits inspected per repo (defaults to unlimited).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GITHUB_TOKEN not set in environment", file=sys.stderr)
        return 2
    truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    by_repo: dict[str, set[str]] = defaultdict(set)
    for entry in truth:
        by_repo[entry["github_repo"]].add(entry["fix_commit_sha"])
    truth_shas = {sha for shas in by_repo.values() for sha in shas}

    client = GitHubClient(token=token)
    detector_candidates: list[CommitCandidate] = []
    baseline_predicted: set[str] = set()

    for repo, shas in by_repo.items():
        print(f"-- scanning {repo} (target SHAs: {len(shas)})", file=sys.stderr)
        inspected = 0
        for commit in client.list_commits(repo, limit=args.max_commits_per_repo):
            inspected += 1
            if baseline_classify(commit):
                baseline_predicted.add(commit.sha)
            ev = extract_evidence(commit)
            s = score(ev)
            if s >= args.min_score:
                detector_candidates.append(
                    CommitCandidate(
                        commit=commit,
                        score=s,
                        confidence=confidence_level(s, ev),
                        evidence=ev,
                    )
                )
        print(f"   inspected {inspected} commits", file=sys.stderr)

    detector_predicted = {c.commit.sha for c in detector_candidates}
    detector_metrics: Metrics = evaluate(detector_predicted, truth_shas)
    baseline_metrics: Metrics = evaluate(baseline_predicted, truth_shas)
    report = render_report(detector_metrics, baseline_metrics, detector_candidates, truth_shas)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
