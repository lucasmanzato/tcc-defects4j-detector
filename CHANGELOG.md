# Histórico de versões

Este arquivo registra a evolução do detector ao longo das iterações. Cada
seção corresponde a uma versão (tag git) e descreve, em linguagem clara,
o que foi feito, por quê, e quais resultados foram observados. É um
documento auxiliar para a escrita do TCC: cita os marcos técnicos e as
métricas de cada estágio.

---

## v0.2.0-fp-filter — Filtros para reduzir falsos positivos (2026-05-02)

**Status:** funcional · recall 100% no ground truth (mantido) · FPs reduzidos
em ~29% no estudo de caso `google/error-prone`.

### Motivação

A v0.1.0 atingiu recall de 100%, mas inspeção manual dos candidatos em
repositórios reais revelou um padrão de **falso positivo**: commits que
introduzem código completamente novo (uma nova função, classe ou
funcionalidade) já vêm com `if (x == null) ...` no topo como código
defensivo. Estruturalmente, isso passa por todos os indícios da v0.1.0
mesmo não sendo correção de bug.

Esta versão adiciona dois novos sinais estruturais que distinguem
*fix de bug existente* de *código novo defensivo*.

### O que mudou

#### Sinal 1 — "A linha desprotegida foi REMOVIDA?" (positivo)

Nova evidência `fix_replaces_existing_use`: True quando a variável que está
sendo protegida pelo null check **também aparece nas linhas removidas** do
mesmo arquivo. Isso é a assinatura clássica de uma correção:

```diff
- classes[i] = array[i].getClass();              ← array usado SEM proteção
+ classes[i] = array[i] == null ? ... : ...      ← array agora protegido
```

Peso: **0,15** (forte sinal positivo, redistribuído de `var_was_used_before`).

#### Sinal 2 — "É adição pura de método novo?" (negativo)

Nova evidência `adds_new_method_declaration`: True quando o arquivo:
1. Adiciona declaração de método, classe, interface, enum ou record, E
2. Não tem nenhuma linha removida (adição pura).

A segunda condição é o que protege correções legítimas que extraem
métodos auxiliares — refactor + fix é comum e não deve ser penalizado.

Penalidade: **-0,20** no score final, com clamp em 0.

### Novos pesos

```
W_NULL_CHECK_ADDED       = 0,50  (eliminatório, inalterado)
W_CANONICAL_CONSTRUCT    = 0,25  (eliminatório, inalterado)
W_FIX_REPLACES_USE       = 0,15  ← novo
W_VAR_USED_BEFORE        = 0,05  (reduzido de 0,20)
W_BUGFIX_MESSAGE         = 0,05  (inalterado)
PENALTY_ADDS_NEW_METHOD  = -0,20 ← novo
```

Soma dos positivos: 1,00. Penalidade subtraída no fim. Score final
sempre em [0,0; 1,0].

### Cálculo no caso real (bugfix do Lang 33)

```
+ classes[i] = array[i] == null ? null : array[i].getClass();
- classes[i] = array[i].getClass();
```

- null check adicionado: +0,50
- ternário (canônico): +0,25
- "array" também aparece em linha removida: +0,15 (Sinal 1 dispara)
- "array" no contexto do hunk: +0,05
- mensagem "[LANG-587] avoid NPE": +0,05
- nenhum método novo declarado: penalty=0
- **Total: 1,00 ✓** (mesmo score da v0.1.0 para esse fix)

### Cálculo no caso falso positivo (código novo defensivo)

```
+ public Result process(Input input) {
+   if (input == null) return Result.empty();
+   return Result.ok(input.value());
+ }
```

- null check adicionado: +0,50
- guard_return (canônico): +0,25
- "input" NÃO aparece em linha removida: +0
- "input" no contexto: +0
- mensagem sem keyword: +0
- declaração de método nova em adição pura: penalty -0,20
- **Total: 0,55 < 0,70 → descartado ✓**

### Métricas após a mudança

Validação contra ground truth (Defects4J Dissection):

| Approach | Recall v0.1.0 | Recall v0.2.0 |
|----------|--------------:|--------------:|
| Detector | 18/18 (100%) | **18/18 (100%)** |
| Baseline | 6/18 (33%) | 6/18 (33%) |

Estudos de caso (mesmos repos, mesmo `--limit 500`):

| Repo | v0.1.0 commits flagrados | v0.2.0 commits flagrados | Redução |
|------|-----------------------:|-----------------------:|--------:|
| google/error-prone | 49 | 35 | **−29%** |
| JodaOrg/joda-time | 9 | 8 | −11% |

### Observação metodológica importante

Durante a calibração, três bugs do ground truth (Closure 43, 103, 127)
foram brevemente perdidos porque o detector inicial de `adds_new_method`
disparava em qualquer adição de método. Inspeção dos diffs reais
mostrou que esses commits **são refatorações + fix** — extraem método
helper e adicionam null check.

A correção foi tornar o sinal *condicional*: só dispara quando o
arquivo é adição pura (sem remoções). Isso preserva o recall completo
sem perder o poder de filtrar FPs verdadeiros (que são, por definição,
adições puras de código novo).

### Componentes desta versão

- **Pipeline:** 10 módulos em `src/` (inalterado)
- **Scripts CLI:** 7 (inalterado)
- **Testes:** 71 (era 57 — +14 cobrindo os novos sinais)
- **Padrões cobertos:** 1 (`missNullCheckP`)
- **Variações sintáticas reconhecidas:** 5 (inalterado)

### Limitação que permanece

O sinal `adds_new_method_declaration` é **conservador** (só dispara em
adição pura). Pode haver FPs onde o commit também remove algumas linhas
não relacionadas (logging, comentários, formatação) e, ainda assim, o
núcleo do código é adição de nova feature. Iterações futuras podem
explorar essa fronteira com sinais mais refinados.

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
