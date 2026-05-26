# Prompt para Claude Code — TCC v2

## Contexto

Estou desenvolvendo um TCC sobre **detecção automática de padrões de correção de bugs** em repositórios Java do GitHub. A v1 funcionou como prova de conceito; agora quero a **v2: mais direta, otimizada e organizada**.

O sistema deve identificar, no histórico de commits de um projeto Java, quais commits aplicaram o padrão de reparo **`missNullCheckP`** (adição de verificação de nulo ausente — causadora de NullPointerException), conforme catalogado no **Defects4J Dissection**.

Referência de bug típico do dataset: https://program-repair.org/defects4j-dissection/#!/bug/Chart/7

A abordagem é **determinística e interpretável** — sem ML, sem LLMs, sem dados de treinamento externos. O score é construído a partir de evidências estruturais extraídas do diff, cada uma com justificativa explícita.

## Objetivo desta sessão

Construir do zero a v2 do projeto, com código limpo, modular e testável. Quero que você atue como engenheiro de software sênior: faça boas escolhas de arquitetura, evite over-engineering, e priorize legibilidade.

## Stack e restrições

- **Linguagem:** Python 3.11+
- **Dependências mínimas:** `requests` (GitHub API), `unidiff` (parsing de diffs), `pytest` (testes). Nada além disso sem justificar.
- **Sem ML, sem LLMs, sem dependências pesadas.** O detector deve ser puramente estrutural.
- **Reprodutível:** rodando localmente, sem serviços externos além da API pública do GitHub.
- **Token GitHub:** ler de variável de ambiente `GITHUB_TOKEN`.

## Estrutura do projeto que quero

```
tcc_v2/
├── README.md                     # como rodar, exemplos, métricas
├── requirements.txt
├── .env.example
├── src/
│   ├── __init__.py
│   ├── github_client.py          # busca commits via API
│   ├── diff_parser.py            # parsing estruturado do diff
│   ├── features.py               # extração de features (evidências)
│   ├── scorer.py                 # cálculo do score + confiança
│   ├── detector.py               # orquestra o pipeline
│   ├── baseline.py               # baseline ingênuo (palavras na mensagem)
│   └── evaluation.py             # métricas Precision/Recall/F1
├── data/
│   └── defects4j_ground_truth.json   # 25 bugs missNullCheckP
├── tests/
│   ├── test_diff_parser.py
│   ├── test_features.py
│   ├── test_scorer.py
│   └── fixtures/                 # diffs reais como fixtures
├── scripts/
│   ├── run_detector.py           # CLI: detecta em um repo qualquer
│   └── run_evaluation.py         # roda contra ground truth e imprime métricas
└── results/                      # outputs gerados (não versionados)
```

## Pipeline (cada etapa = um módulo)

1. **GitHub Client** — recebe `owner/repo`, retorna commits paginados (SHA, mensagem, autor, data, arquivos alterados, patch).
2. **Diff Parser** — para cada commit, identifica linhas adicionadas (+) e removidas (-) por arquivo, normalizadas (sem whitespace ruído).
3. **Feature Extractor** — extrai do diff um dicionário de evidências:
   - `has_null_check_added`: bool — adicionou `if (x == null)`, `if (null == x)`, ou `Objects.requireNonNull(...)`?
   - `null_check_construct`: enum — `guard_return`, `guard_throw`, `ternary`, `requireNonNull`, `none`
   - `var_was_used_before`: bool — a variável protegida já era referenciada no arquivo antes da mudança?
   - `is_likely_bugfix`: bool — mensagem sugere bugfix (palavras-chave + heurística de tamanho)?
   - `diff_size_lines`: int
   - `touches_test_files_only`: bool
4. **Scorer** — combina features em score 0.0–1.0 com pesos justificados no docstring. Cada peso comentado com o "porquê" derivado da análise dos bugs do Defects4J.
5. **Confidence Adjuster** — penaliza commits muito grandes, de docs/chore, ou só de testes. Define nível: `low` (<0.4) / `medium` (0.4–0.7) / `high` (>0.7).
6. **Detector** — orquestra tudo e retorna lista ranqueada de candidatos.
7. **Baseline** — classificador ingênuo que olha só palavras-chave na mensagem (`null`, `NPE`, `NullPointerException`).
8. **Evaluation** — roda detector e baseline contra ground truth, calcula Precision/Recall/F1 e imprime tabela comparativa.

## Ground truth

O arquivo `data/defects4j_ground_truth.json` deve conter os 25 bugs oficialmente classificados como `missNullCheckP` no Defects4J Dissection, no formato:

```json
[
  {
    "project": "Chart",
    "bug_id": 7,
    "fix_commit_sha": "<sha>",
    "github_repo": "jfree/jfreechart",
    "patterns": ["missNullCheckP"]
  }
]
```

Se você não tiver os SHAs exatos, deixe um TODO claro e crie um stub com 3–5 entradas conhecidas para que os testes rodem.

## CLI esperada

```bash
# Roda detector em um repositório
python scripts/run_detector.py --repo jfree/jfreechart --pattern missNullCheckP --limit 500 --output results/jfreechart.json

# Avalia contra ground truth
python scripts/run_evaluation.py --ground-truth data/defects4j_ground_truth.json --output results/eval.md
```

A saída de `run_evaluation.py` deve ser um relatório markdown com:
- Tabela: detector vs baseline (Precision, Recall, F1)
- Lista de falsos positivos e falsos negativos com explicação
- Distribuição de scores

## Critérios de qualidade

- **Funções pequenas e nomeadas pelo que fazem**, não pelo como.
- **Docstrings em todas as funções públicas**, com exemplo quando útil.
- **Type hints obrigatórios** em todas as assinaturas.
- **Testes unitários** para `diff_parser`, `features` e `scorer`, usando diffs reais do Defects4J como fixtures (Chart 7 é um ótimo ponto de partida).
- **Sem código morto, sem comentários óbvios, sem prints de debug.**
- **README com:** propósito, como rodar, exemplo de saída, métricas obtidas, limitações conhecidas.

## Como quero que você trabalhe

1. **Antes de codar**, me proponha a estrutura final de arquivos e os pontos de decisão arquitetural que enxerga (ex: como modelar o resultado, como lidar com rate limit do GitHub). Espere meu OK antes de implementar.
2. **Implemente em ordem de dependência**: `diff_parser` → `features` → `scorer` → `detector` → `evaluation`. Cada módulo com testes antes de seguir.
3. **Use o bug Chart 7 como exemplo guia** durante o desenvolvimento — se o detector não pega Chart 7, algo está errado.
4. **Ao final**, rode a avaliação completa e me reporte as métricas em uma tabela curta.

## O que NÃO fazer

- Não criar abstrações para os outros 30 padrões agora — foco total em `missNullCheckP`.
- Não usar regex monolíticas ilegíveis; prefira parsing estruturado.
- Não criar interface web, dashboard, ou qualquer camada visual.
- Não silenciar exceções; falhas devem ser explícitas.

## Primeiro passo

Comece propondo a arquitetura final dos módulos e me mostre como ficaria a interface (assinaturas) de cada função pública antes de escrever a implementação.
