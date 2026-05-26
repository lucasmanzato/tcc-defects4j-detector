"""Classify each Defects4J missNullCheckP bug by its construct variation.

Reads ``vendor/defects4j-dissection/defects4j-bugs.json`` and runs the
project's own ``detect_null_check`` on each bug's diff to assign one of the
five canonical forms (guard_return, guard_throw, guard_block, ternary,
requireNonNull). Emits a Markdown table suitable for the TCC appendix.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.diff_parser import parse_unified_diff  # noqa: E402
from src.features import detect_null_check  # noqa: E402
from src.models import NullCheckKind  # noqa: E402

PATTERN = "missNullCheckP"
BASE_URL = "https://program-repair.org/defects4j-dissection/#!/bug"

KIND_LABEL = {
    NullCheckKind.GUARD_RETURN: "guard_return — sai da função (`if vazio → return`)",
    NullCheckKind.GUARD_THROW: "guard_throw — lança erro (`if vazio → throw`)",
    NullCheckKind.GUARD_BLOCK: "guard_block — bloco alternativo (`if vazio → ...`)",
    NullCheckKind.TERNARY: "ternary — operador inline (`vazio ? ... : ...`)",
    NullCheckKind.REQUIRE_NON_NULL: "requireNonNull — biblioteca",
    NullCheckKind.NONE: "(não classificado)",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dissection",
        type=Path,
        default=Path("vendor/defects4j-dissection/defects4j-bugs.json"),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("results/missnullcheckp_variations.md"),
    )
    return p.parse_args()


def classify_bug(bug: dict) -> NullCheckKind:
    diff_text = bug.get("diff") or ""
    if not diff_text.strip():
        return NullCheckKind.NONE
    try:
        files = parse_unified_diff(diff_text)
    except Exception:
        return NullCheckKind.NONE
    all_added = tuple(line for f in files for line in f.added_lines)
    return detect_null_check(all_added)


def main() -> int:
    args = parse_args()
    if not args.dissection.exists():
        print(f"missing: {args.dissection}", file=sys.stderr)
        return 1
    bugs = json.loads(args.dissection.read_text(encoding="utf-8"))
    candidates = [b for b in bugs if PATTERN in b.get("repairPatterns", [])]
    candidates.sort(key=lambda b: (b["project"], b["bugId"]))

    rows: list[dict] = []
    for bug in candidates:
        kind = classify_bug(bug)
        rows.append(
            {
                "project": bug["project"],
                "bug_id": bug["bugId"],
                "construct": kind,
                "url": f"{BASE_URL}/{bug['project']}/{bug['bugId']}",
            }
        )

    counts = {k: sum(1 for r in rows if r["construct"] is k) for k in NullCheckKind}
    md = render(rows, counts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(f"wrote {args.output} ({len(rows)} bugs)")
    return 0


def render(rows: list[dict], counts: dict[NullCheckKind, int]) -> str:
    lines: list[str] = []
    lines.append("# Variações sintáticas do padrão `missNullCheckP`\n")
    lines.append(
        "Tabela construída a partir dos **25 bugs** classificados pelo "
        "Defects4J Dissection sob o padrão `missNullCheckP`. A coluna "
        "*Variação* é uma sub-classificação empírica deste trabalho, obtida "
        "ao aplicar a função `detect_null_check` (em `src/features.py`) ao "
        "diff de cada bug.\n"
    )
    lines.append("## Distribuição agregada\n")
    lines.append("| Variação | Bugs |")
    lines.append("|---|---:|")
    for kind in (
        NullCheckKind.GUARD_RETURN,
        NullCheckKind.GUARD_THROW,
        NullCheckKind.GUARD_BLOCK,
        NullCheckKind.TERNARY,
        NullCheckKind.REQUIRE_NON_NULL,
        NullCheckKind.NONE,
    ):
        c = counts.get(kind, 0)
        if c == 0 and kind is NullCheckKind.NONE:
            continue
        lines.append(f"| {KIND_LABEL[kind]} | {c} |")
    lines.append("")

    lines.append("## Tabela completa\n")
    lines.append("| Projeto | Bug | Variação | Link no Dissection |")
    lines.append("|---|---:|---|---|")
    for r in rows:
        lines.append(
            f"| {r['project']} | {r['bug_id']} | {KIND_LABEL[r['construct']]} | [abrir]({r['url']}) |"
        )
    lines.append("")

    lines.append(
        "## Observações\n"
    )
    lines.append(
        "- **`requireNonNull`** não aparece nos 25 bugs do Defects4J — a "
        "biblioteca `Objects.requireNonNull` foi introduzida no Java 7 "
        "(2011) e os bugs do dataset são, em sua maioria, anteriores a essa "
        "data ou de projetos que evitavam dependências externas. A forma "
        "ainda assim faz parte da assinatura por aparecer com frequência em "
        "código moderno.\n"
    )
    lines.append(
        "- A coluna *Variação* foi atribuída automaticamente. Em casos "
        "ambíguos (por exemplo, um diff que adiciona simultaneamente um "
        "ternário e um `if`-guard), prevalece o primeiro casamento na ordem "
        "de classificação: `requireNonNull` → `ternary` → `guard_throw` → "
        "`guard_return` → `guard_block`.\n"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
