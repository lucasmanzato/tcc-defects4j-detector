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
from src.patterns import PATTERNS, get_detector  # noqa: E402

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
        "evidence": _evidence_to_dict(c.evidence),
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


def _evidence_to_dict(evidence: object) -> dict:
    """Serialise any pattern-specific evidence dataclass to JSON-friendly dict.

    Iterates over the dataclass fields so new patterns automatically
    contribute their own evidences without changing this function.
    """
    out: dict = {}
    fields = getattr(type(evidence), "__dataclass_fields__", {})
    for name in fields:
        value = getattr(evidence, name)
        # Enums are serialised by their string value (NullCheckKind / CondReturnKind).
        if hasattr(value, "value") and not isinstance(value, (bool, int, float)):
            out[name] = value.value
        else:
            out[name] = value
    return out


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
    repo_slug = repo.replace("/", "_").lower()
    # ``pattern`` is part of the slug so running multiple patterns on the
    # same repo produces independent output files instead of overwriting.
    pattern_slug = re.sub(r"[^a-z0-9]+", "_", pattern.lower()).strip("_")
    slug = f"{repo_slug}__{pattern_slug}"
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

    patterns_chosen = _prompt_patterns()

    # Other parameters are kept at sensible defaults — the script aims to
    # ask only what cannot be sensibly defaulted. Use scripts/run_detector.py
    # for full flag control.
    limit: int | None = DEFAULT_LIMIT
    min_score: float = config.DEFAULT_MIN_SCORE

    print()
    print(f"  Repositório:    {repo}")
    print(f"  Limite:         {limit} commits (padrão)")
    print(f"  Pontuação mín.: {min_score} (padrão)")
    print(f"  Padrão(ões):    {', '.join(patterns_chosen)}")
    print()

    setup_logging(logging.INFO)
    started = time.monotonic()
    client = GitHubClient(token=token)

    try:
        results_by_pattern = _run_patterns(
            patterns_chosen, repo, client, limit=limit, min_score=min_score
        )
    except GitHubError as exc:
        print(f"\nERRO ao acessar GitHub: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelado pelo usuário.", file=sys.stderr)
        return 130

    elapsed = time.monotonic() - started

    print()
    banner("Resultado")
    print(f"Tempo total: {elapsed:.1f} segundos")
    print()

    for pattern_name, candidates in results_by_pattern.items():
        json_path, md_path = write_outputs(
            repo, candidates, min_score, pattern_name
        )
        _print_pattern_summary(pattern_name, candidates, json_path, md_path)
    return 0


# ---------------------------------------------------------------------------
# Helpers for multi-pattern execution and presentation
# ---------------------------------------------------------------------------
def _prompt_patterns() -> list[str]:
    """Ask the user which pattern(s) to detect.

    The menu is built dynamically from the registry, so new patterns appear
    automatically. ``ambos`` (or ``all``) selects every registered pattern.
    """
    options = list(PATTERNS.keys())
    print()
    print("Padrões disponíveis:")
    for idx, name in enumerate(options, start=1):
        desc = PATTERNS[name].description
        print(f"  {idx}. {name} — {desc}")
    print(f"  {len(options) + 1}. ambos (rodar todos os padrões)")
    print()
    while True:
        raw = prompt(
            "Qual padrão buscar? (número ou nome; Enter = 1)",
            default="1",
        ).strip().lower()
        if not raw or raw == "1":
            return [options[0]]
        if raw.isdigit():
            n = int(raw)
            if n == len(options) + 1 or raw == str(len(options) + 1):
                return list(options)
            if 1 <= n <= len(options):
                return [options[n - 1]]
        if raw in {"ambos", "all", "todos"}:
            return list(options)
        # Allow direct name match.
        for name in options:
            if raw == name.lower():
                return [name]
        print(f"  → Opção não reconhecida: {raw!r}. Tente novamente.")


def _run_patterns(
    pattern_names: list[str],
    repo: str,
    client: GitHubClient,
    limit: int | None,
    min_score: float,
) -> dict[str, list[CommitCandidate]]:
    """Run each requested pattern and return the candidates grouped by name.

    Patterns are executed sequentially (one full commit walk per pattern)
    because the orchestration scores commits against a single detector at a
    time. Future versions can interleave to share the API budget.
    """
    out: dict[str, list[CommitCandidate]] = {}
    for name in pattern_names:
        detector = get_detector(name)
        banner(f"Padrão: {name}")
        candidates = detect(
            repo, client, limit=limit, min_score=min_score, pattern=detector
        )
        out[name] = candidates
    return out


def _print_pattern_summary(
    pattern_name: str,
    candidates: list[CommitCandidate],
    json_path: Path,
    md_path: Path,
) -> None:
    occurrences = sum(len(c.matches) for c in candidates)
    files_touched = len({m.file_path for c in candidates for m in c.matches})
    perfect = sum(1 for c in candidates if round(c.score, 2) == 1.0)
    high = sum(1 for c in candidates if c.confidence == "high")

    print(f"--- {pattern_name} ---")
    print(f"Commits flagrados:           {len(candidates)}")
    print(f"Pontos no código (matches):  {occurrences}")
    print(f"Arquivos diferentes:         {files_touched}")
    print(f"Pontuação 1.00 (acerto):     {perfect}")
    print(f"Confiança alta:              {high} de {len(candidates)}")
    print()
    print(f"Relatório legível:  {md_path}")
    print(f"JSON detalhado:     {json_path}")
    if candidates:
        print()
        print("Top 3 candidatos:")
        for c in candidates[:3]:
            msg = c.commit.message.splitlines()[0][:70] if c.commit.message else ""
            print(f"  {c.score:.2f} {c.confidence:6s}  {c.commit.sha[:10]}  {msg}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
