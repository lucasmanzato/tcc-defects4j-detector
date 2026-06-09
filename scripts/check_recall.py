"""Targeted recall test against the Defects4J ground truth.

For each entry in ``data/defects4j_ground_truth.json``, fetches the exact fix
commit by SHA and runs the detector pipeline. Reports per-bug score and
confidence, plus aggregate recall for both the detector and the baseline.

This script intentionally does *not* measure precision: it walks only the
known positives. Use ``run_evaluation.py`` for the full Precision/Recall/F1
sweep over a repo's commit history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import load_dotenv  # noqa: E402

load_dotenv()

from src import config  # noqa: E402
from src.baseline import baseline_classify  # noqa: E402
from src.github_client import GitHubClient, GitHubError  # noqa: E402
from src.patterns import available_patterns, get_detector  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a targeted recall test on the ground truth.")
    p.add_argument("--ground-truth", type=Path, default=Path("data/defects4j_ground_truth.json"))
    p.add_argument(
        "--pattern",
        default="missNullCheckP",
        choices=available_patterns(),
        help="Which pattern detector to validate.",
    )
    p.add_argument("--min-score", type=float, default=config.DEFAULT_MIN_SCORE)
    p.add_argument("--output", type=Path, default=None, help="Optional Markdown output path")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GITHUB_TOKEN not set in environment", file=sys.stderr)
        return 2
    truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    client = GitHubClient(token=token)
    detector = get_detector(args.pattern)

    rows: list[dict] = []
    missing: list[dict] = []
    detected_count = 0
    baseline_count = 0
    for entry in truth:
        try:
            commit = client.get_commit(entry["github_repo"], entry["fix_commit_sha"])
        except GitHubError as exc:
            missing.append({**entry, "error": str(exc).split(":", 2)[-1].strip()[:120]})
            continue
        evidence = detector.extract_evidence(commit)
        s = detector.score(evidence)
        confidence = detector.confidence_level(s, evidence)
        detector_hit = s >= args.min_score
        baseline_hit = baseline_classify(commit)
        if detector_hit:
            detected_count += 1
        if baseline_hit:
            baseline_count += 1
        rows.append(
            {
                "project": entry["project"],
                "bug_id": entry["bug_id"],
                "sha": commit.sha[:10],
                "score": s,
                "confidence": confidence,
                "construct": _construct_label(evidence),
                "var_used_before": evidence.var_was_used_before,
                "bugfix_msg": evidence.is_likely_bugfix,
                "detector_hit": detector_hit,
                "baseline_hit": baseline_hit,
                "message": commit.message.splitlines()[0][:80] if commit.message else "",
            }
        )

    n = len(rows)
    detector_recall = detected_count / n if n else 0.0
    baseline_recall = baseline_count / n if n else 0.0

    report = _render(rows, detector_recall, baseline_recall, args.min_score, missing)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report)
    return 0


def _construct_label(evidence) -> str:
    """Return the human-readable form for whichever construct field exists."""
    for attr in ("null_check_construct", "cond_return_form"):
        value = getattr(evidence, attr, None)
        if value is not None:
            return value.value if hasattr(value, "value") else str(value)
    return "n/a"


def _render(
    rows: list[dict],
    detector_recall: float,
    baseline_recall: float,
    min_score: float,
    missing: list[dict],
) -> str:
    lines: list[str] = []
    lines.append("# Targeted recall on Defects4J ground truth\n")
    total = len(rows) + len(missing)
    lines.append(
        f"- Threshold: `score >= {min_score}` "
        f"| Reachable on GitHub: {len(rows)}/{total} "
        f"| Missing SHAs: {len(missing)}\n"
    )
    lines.append("## Summary\n")
    lines.append("| Approach | Recall |")
    lines.append("|----------|--------|")
    lines.append(f"| Detector | {detector_recall:.2f} ({sum(1 for r in rows if r['detector_hit'])}/{len(rows)}) |")
    lines.append(f"| Baseline (keyword) | {baseline_recall:.2f} ({sum(1 for r in rows if r['baseline_hit'])}/{len(rows)}) |")
    lines.append("")
    if missing:
        lines.append("## Missing on GitHub (not counted in recall)\n")
        lines.append("| Project | Bug | SHA | Repo | Error |")
        lines.append("|---------|-----|-----|------|-------|")
        for m in missing:
            lines.append(
                f"| {m['project']} | {m['bug_id']} | `{m['fix_commit_sha'][:10]}` "
                f"| {m['github_repo']} | {m.get('error','')} |"
            )
        lines.append("")
    lines.append("## Per-bug breakdown\n")
    lines.append("| Project | Bug | SHA | Score | Conf | Construct | VarPrior | BugMsg | Det | Base | Msg |")
    lines.append("|---------|-----|-----|-------|------|-----------|----------|--------|-----|------|-----|")
    for r in rows:
        det = "yes" if r["detector_hit"] else "NO"
        base = "yes" if r["baseline_hit"] else "NO"
        var = "Y" if r["var_used_before"] else "n"
        bug = "Y" if r["bugfix_msg"] else "n"
        lines.append(
            f"| {r['project']} | {r['bug_id']} | `{r['sha']}` | {r['score']:.2f} | "
            f"{r['confidence']} | {r['construct']} | {var} | {bug} | {det} | {base} | {r['message'][:50]} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
