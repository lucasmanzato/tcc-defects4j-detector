# Histórico de versões

Este arquivo registra a evolução do detector ao longo das iterações. Cada
seção corresponde a uma versão (tag git) e descreve, em linguagem clara,
o que foi feito, por quê, e quais resultados foram observados. É um
documento auxiliar para a escrita do TCC: cita os marcos técnicos e as
métricas de cada estágio.

---

## v0.3.0-multi-pattern — Suporte a múltiplos padrões (2026-06-02)

**Status:** em desenvolvimento · adiciona o padrão `condBlockRetAdd` ao lado
do `missNullCheckP`, demonstrando que a arquitetura é genérica e
extensível.

### Por que `condBlockRetAdd` e não `wrongComp`

A escolha do segundo padrão passou por uma análise empírica documentada
para fins de defesa do TCC.

**Tentativa inicial: `wrongComp` (58 bugs no Defects4J Dissection)**

O nome sugere "comparação errada" — supus que se tratava de troca de
operador (`<` ↔ `<=`, `==` ↔ `!=`, etc.). Seria estruturalmente
detectável: comparar operadores nas linhas removidas vs. adicionadas.

Ao examinar os 58 bugs reais classificados sob esse padrão no Defects4J,
descobri que:

- **1 / 58** é troca pura de operador (Lang 50: `!=` → `==`)
- **7 / 58** mudam o operando da comparação (typos de variável)
- **50 / 58** são refatorações complexas envolvendo comparações
  (substituem método inteiro, mudam comparação por iteração, etc.)

`wrongComp` no catálogo é uma categoria **semântica** ("o bug envolve
comparação errada"), não **estrutural** ("o diff mostra troca de
operador"). Detectar isso via regex daria recall de ~10% — não validaria
a arquitetura.

**Escolha final: `condBlockRetAdd` (77 bugs, 68 sem overlap com
`missNullCheckP`)**

Esse padrão é estruturalmente bem definido: "o fix adicionou um bloco
`if (condição) { return ...; }` (ou sua forma compacta de uma linha)".

Argumentos da escolha:

1. **Estruturalmente detectável** — ~95% dos casos cabem na máscara
   regex, ao contrário dos ~10% do `wrongComp`.
2. **Ground truth grande e independente** — 77 bugs, 68 sem overlap com
   `missNullCheckP`.
3. **Generalização forte para o TCC** — `missNullCheckP guard_return`
   é um *caso particular* de `condBlockRetAdd` onde a condição é
   `(x == null)`. Mostrar os dois padrões evidencia que o sistema é uma
   **plataforma genérica** com casos especiais especializados.
4. **Reuso arquitetural** — os sinais introduzidos na v0.2.0
   (`fix_replaces_existing_use`, `adds_new_method_declaration`) se
   aplicam diretamente, validando que esses sinais são *transversais*
   aos padrões e não específicos do null check.

A tentativa frustrada com `wrongComp` é material direto para a seção de
metodologia do TCC: ilustra o **processo iterativo** de escolha de
padrões e a importância da **inspeção empírica** antes de comprometer
implementação.

### Arquitetura introduzida

Para suportar múltiplos padrões sem acoplar o pipeline a nenhum deles,
extraímos o detector para um pacote dedicado:

```
src/patterns/
  __init__.py                # registry: PATTERNS dict
  base.py                    # PatternDetector ABC + BaseEvidence
  miss_null_check_p.py       # detector existente migrado
  cond_block_ret_add.py      # detector novo
```

Cada padrão é uma classe que implementa quatro métodos (`extract_evidence`,
`score`, `confidence_level`, `find_matches`) e mora num único arquivo
com sua própria regex, seu Evidence dataclass e seus pesos. Adicionar um
terceiro padrão no futuro é uma operação local: 1 arquivo novo +
registrar no `__init__.py`. Nada na orquestração (cliente GitHub, parser
de diff, CLIs, relatório) muda.

### O detector novo

Reconhece quatro formas canônicas de `if (cond) return`:

| Forma | Exemplo |
|---|---|
| `bare_return` | `if (!ready) { return; }` |
| `return_value` | `if (n.isDelProp()) { return true; }` |
| `return_expression` | `if (size > MAX) { return defaultValue(); }` |
| `compact_one_line` | `if (foo == null) return null;` |

A condição é extraída por um **parser de parênteses balanceados**, não
regex. Isso é o que permite reconhecer:

- Chamadas aninhadas: `if (Modifier.isAbstract(invocation.getMethod().getModifiers()))`
- Condições multi-linha:
  ```java
  if (var != null
      && var.getParentNode().isCatch()) {
  ```

A regex original não suportava paren-aninhado e detectava apenas ~86% do
ground truth; após a substituição pelo parser, subimos para 95%, e
removendo a penalidade `adds_new_method_declaration` (semanticamente
inadequada para este padrão), atingimos **98% (57/58)**.

### Calibração dos pesos

Idêntica à v0.2.0 do `missNullCheckP`, com uma diferença documentada:

| Peso | missNullCheckP | condBlockRetAdd |
|---|---|---|
| `W_*_ADDED` (eliminatório) | 0,50 | 0,50 |
| `W_CANONICAL_*` (eliminatório) | 0,25 | 0,25 |
| `W_FIX_REPLACES_USE` | 0,15 | 0,15 |
| `W_VAR_USED_BEFORE` | 0,05 | 0,05 |
| `W_BUGFIX_MESSAGE` | 0,05 | 0,05 |
| `PENALTY_ADDS_NEW_METHOD` | -0,20 | **(omitido)** |

O motivo da omissão da penalidade para `condBlockRetAdd`: adicionar um
guard-return no topo de um método recém-declarado é uma forma frequente
de fix legítimo (override de `equals`/`compareTo` que checa o tipo logo
no começo — Lang 23 e Lang 64 do ground truth são exatamente isso). No
`missNullCheckP` o mesmo cenário caracteriza código defensivo novo
(falso positivo); a polaridade do sinal **muda entre padrões**.

### Métricas observadas

| Padrão | Bugs alcançáveis | Recall | Baseline |
|---|---:|---:|---:|
| `missNullCheckP` | 18 | **100% (18/18)** | 33% |
| `condBlockRetAdd` | 58 | **98% (57/58)** | 2% |

Estudo de caso comparativo (`apache/commons-lang`, últimos 500 commits):

| Padrão | Commits flagrados | Pontos no código | Arquivos |
|---|---:|---:|---:|
| `missNullCheckP` | 15 | 20 | 12 |
| `condBlockRetAdd` | 25 | 63 | 16 |

O `condBlockRetAdd` flagra mais commits, como esperado (padrão mais
amplo). Os top candidatos coincidem em vários casos com `missNullCheckP`
(`Fix NullPointerException...` em `ReflectionDiffBuilder`), confirmando
empiricamente que `missNullCheckP guard_return` é um caso particular de
`condBlockRetAdd`.

### Menu interativo

O CLI `scripts/run_interactive.py` agora pergunta:

1. URL ou `owner/name` do repositório
2. Qual padrão buscar (`missNullCheckP`, `condBlockRetAdd`, ou *ambos*)

Os outros parâmetros continuam no default (`limit=500`, `min_score=0.7`).
A lista de padrões é montada dinamicamente a partir do registry, então
adicionar uma terceira opção no futuro aparece automaticamente no menu.
Arquivos de saída ganham sufixo do padrão (`<repo>__<pattern>.json`)
para não sobreescreverem quando os dois padrões rodam no mesmo repo.

### Limitação documentada

O único bug do ground truth de `condBlockRetAdd` que o detector não
encontra é **Closure 94**: a correção introduz um `case X: return Y;`
dentro de um `switch`, em vez de um `if`. A máscara estrutural é
deliberadamente restrita a `if`-guards (forma mais comum nos 71 bugs do
ground truth); estender para `switch-case` exigiria reformular a base
da regra. Marcado como trabalho futuro.

### Componentes desta versão

- **Pipeline:** 11 módulos em `src/` (incluindo `src/patterns/` com 4 arquivos)
- **Scripts CLI:** 8 (novo: `build_ground_truth_cond_block_ret_add.py`)
- **Testes:** 94 (era 71 — +23 cobrindo o novo padrão)
- **Padrões cobertos:** 2 (`missNullCheckP`, `condBlockRetAdd`)
- **Ground truth:** 20 bugs (missNullCheckP) + 71 bugs (condBlockRetAdd)

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
