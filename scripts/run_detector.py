"""CLI: run the missNullCheckP detector against a single GitHub repo.

Reads ``GITHUB_TOKEN`` from the environment, walks the repo's commit history,
and writes a JSON file with the ranked candidates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import load_dotenv  # noqa: E402

load_dotenv()

from src import config  # noqa: E402
from src.detector import detect  # noqa: E402
from src.github_client import GitHubClient  # noqa: E402
from src.models import CommitCandidate  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect missNullCheckP commits in a repo.")
    p.add_argument("--repo", required=True, help="GitHub repo as owner/name (e.g. apache/commons-lang)")
    p.add_argument("--pattern", default="missNullCheckP", help="Repair pattern label (informational)")
    p.add_argument("--limit", type=int, default=None, help="Optional commit cap (debugging)")
    p.add_argument("--min-score", type=float, default=config.DEFAULT_MIN_SCORE)
    p.add_argument("--output", required=True, type=Path, help="Output JSON path")
    return p.parse_args()


def candidate_to_dict(c: CommitCandidate) -> dict:
    return {
        "sha": c.commit.sha,
        "score": c.score,
        "confidence": c.confidence,
        "message": c.commit.message.splitlines()[0] if c.commit.message else "",
        "url": c.commit.url,
        "date": c.commit.date.isoformat(),
        "occurrences": len(c.matches),
        "evidence": {
            "has_null_check_added": c.evidence.has_null_check_added,
            "null_check_construct": c.evidence.null_check_construct.value,
            "var_was_used_before": c.evidence.var_was_used_before,
            "is_likely_bugfix": c.evidence.is_likely_bugfix,
            "diff_size_lines": c.evidence.diff_size_lines,
            "touches_test_files_only": c.evidence.touches_test_files_only,
        },
        "matches": [
            {
                "file_path": m.file_path,
                "line_number": m.line_number,
                "construct": m.construct.value,
                "snippet": m.snippet,
            }
            for m in c.matches
        ],
    }


def build_summary(candidates: list[CommitCandidate]) -> dict:
    by_file: dict[str, int] = {}
    by_construct: dict[str, int] = {}
    total_matches = 0
    for c in candidates:
        for m in c.matches:
            total_matches += 1
            by_file[m.file_path] = by_file.get(m.file_path, 0) + 1
            by_construct[m.construct.value] = by_construct.get(m.construct.value, 0) + 1
    return {
        "total_commits_flagged": len(candidates),
        "total_pattern_occurrences": total_matches,
        "by_file": dict(sorted(by_file.items(), key=lambda kv: -kv[1])),
        "by_construct": by_construct,
    }


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GITHUB_TOKEN not set in environment", file=sys.stderr)
        return 2
    client = GitHubClient(token=token)
    print(f"detecting {args.pattern} in {args.repo} (min_score={args.min_score})...", file=sys.stderr)
    candidates = detect(args.repo, client, limit=args.limit, min_score=args.min_score)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repo": args.repo,
        "pattern": args.pattern,
        "min_score": args.min_score,
        "summary": build_summary(candidates),
        "candidates": [candidate_to_dict(c) for c in candidates],
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    s = payload["summary"]
    print(
        f"wrote {args.output}: {s['total_commits_flagged']} commits flagged, "
        f"{s['total_pattern_occurrences']} pattern occurrences "
        f"across {len(s['by_file'])} files",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
