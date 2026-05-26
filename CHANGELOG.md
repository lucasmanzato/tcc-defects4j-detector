# Histórico de versões

Este arquivo registra a evolução do detector ao longo das iterações. Cada
seção corresponde a uma versão (tag git) e descreve, em linguagem clara,
o que foi feito, por quê, e quais resultados foram observados. É um
documento auxiliar para a escrita do TCC: cita os marcos técnicos e as
métricas de cada estágio.

---

## v0.1.0-baseline — Detector estrutural funcional (2026-05-02)

**Status:** funcional · recall 100% no ground truth · produz falsos
positivos (commits de código novo defensivo, sem ser correção de bug).

### O que esta versão faz

Detecta automaticamente, no histórico de commits de um repositório Java
do GitHub, quais mudanças aplicaram o padrão `missNullCheckP` (adição de
verificação de valor vazio ausente — causadora de NullPointerException),
conforme catalogado no Defects4J Dissection.

### O caminho até aqui

A construção seguiu cinco iterações principais. Cada uma resolveu um
problema específico e foi validada contra o ground truth de 18 bugs
reais do Defects4J (20 catalogados, 2 inalcançáveis no GitHub atual).

#### Iteração 1 — Pipeline modular inicial
- Construído o pipeline em 5 estágios: Fetch → Parse → Extract → Score → Report
- 9 módulos em `src/`, cada um com responsabilidade única
- Arquitetura imutável (dataclasses congeladas), sem efeitos colaterais
- 47 testes unitários cobrindo `diff_parser`, `features`, `scorer`
- **Recall inicial:** 39% (7/18 bugs detectados)

#### Iteração 2 — Cobertura de variações sintáticas
Diagnóstico: o detector falhava em casos com `array[i] == null` e
`obj.method() == null` por regex restritivo.
- Regex de comparação null reescrito para aceitar acessos compostos
- Adicionado o enum `GUARD_BLOCK` para `if (x == null) { ... }` sem return/throw (caso comum não previsto inicialmente)
- **Recall após ajuste:** 67% (12/18)

#### Iteração 3 — Extração robusta de variáveis
Diagnóstico: a heurística de "variável já usada antes" extraía nomes
incorretos (capturava `if` em vez de `array`) por regex permissivo.
- Regex `_VAR_FROM_NULL_CMP` restringido para casar somente identificadores válidos, com suporte a `obj.method()` e `arr[i]`
- **Recall após ajuste:** 72% (13/18)

#### Iteração 4 — Calibração empírica dos pesos
Diagnóstico: 5 bugs reais ficavam em score 0.65 por terem só os dois
indícios eliminatórios (E1+E2). Verificou-se que **18/18 bugs** combinam
null check + construct canônico — portanto essa combinação deve, por si
só, cruzar o limite de 0.70.
- Pesos redistribuídos: E1=0.50, E2=0.25, E3=0.20, E4=0.05
- A descrição (E4) ficou propositalmente fraca: bugfixes reais nem sempre mencionam "null" na mensagem
- **Recall após ajuste:** 100% (18/18) ✓

#### Iteração 5 — Consistência arquivos de teste × código de produção
Diagnóstico: alguns commits flagrados tinham `score=0.95` mas
`occurrences=0`, porque `extract_evidence` considerava arquivos de teste
mas `find_matches` os excluía.
- `extract_evidence` agora filtra arquivos de teste, mantendo o filtro
  consistente em toda a pipeline
- **Recall:** mantido em 100%
- Falsos positivos em commits "só de teste" eliminados

#### Iteração 6 — Filtro de extensões na origem
Diagnóstico: o objeto `Commit` carregava todos os arquivos do diff,
incluindo `.py`, `.md`, `.yml`. Isso inflava `diff_size_lines` e poluía
a memória sem afetar resultados.
- Centralizada lista `ANALYZED_EXTENSIONS = (".java",)` em `src/config.py`
- Filtro aplicado em `github_client._to_commit` (fonte única)
- 5 testes adicionais cobrindo o filtro

### Métricas observadas

| Repositório | Commits analisados | Flagrados | Ocorrências | Arquivos |
|---|---:|---:|---:|---:|
| `apache/commons-lang` | 50 | 5 | 7 | 4 |
| `google/error-prone` | 500 | 49 | 80 | 45 |
| `apache/flink` | 500 | 117 | 441 | 193 |
| `JodaOrg/joda-time` | 500 | 9 | 17 | 4 |

Validação contra ground truth (Defects4J):
- **Detector:** 18/18 (recall 100%)
- **Baseline (palavra-chave na mensagem):** 6/18 (recall 33%)

### Limitação conhecida desta versão

**Alguns candidatos flagrados são código novo defensivo** (introdução
de método com null check proativo), não correção de bug real. A
heurística atual não distingue:

- *Fix*: existia código vulnerável → foi removido → substituído por código protegido
- *Feature defensiva*: método novo é introduzido já com null check no topo, sem código vulnerável anterior

Esta limitação é o ponto de partida da próxima iteração.

### Componentes desta versão

- **Pipeline:** 10 módulos em `src/` (incluindo `logger.py`)
- **Scripts CLI:** 7 (`run_interactive.py`, `run_detector.py`, `run_evaluation.py`, `check_recall.py`, `build_ground_truth.py`, `build_report.py`, `classify_dissection_variations.py`, `build_schedule_pdf.py`)
- **Testes:** 57 (todos passando)
- **Padrões cobertos:** 1 (`missNullCheckP`)
- **Variações sintáticas reconhecidas:** 5 (`guard_return`, `guard_throw`, `guard_block`, `ternary`, `requireNonNull`)

### Documentação

- `README.md` — manual de uso
- `ARCHITECTURE.md` — arquitetura interna detalhada
- `results/cronograma_tcc.pdf` — cronograma de entregas
- `results/missnullcheckp_variations.md` — catálogo das 25 ocorrências do padrão no Defects4J classificadas por variação

---

## Convenção de versionamento

A partir de v0.1.0-baseline, cada mudança significativa recebe uma nova
tag git, seguindo o padrão `vMAJOR.MINOR.PATCH-rótulo`:

- `v0.1.0-baseline` — primeiro detector funcional (esta versão)
- `v0.2.0-fp-filter` — próxima: filtros para reduzir falsos positivos
- `v0.3.0-multi-pattern` — futura: suporte ao segundo padrão
- `v0.4.0-llm-confirm` — futura: confirmação manual + LLM
- `v1.0.0` — entrega final do TCC

Cada nova versão atualiza este CHANGELOG com: o que mudou, o porquê, e
as métricas observadas.
