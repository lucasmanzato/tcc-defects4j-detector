# Arquitetura do sistema

Documento de referência sobre a estrutura interna do detector. Voltado para quem
precisa entender, manter ou estender o projeto.

---

## 1. Visão geral — o que entra e o que sai

```
┌───────────────────────┐
│  Repositório GitHub   │
│  (ex.: apache/flink)  │
└──────────┬────────────┘
           │ histórico de commits
           ▼
┌──────────────────────────────────────────────────────────────┐
│                     SISTEMA DE DETECÇÃO                      │
│  • Busca commits (GitHub API)                                │
│  • Lê o diff de cada um                                      │
│  • Aplica a "máscara" estrutural (4 indícios)                │
│  • Calcula pontuação 0–1                                     │
└──────────┬────────────────────────────────┬──────────────────┘
           │                                │
           ▼                                ▼
   ┌───────────────┐               ┌────────────────────┐
   │  JSON cru     │               │  Relatório MD      │
   │ (toda info)   │               │ (legível humano)   │
   │ results/*.json│               │ results/*.md       │
   └───────────────┘               └────────────────────┘
```

A entrada é um repositório (`owner/name`). As saídas são duas:

1. **JSON detalhado** — para uso por outras ferramentas (inclui localização de
   cada ocorrência, snippet, evidências, etc.).
2. **Markdown amigável** — para leitura humana (gerado por `scripts/build_report.py`).

---

## 2. Pipeline em 5 estágios

```
[1] FETCH  →  [2] PARSE  →  [3] EXTRACT  →  [4] SCORE  →  [5] REPORT
```

| Estágio | Pergunta que responde | Onde mora |
|---------|-----------------------|-----------|
| **1. Fetch** | "Quais commits existem nesse repositório?" | `src/github_client.py` |
| **2. Parse** | "Em cada commit, o que foi adicionado, removido e qual o contexto?" | `src/diff_parser.py` |
| **3. Extract** | "Esse diff tem os indícios da máscara?" | `src/features.py` |
| **4. Score** | "Quanto vale essa combinação de indícios?" | `src/scorer.py` |
| **5. Report** | "Como isso é apresentado para o leitor?" | `src/detector.py` + scripts/ |

Cada estágio só conhece o anterior; nenhum sabe do estágio seguinte. Isso é o
que permite testar e trocar peças isoladamente.

---

## 3. Layout de pastas

```
Tcc_v2/
├── ARCHITECTURE.md             ◄── este documento
├── README.md                   ◄── manual de uso
│
├── src/                        ◄── O cérebro do sistema
│   ├── models.py               (1) "tipos" — formato dos dados
│   ├── config.py               (2) constantes — pesos e limites
│   ├── github_client.py        (3) ponte com a API do GitHub
│   ├── diff_parser.py          (4) lê diff bruto e estrutura
│   ├── features.py             (5) detecta indícios + ocorrências
│   ├── scorer.py               (6) combina indícios em pontuação
│   ├── detector.py             (7) orquestra tudo
│   ├── baseline.py             (8) classificador ingênuo (comparação)
│   ├── evaluation.py           (9) métricas Precisão/Recall/F1
│   └── logger.py              (10) progress logger compartilhado
│
├── scripts/                    ◄── O que o usuário roda
│   ├── _env.py                 carrega .env (token GitHub)
│   ├── build_ground_truth.py   gera data/defects4j_ground_truth.json
│   ├── run_interactive.py      modo console interativo (entrada de URL)
│   ├── run_detector.py         analisa um repo → JSON (modo CLI)
│   ├── check_recall.py         testa contra ground truth → MD
│   ├── run_evaluation.py       avalia contra histórico completo
│   ├── build_report.py         transforma JSON em MD legível
│   └── classify_dissection_variations.py  classifica os 25 bugs
│
├── tests/                      ◄── Garantia de que funciona
│   ├── fixtures/               diffs reais do Defects4J
│   ├── test_diff_parser.py
│   ├── test_features.py
│   ├── test_scorer.py
│   └── test_pipeline_smoke.py
│
├── data/
│   └── defects4j_ground_truth.json    20 bugs com SHA real
│
├── results/                    saída do sistema (gitignored)
│   ├── error_prone.json
│   ├── flink.json
│   ├── joda_time.json
│   ├── joda_time_report.md
│   └── missnullcheckp_variations.md
│
└── vendor/                     dados externos (gitignored)
    └── defects4j-dissection/
        └── defects4j-bugs.json    catálogo dos 395 bugs
```

---

## 4. Cada módulo do `src/`

### `models.py` — formato dos dados

Tipos imutáveis (`@dataclass(frozen=True)`). Define o **formato** dos dados que
circulam entre módulos. Estruturas principais:

| Tipo | Para que serve |
|------|----------------|
| `Commit` | Tudo que sabemos de um commit (SHA, mensagem, autor, data, arquivos alterados) |
| `FileDiff` | Um arquivo dentro de um commit (caminho, linhas adicionadas/removidas/contexto, números de linha) |
| `Match` | Uma ocorrência específica (caminho, linha, forma do null check, snippet) |
| `Evidence` | A "máscara" preenchida: 4 booleanos + 2 números |
| `CommitCandidate` | Resultado final: commit + pontuação + nível de confiança + lista de matches |
| `NullCheckKind` | Enum com as 5 formas: `GUARD_RETURN`, `GUARD_THROW`, `GUARD_BLOCK`, `TERNARY`, `REQUIRE_NON_NULL` |

### `config.py` — todos os números

Constantes de calibração. Para mudar peso de um indício ou o limite mínimo de
pontuação, mexe **só aqui**. Nada de números mágicos espalhados.

```python
W_NULL_CHECK_ADDED      = 0.50    # peso do indício 1 (eliminatório)
W_CANONICAL_CONSTRUCT   = 0.25    # peso do indício 2 (eliminatório)
W_VAR_USED_BEFORE       = 0.20    # peso do indício 3 (confirmação)
W_BUGFIX_MESSAGE        = 0.05    # peso do indício 4 (confirmação)
DEFAULT_MIN_SCORE       = 0.7     # limite acima do qual é candidato
LARGE_DIFF_LINES        = 200     # rebaixa confiança em commits gigantes
BUGFIX_KEYWORDS         = (...)   # palavras na mensagem que indicam bugfix
JAVA_TEST_PATH_MARKERS  = (...)   # como identificar pasta de teste
```

### `github_client.py` — ponte com a API

Única peça que fala com a internet. Usa apenas `requests`. Faz 3 coisas:

- Pagina o histórico (`list_commits`)
- Busca detalhes de um commit (`get_commit`)
- Respeita o limite de 5000 reqs/h: se sobrar < 10 reqs, espera o reset

Se a API falhar, lança `GitHubError` em vez de engolir o erro.

### `diff_parser.py` — diff bruto → estrutura

Usa a biblioteca `unidiff` para transformar texto em estrutura. Também:

- Normaliza fim-de-linha (Windows × Unix)
- Remove ruído (linhas só com `{`, `}`, comentários)
- Marca cada linha adicionada com seu número (para reportar localização)

### `features.py` — o coração do detector

Funções públicas:

| Função | Responde |
|--------|----------|
| `detect_null_check(linhas_adicionadas)` | Qual das 5 formas? Ou `NONE`? |
| `classify_line(linha)` | A mesma classificação, mas linha por linha (para reportar matches) |
| `variable_used_before(file_diff)` | A variável protegida já existia no contexto? |
| `is_bugfix_message(mensagem)` | Mensagem contém palavra-chave de bugfix? |
| `extract_evidence(commit)` | Junta tudo num `Evidence` (a máscara preenchida) |
| `find_matches(commit)` | Lista de `Match` (uma por linha que casa) |

Detecção é via **regex puro**. Sem AST, sem parser Java — propositalmente leve.

### `scorer.py` — combina indícios

Duas funções, ambas curtas:

```python
score(evidence)                    → 0.0 a 1.0
confidence_level(score, evidence)  → "low" | "medium" | "high"
```

Lógica:

- Se faltar indício 1 ou 2 (eliminatórios): `0.0`
- Caso contrário: soma dos pesos dos indícios presentes
- Confiança: deriva do score com penalidades (commit gigante → `medium`;
  só testes → `medium`)

### `detector.py` — a "cola"

Recebe o cliente GitHub, itera os commits, monta o pipeline:

```
commits → extract_evidence → score → filter ≥ 0.7 → find_matches → ordena → lista
```

Saída: `list[CommitCandidate]` ordenado por pontuação (data como desempate).

### `baseline.py` — classificador ingênuo

Não faz parte da detecção principal. Existe **só para comparação científica**:
se um simples grep pela mensagem encontrasse os bugs, o trabalho do detector
não estaria justificado. Atualmente o baseline tem recall de 33% no ground
truth, contra 100% do detector.

### `evaluation.py` — métricas

Calcula Precisão / Recall / F1 dado um conjunto de SHAs preditos versus SHAs
do ground truth. Renderiza relatório em Markdown.

---

## 5. Como os dados fluem

Fluxo concreto de uma chamada `python scripts/run_detector.py --repo X`:

```
┌────────────────────────────────────────────────────────────┐
│ scripts/run_detector.py                                    │
│  • carrega .env (GITHUB_TOKEN)                             │
│  • cria GitHubClient                                       │
│  • chama detect()                                          │
└───────────────────────┬────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────┐
│ src/detector.py :: detect()                                │
│  for commit in client.list_commits(repo):                  │
│      ev = features.extract_evidence(commit)                │
│      s  = scorer.score(ev)                                 │
│      if s >= 0.7:                                          │
│          c = scorer.confidence_level(s, ev)                │
│          m = features.find_matches(commit)                 │
│          yield CommitCandidate(commit, s, c, ev, m)        │
└───────────────────────┬────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
┌──────────────────┐          ┌──────────────────────┐
│ github_client    │          │ diff_parser          │
│ • requests       │          │ • unidiff            │
│ • paginação      │          │ • normalização       │
│ • rate-limit     │          │ • marcação de linhas │
└──────────────────┘          └──────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────┐
│ features.py :: extract_evidence()                          │
│  • filtra arquivos de teste                                │
│  • detect_null_check()  → NullCheckKind                    │
│  • variable_used_before()                                  │
│  • is_bugfix_message()                                     │
│  • diff_size_lines() / touches_test_files_only()           │
│  → retorna Evidence(...)                                   │
└────────────────────────────────────────────────────────────┘
```

Cada seta é uma chamada de função pura — sem estado mutável, sem efeitos
colaterais. Isso significa que se você executar duas vezes com o mesmo input,
**garantidamente** dá o mesmo output. Reproduzível.

---

## 6. As três entradas para o usuário

4 scripts CLI principais:

| Comando | Para quê | Custo (API) |
|---------|----------|------------:|
| `python scripts/run_interactive.py` | **Modo interativo:** prompt para URL, logs em tempo real, gera JSON + relatório MD | ~limit + 1 reqs |
| `python scripts/run_detector.py --repo X` | Modo flag-driven (uso em scripts) | ~limit + 1 reqs |
| `python scripts/check_recall.py` | Validar a heurística contra os bugs catalogados | 20 reqs (constante) |
| `python scripts/run_evaluation.py` | Métricas completas (Precision/Recall/F1) | varia (caro) |

Mais 2 scripts auxiliares (não conversam com a API):

| Comando | Para quê |
|---------|----------|
| `python scripts/build_report.py` | Transformar JSON em MD legível |
| `python scripts/classify_dissection_variations.py` | Catalogar as 5 formas nos 25 bugs |

---

## 7. Onde tocar para mudar comportamento

| Quero mudar... | Mexo em... |
|----------------|------------|
| Peso de algum indício | `src/config.py` (constantes `W_*`) |
| Limite mínimo de pontuação | `src/config.py` (`DEFAULT_MIN_SCORE`) |
| Adicionar palavra-chave de bugfix | `src/config.py` (`BUGFIX_KEYWORDS`) |
| Reconhecer nova forma de null check | `src/features.py` (regex `_*`) + `src/models.py` (enum `NullCheckKind`) |
| Como o relatório é apresentado | `scripts/build_report.py` |
| Lógica de penalidade da confiança | `src/scorer.py` (função `confidence_level`) |
| Como filtrar arquivos de teste | `src/config.py` (`JAVA_TEST_PATH_MARKERS`) + `src/features.py` (`_is_test_path`) |

---

## 8. Garantia de que funciona — os testes

| Camada | Testes | O que verifica |
|--------|------:|----------------|
| `test_diff_parser.py` | 16 | Lê fixtures reais (Lang33, Math4, Mockito38, Closure110), confere se identifica as linhas certas |
| `test_features.py` | 24 | Cada uma das 5 formas é detectada; variáveis são extraídas com indices/métodos; testes são filtrados |
| `test_scorer.py` | 11 | Pesos somam 1,0; eliminatórios funcionam; níveis de confiança caem nas faixas corretas |
| `test_pipeline_smoke.py` | 1 | Pipeline inteiro (sem rede) roda no diff do Lang 33 e produz score=1.00 |
| **Total** | **52** | Roda em ~0,1 segundo |

Para rodar tudo:

```bash
python -m pytest tests/
```

---

## 9. Princípios que guiam o design

- **Determinístico:** mesmo input → mesmo output, sempre. Sem ML, sem
  aleatoriedade.
- **Interpretável:** cada decisão tem um motivo escrito no código. O peso 0,50
  do indício 1 está comentado explicando por quê.
- **Modular:** se um estágio falha, só ele precisa ser revisitado. O
  `diff_parser` não sabe que existe `scorer`.
- **Sem mágica:** dependências mínimas (`requests`, `unidiff`, `pytest`). Nada
  de framework pesado.
- **Testável:** fixtures são diffs reais do Defects4J — a verdade vem do
  dataset acadêmico, não de exemplos sintéticos.

---

## 10. Glossário rápido

- **Commit** — uma mudança que o desenvolvedor enviou ao repositório.
- **Diff** — texto que mostra o que foi adicionado e removido entre duas
  versões de um arquivo.
- **SHA** — identificador único de cada commit (40 caracteres hexadecimais).
- **Indício / evidência** — uma das 4 perguntas estruturais que o detector faz.
- **Máscara / assinatura** — o conjunto completo das 4 perguntas + 5 formas.
- **Pontuação (score)** — número de 0 a 1 que mede o casamento com a máscara.
- **Confiança** — etiqueta `low` / `medium` / `high` que combina pontuação com
  penalidades de tamanho e tipo de arquivo.
- **Match** — uma linha específica do diff que dispara o reconhecimento de
  uma forma canônica.
- **Ground truth** — conjunto de 20 bugs com SHA conhecido, derivado do
  Defects4J Dissection, usado para validar o detector.
