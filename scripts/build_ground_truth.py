"""Build ground truth JSON for missNullCheckP from defects4j-dissection.

Reads vendor/defects4j-dissection/defects4j-bugs.json, filters bugs that contain
the missNullCheckP repair pattern, and emits data/defects4j_ground_truth.json
with upstream GitHub repo + fix commit SHA.

Chart bugs are skipped: their revisionId is an SVN revision number, not a Git
SHA, and the upstream jfree/jfreechart GitHub repo does not preserve a clean
SVN to Git mapping. Documented as a known limitation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_REPO = {
    "Closure": "google/closure-compiler",
    "Lang": "apache/commons-lang",
    "Math": "apache/commons-math",
    "Mockito": "mockito/mockito",
    "Time": "JodaOrg/joda-time",
}

DISSECTION_PATH = Path("vendor/defects4j-dissection/defects4j-bugs.json")
OUTPUT_PATH = Path("data/defects4j_ground_truth.json")
PATTERN = "missNullCheckP"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def is_git_sha(value: str) -> bool:
    return bool(SHA_RE.match(value))


def build() -> list[dict]:
    bugs = json.loads(DISSECTION_PATH.read_text(encoding="utf-8"))
    out: list[dict] = []
    skipped: list[tuple[str, int, str]] = []
    for bug in bugs:
        if PATTERN not in bug.get("repairPatterns", []):
            continue
        project = bug["project"]
        bug_id = bug["bugId"]
        rev = str(bug["revisionId"])
        repo = PROJECT_REPO.get(project)
        if repo is None or not is_git_sha(rev):
            skipped.append((project, bug_id, rev))
            continue
        out.append(
            {
                "project": project,
                "bug_id": bug_id,
                "fix_commit_sha": rev,
                "github_repo": repo,
                "patterns": [PATTERN],
            }
        )
    out.sort(key=lambda e: (e["project"], e["bug_id"]))
    if skipped:
        print(f"skipped {len(skipped)} bugs (no upstream Git SHA):", file=sys.stderr)
        for project, bug_id, rev in skipped:
            print(f"  {project} {bug_id} (rev={rev})", file=sys.stderr)
    return out


def main() -> int:
    if not DISSECTION_PATH.exists():
        print(f"missing: {DISSECTION_PATH}", file=sys.stderr)
        return 1
    entries = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} entries to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
