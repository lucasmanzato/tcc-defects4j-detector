"""Generate a layperson-friendly Markdown report from detector JSON outputs.

Reads every ``results/*.json`` produced by ``run_detector.py`` and emits a
single Markdown file (default: ``results/repos_comparison.md``) written for
non-technical readers: plain Portuguese, no jargon, every number explained.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Friendly labels for technical construct names.
CONSTRUCT_LABELS: dict[str, str] = {
    "guard_return": "Verificação que sai da função (`if vazio → return`)",
    "guard_throw": "Verificação que lança erro (`if vazio → throw`)",
    "guard_block": "Verificação que executa caminho alternativo (`if vazio → ...`)",
    "ternary": "Verificação inline (operador ternário `vazio ? ... : ...`)",
    "requireNonNull": "Verificação via biblioteca (`Objects.requireNonNull`)",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results-dir", type=Path, default=Path("results"))
    p.add_argument("--output", type=Path, default=Path("results/repos_comparison.md"))
    p.add_argument(
        "--repo",
        action="append",
        default=None,
        help="Restrict report to one or more repos (matches `owner/name` or substring). "
             "Pass the flag multiple times to include several.",
    )
    return p.parse_args()


def load_runs(results_dir: Path, repo_filters: list[str] | None = None) -> list[dict]:
    runs: list[dict] = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "summary" not in data:
            continue
        if repo_filters and not any(f.lower() in data.get("repo", "").lower() for f in repo_filters):
            continue
        data["_filename"] = path.name
        runs.append(data)
    return runs


def render(runs: list[dict]) -> str:
    if not runs:
        return "# Relatório de análise — nenhum repositório analisado\n"

    sections: list[str] = []
    sections.append(_render_intro(runs))
    sections.append(_render_signature())
    sections.append(_render_summary_table(runs))
    sections.append(_render_aggregate_constructs(runs))
    for run in runs:
        sections.append(_render_repo(run))
    sections.append(_render_glossary())
    return "\n\n".join(sections) + "\n"


# ---- intro -----------------------------------------------------------------
def _render_intro(runs: list[dict]) -> str:
    repos = ", ".join(f"`{r['repo']}`" for r in runs)
    n = len(runs)
    if n == 1:
        scope = f"em **1 projeto** de código aberto: {repos}"
    else:
        scope = f"em **{n} projetos** de código aberto: {repos}"
    return f"""# Relatório de análise de correções de bug

## O que foi analisado

Este relatório mostra os resultados de uma busca automática por um tipo
específico de correção de bug {scope}.

O bug procurado é conhecido como **"verificação de vazio faltante"**
(em inglês, *missing null check*). Ele acontece quando o código original
esquece de checar se uma variável está vazia antes de usá-la, o que
provoca um erro em tempo de execução. A correção típica é simplesmente
**adicionar essa verificação**.

A ferramenta percorreu o histórico de mudanças (*commits*) de cada
projeto e marcou aquelas que aparentam ser correções desse tipo,
seguindo regras estruturais explícitas — sem inteligência artificial e
sem treinamento prévio. Cada mudança recebe uma pontuação entre 0 e 1.
Acima de **0,70** ela é considerada uma provável correção.
"""


# ---- signature (mask) ------------------------------------------------------
def _render_signature() -> str:
    return """## A "assinatura" do bug — o molde usado para comparar

A ferramenta não faz busca por palavras-chave nem usa inteligência
artificial. Ela compara cada mudança do projeto contra um **molde
estrutural** (também chamado de *assinatura* ou *máscara*) que descreve
como uma correção do tipo procurado costuma se parecer. Se a mudança se
encaixa no molde, é marcada; se não se encaixa, é descartada.

O molde tem **dois grupos de perguntas**: indícios obrigatórios (sem eles
não há correção) e indícios de confirmação (que aumentam a certeza).

### Indícios obrigatórios (eliminatórios)

Se qualquer um destes responder "não", a mudança é automaticamente
descartada — independente do que disserem os demais.

| # | Pergunta | Peso | Por que é obrigatório |
|---|---|---:|---|
| 1 | A mudança **adicionou** uma verificação de valor vazio (algo equivalente a "se está vazio…")? | 0,50 | Sem isso, simplesmente não existe correção do tipo procurado. |
| 2 | A verificação adicionada se encaixa em **uma das cinco formas conhecidas** (ver tabela abaixo)? | 0,25 | A literatura catalogou apenas essas cinco formas como casos do padrão; qualquer coisa fora delas é outro tipo de mudança. |

### Indícios de confirmação (aumentam a certeza, não eliminam)

Estes são "votos a favor". Faltar não desclassifica, mas a pontuação
final fica menor.

| # | Pergunta | Peso | Para que serve |
|---|---|---:|---|
| 3 | A variável protegida pela verificação **já era usada antes** da mudança no mesmo arquivo? | 0,20 | Distingue uma correção de bug ("essa variável já existia, esqueceram de checar") de código novo defensivo. |
| 4 | A **mensagem do commit** menciona algo do tipo "fix NPE", "null check", "avoid null"? | 0,05 | Indício útil mas fraco — desenvolvedores frequentemente não mencionam o detalhe técnico na descrição. |

### As cinco formas conhecidas (variações do mesmo padrão)

Para o indício obrigatório nº 2, a verificação precisa ser uma destas:

| Forma | Como costuma aparecer no código |
|---|---|
| Sair da função (`guard_return`) | `if (x == null) return ...;` |
| Lançar erro (`guard_throw`) | `if (x == null) throw new ...;` |
| Bloco alternativo (`guard_block`) | `if (x == null) { ... } else { ... }` |
| Inline ternário (`ternary`) | `x == null ? valor_padrao : x.metodo()` |
| Biblioteca (`requireNonNull`) | `Objects.requireNonNull(x);` |

### Como a pontuação se forma

A soma dos pesos dos quatro indícios resulta em uma nota entre **0 e 1**.
Acima de **0,70** a mudança é considerada uma provável correção. Abaixo,
é descartada.

- Os dois indícios obrigatórios sozinhos já totalizam **0,75** — basta
  para passar do limite, mesmo sem confirmações.
- Acrescentar a variável-usada-antes leva a **0,95**.
- Com tudo (mensagem inclusive), a pontuação chega a **1,00**.

### Onde a assinatura está no código

Toda essa lógica está implementada nestes arquivos do projeto:

| Arquivo | O que contém |
|---|---|
| `src/models.py` | A estrutura de dados da assinatura (`Evidence`) e o catálogo das cinco formas (`NullCheckKind`). |
| `src/features.py` | As regras de detecção: como reconhecer cada forma, como extrair a variável protegida, como classificar a mensagem. |
| `src/config.py` | Os pesos numéricos (0,50 / 0,25 / 0,20 / 0,05) e o limite mínimo de pontuação (0,70). |
| `src/scorer.py` | O cálculo final que combina os indícios em uma nota e atribui o nível de confiança. |

Os pesos foram calibrados de forma empírica: testamos contra os 18 bugs
do tipo `missNullCheckP` catalogados no Defects4J Dissection (a base de
referência da literatura) e ajustamos para que **todos eles fossem
detectados** acima do limite de 0,70 — atingindo recall de 100% no
conjunto de validação.
"""


# ---- summary table ---------------------------------------------------------
def _render_summary_table(runs: list[dict]) -> str:
    lines: list[str] = []
    title = "## Visão geral do projeto" if len(runs) == 1 else "## Visão geral dos projetos"
    lines.append(f"{title}\n")
    lines.append(
        "| Projeto | Correções encontradas | Pontos no código | Arquivos diferentes | Pontos por correção (média) | Confiança alta |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for run in runs:
        s = run["summary"]
        n = s["total_commits_flagged"]
        occ = s["total_pattern_occurrences"]
        files = len(s["by_file"])
        avg = (occ / n) if n else 0
        high = sum(1 for c in run["candidates"] if c["confidence"] == "high")
        pct_high = high / n * 100 if n else 0
        lines.append(
            f"| `{run['repo']}` | {n} | {occ} | {files} | {avg:.1f} | {pct_high:.0f}% |"
        )
    lines.append("")
    lines.append(
        "**Como ler:** uma única correção pode arrumar o problema em vários "
        "lugares ao mesmo tempo. Por isso a coluna *Pontos no código* é maior "
        "ou igual à de *Correções encontradas*. *Confiança alta* significa "
        "que, além da pontuação alta, a correção é pequena e está em código "
        "de produção (não em arquivos de teste)."
    )
    return "\n".join(lines)


# ---- aggregate constructs --------------------------------------------------
def _render_aggregate_constructs(runs: list[dict]) -> str:
    aggregate: Counter[str] = Counter()
    for run in runs:
        for kind, count in run["summary"]["by_construct"].items():
            aggregate[kind] += count
    total = sum(aggregate.values())

    lines: list[str] = []
    lines.append("## Como os desenvolvedores escrevem essas correções\n")
    lines.append(
        "Toda correção desse tipo segue uma das **cinco formas conhecidas**. "
        "Saber qual forma cada projeto prefere ajuda a entender o estilo de "
        "código da equipe."
    )
    lines.append("")
    lines.append("| Forma da correção | Total | Participação |")
    lines.append("|---|---:|---:|")
    for kind, count in aggregate.most_common():
        share = count / total * 100 if total else 0
        label = CONSTRUCT_LABELS.get(kind, kind)
        lines.append(f"| {label} | {count} | {share:.1f}% |")
    return "\n".join(lines)


# ---- per-repo --------------------------------------------------------------
def _render_repo(run: dict) -> str:
    s = run["summary"]
    cands = run["candidates"]
    n = s["total_commits_flagged"]

    high = sum(1 for c in cands if c["confidence"] == "high")
    medium = sum(1 for c in cands if c["confidence"] == "medium")
    perfect = sum(1 for c in cands if round(c["score"], 2) == 1.0)
    avg_occ = (s["total_pattern_occurrences"] / n) if n else 0

    lines: list[str] = []
    lines.append(f"## `{run['repo']}`\n")
    lines.append(
        f"- **Mudanças marcadas como possível correção:** {n}"
    )
    lines.append(
        f"- **Locais ajustados em todo o repositório:** {s['total_pattern_occurrences']}"
    )
    lines.append(
        f"- **Quantos arquivos diferentes:** {len(s['by_file'])}"
    )
    lines.append(
        f"- **Em média, cada correção arruma:** {avg_occ:.1f} ponto(s) no código"
    )
    lines.append(
        f"- **Confiança alta:** {high} de {n} ({_pct(high, n)}) · "
        f"**Confiança média:** {medium} ({_pct(medium, n)})"
    )
    lines.append(
        f"- **Acerto perfeito** (todos os indicadores positivos): {perfect} de {n} ({_pct(perfect, n)})"
    )
    lines.append("")

    # Construct breakdown — only if any data
    if s["by_construct"]:
        lines.append("### Estilo de correção mais usado neste projeto\n")
        lines.append("| Forma | Vezes que apareceu |")
        lines.append("|---|---:|")
        for kind, count in sorted(s["by_construct"].items(), key=lambda kv: -kv[1]):
            label = CONSTRUCT_LABELS.get(kind, kind)
            lines.append(f"| {label} | {count} |")
        lines.append("")

    # Top files
    if s["by_file"]:
        lines.append("### Arquivos mais corrigidos\n")
        lines.append("| Vezes | Arquivo |")
        lines.append("|---:|---|")
        for path, count in list(s["by_file"].items())[:5]:
            short = "/".join(path.split("/")[-3:])
            lines.append(f"| {count} | `{short}` |")
        lines.append("")

    # Top candidates
    if cands:
        lines.append("### Principais correções identificadas\n")
        lines.append(
            "Cada linha é uma mudança no histórico do projeto. *Pontos no "
            "código* indica em quantos lugares a correção foi aplicada."
        )
        lines.append("")
        lines.append("| Pontuação | Confiança | Pontos no código | Data | Resumo da mudança |")
        lines.append("|---:|---|---:|---|---|")
        for c in cands[:5]:
            date = c["date"][:10]
            msg = c["message"][:90].replace("|", "\\|")
            lines.append(
                f"| {c['score']:.2f} | {c['confidence']} | {c['occurrences']} | {date} | {msg} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---- glossary --------------------------------------------------------------
def _render_glossary() -> str:
    return """## Glossário rápido

- **Correção (commit):** uma mudança que o desenvolvedor enviou ao
  repositório. O histórico do projeto é a sequência completa de
  correções, com data, mensagem e o que foi alterado.
- **Pontuação (0 a 1):** medida de quão certa a ferramenta está de que
  aquela mudança é uma correção do tipo procurado. Quanto mais alta,
  mais indícios estão presentes.
- **Confiança alta:** pontuação acima de 0,70 e mudança em código de
  produção (não apenas testes). É o nível de evidência mais forte.
- **Confiança média:** pontuação alta, mas a mudança é grande demais ou
  toca apenas testes. Vale revisar manualmente.
- **Verificação de vazio (null check):** uma instrução curta que pergunta
  "esse valor está vazio?" antes de usá-lo, evitando o erro.
- **Falso positivo:** quando a ferramenta marcou algo que, ao olhar de
  perto, não é realmente o tipo de correção esperado. Faz parte de
  qualquer abordagem automática; este relatório lista os candidatos para
  revisão humana, não para aceitação cega.
"""


# ---- helpers ---------------------------------------------------------------
def _pct(part: int, total: int) -> str:
    return f"{(part / total * 100):.0f}%" if total else "0%"


def main() -> int:
    args = parse_args()
    runs = load_runs(args.results_dir, args.repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(runs), encoding="utf-8")
    print(f"wrote {args.output} ({len(runs)} repositórios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
