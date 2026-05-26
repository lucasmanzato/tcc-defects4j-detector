"""Interactive CLI: prompts for a GitHub repo and produces a full report.

The user pastes either a GitHub URL (``https://github.com/owner/name``) or
the bare ``owner/name`` identifier. The script then walks the commit history,
scores each commit against the structural signature, and emits two outputs in
``results/``:

- ``results/<repo_slug>.json`` — full machine-readable output (candidates,
  per-file occurrences, evidences)
- ``results/<repo_slug>_report.md`` — layperson-friendly Markdown report

Progress messages are streamed to stderr while the analysis runs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import load_dotenv  # noqa: E402

load_dotenv()

from src import config  # noqa: E402
from src.detector import detect  # noqa: E402
from src.github_client import GitHubClient, GitHubError  # noqa: E402
from src.logger import setup_logging  # noqa: E402
from src.models import CommitCandidate  # noqa: E402

# Import the report builder from the sibling script so we don't duplicate
# rendering logic.
import build_report  # noqa: E402

REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
URL_RE = re.compile(r"github\.com[/:]([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)")

# Sensible default for the interactive run. The non-interactive
# scripts/run_detector.py exposes flags to override.
DEFAULT_LIMIT = 500


def parse_repo(raw: str) -> str | None:
    """Accept either ``owner/name`` or a GitHub URL and return ``owner/name``."""
    if not raw:
        return None
    cleaned = raw.strip().rstrip("/")
    cleaned = re.sub(r"\.git$", "", cleaned)
    m = URL_RE.search(cleaned)
    if m:
        return m.group(1)
    if REPO_RE.match(cleaned):
        return cleaned
    return None


def prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{question}{suffix}: ").strip()
        except EOFError:
            return default or ""
        if value:
            return value
        if default is not None:
            return default


def banner(title: str) -> None:
    width = max(60, len(title) + 4)
    print("=" * width)
    print(title.center(width))
    print("=" * width)


def candidate_to_dict(c: CommitCandidate) -> dict:
    return {
        "sha": c.commit.sha,
        "score": c.score,
        "confidence": c.confidence,
        "occurrences": len(c.matches),
        "message": c.commit.message.splitlines()[0] if c.commit.message else "",
        "url": c.commit.url,
        "date": c.commit.date.isoformat(),
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


def build_summary(candidates: list[CommitCandidate], pattern: str, repo: str, min_score: float) -> dict:
    """Aggregate per-file and per-construct counts so the JSON has totals."""
    by_file: dict[str, int] = {}
    by_construct: dict[str, int] = {}
    total_matches = 0
    for c in candidates:
        for m in c.matches:
            by_file[m.file_path] = by_file.get(m.file_path, 0) + 1
            by_construct[m.construct.value] = by_construct.get(m.construct.value, 0) + 1
            total_matches += 1
    by_file = dict(sorted(by_file.items(), key=lambda kv: -kv[1]))
    return {
        "total_commits_flagged": len(candidates),
        "total_pattern_occurrences": total_matches,
        "by_file": by_file,
        "by_construct": by_construct,
    }


def write_outputs(repo: str, candidates: list[CommitCandidate], min_score: float, pattern: str) -> tuple[Path, Path]:
    slug = repo.replace("/", "_").lower()
    json_path = ROOT / "results" / f"{slug}.json"
    md_path = ROOT / "results" / f"{slug}_report.md"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    summary = build_summary(candidates, pattern, repo, min_score)
    payload = {
        "repo": repo,
        "pattern": pattern,
        "min_score": min_score,
        "summary": summary,
        "candidates": [candidate_to_dict(c) for c in candidates],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Reuse the project's report builder to keep formatting consistent.
    md_path.write_text(build_report.render([payload | {"_filename": json_path.name}]), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    banner("Detector de padrões de correção de bugs · modo interativo")
    print()
    print("Pressione Ctrl+C a qualquer momento para cancelar.")
    print()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "ERRO: a variável de ambiente GITHUB_TOKEN não está definida.\n"
            "Crie um token em https://github.com/settings/tokens e coloque "
            "em .env como: GITHUB_TOKEN=ghp_...",
            file=sys.stderr,
        )
        return 2

    while True:
        raw = prompt("URL ou owner/name do repositório (ex.: apache/flink)")
        repo = parse_repo(raw)
        if repo:
            break
        print(f"  → Formato não reconhecido: {raw!r}. Tente novamente.")

    # Defaults are deliberate — the script aims at a single prompt. To tune
    # the limit or threshold, use scripts/run_detector.py (flag-driven).
    limit: int | None = DEFAULT_LIMIT
    min_score: float = config.DEFAULT_MIN_SCORE
    pattern = "missNullCheckP"

    print()
    print(f"  Repositório:    {repo}")
    print(f"  Limite:         {limit} commits (padrão)")
    print(f"  Pontuação mín.: {min_score} (padrão)")
    print(f"  Padrão alvo:    {pattern}")
    print()

    setup_logging(logging.INFO)
    started = time.monotonic()
    client = GitHubClient(token=token)

    try:
        candidates = detect(repo, client, limit=limit, min_score=min_score)
    except GitHubError as exc:
        print(f"\nERRO ao acessar GitHub: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelado pelo usuário.", file=sys.stderr)
        return 130

    elapsed = time.monotonic() - started

    json_path, md_path = write_outputs(repo, candidates, min_score, pattern)

    occurrences = sum(len(c.matches) for c in candidates)
    files_touched = len({m.file_path for c in candidates for m in c.matches})
    perfect = sum(1 for c in candidates if round(c.score, 2) == 1.0)
    high = sum(1 for c in candidates if c.confidence == "high")

    print()
    banner("Resultado")
    print(f"Tempo total:                 {elapsed:.1f} segundos")
    print(f"Commits flagrados:           {len(candidates)}")
    print(f"Pontos no código (matches):  {occurrences}")
    print(f"Arquivos diferentes:         {files_touched}")
    print(f"Pontuação 1.00 (acerto):     {perfect}")
    print(f"Confiança alta:              {high} de {len(candidates)}")
    print()
    print(f"Relatório legível:  {md_path}")
    print(f"JSON detalhado:     {json_path}")
    print()
    if candidates:
        print("Top 3 candidatos:")
        for c in candidates[:3]:
            msg = c.commit.message.splitlines()[0][:70] if c.commit.message else ""
            print(f"  {c.score:.2f} {c.confidence:6s}  {c.commit.sha[:10]}  {msg}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
