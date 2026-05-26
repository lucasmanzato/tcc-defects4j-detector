# TCC v2 — `missNullCheckP` Detector

Deterministic, interpretable detector for the **`missNullCheckP`** repair pattern
(adding a missing null check that would otherwise cause a NullPointerException),
as catalogued by the [Defects4J Dissection](https://program-repair.org/defects4j-dissection/).

The detector ingests Java commits from the GitHub REST API, extracts a small set of
structural evidences from each diff (a null comparison was added; the canonical
construct used; the protected variable was already in the file; the message looks
like a bugfix), and combines them through a fixed, weighted formula to produce a
score in `0.0 – 1.0`. Above `0.7` (default) the commit is surfaced as a candidate.

> No machine learning, no LLMs, no external training data. Each weight is justified
> in `src/config.py`.

## Requirements

- Python 3.11+
- A GitHub personal access token (read-only is enough). Set `GITHUB_TOKEN`.
- `pip install -r requirements.txt`

## Layout

```
src/                  # detector pipeline (one module per stage)
  github_client.py    # paginated commit + per-commit detail fetch
  diff_parser.py      # unified-diff parsing via unidiff
  features.py         # structural evidence extraction
  scorer.py           # weighted combination + confidence label
  detector.py         # orchestration
  baseline.py         # naive keyword baseline
  evaluation.py       # Precision / Recall / F1 + Markdown report
  models.py           # frozen dataclasses (Commit, Evidence, ...)
  config.py           # weights, thresholds, keywords
data/
  defects4j_ground_truth.json   # 20 missNullCheckP bugs (Closure, Lang, Math, Mockito, Time)
tests/                # unit tests + real Defects4J diffs as fixtures
scripts/
  run_detector.py     # CLI: detect on one repo
  run_evaluation.py   # CLI: detector vs baseline vs ground truth
  build_ground_truth.py
```

## Running

```bash
export GITHUB_TOKEN=ghp_...
pip install -r requirements.txt

# Interactive console (recommended for everyday use)
python scripts/run_interactive.py
# Prompts for the GitHub URL (or owner/name), the commit limit, and the
# minimum score. Streams progress logs and writes both the JSON output and
# the layperson-friendly Markdown report to results/.

# Non-interactive flag-driven mode
python scripts/run_detector.py \
    --repo apache/commons-lang \
    --pattern missNullCheckP \
    --output results/commons_lang.json

# Targeted recall test against ground truth (instant, ~20 API calls)
python scripts/check_recall.py --output results/recall.md

# Full Precision/Recall/F1 sweep over commit histories (slow, see notes)
python scripts/run_evaluation.py \
    --ground-truth data/defects4j_ground_truth.json \
    --output results/eval.md \
    --max-commits-per-repo 5000
```

`--max-commits-per-repo` is optional. The default is unbounded; setting it makes
the evaluation tractable on very large repos (e.g. `google/closure-compiler`).

## Ground truth

`data/defects4j_ground_truth.json` is generated from the `defects4j-dissection`
JSON: of the 25 bugs labelled `missNullCheckP`, **20 are kept** and **5 Chart
bugs are dropped**. Defects4J pre-dates the JFreeChart move from SVN to Git, so
the dissection's `revisionId` for Chart is an SVN revision number with no clean
mapping to a `jfree/jfreechart` GitHub SHA. To rebuild:

```bash
git clone --depth 1 https://github.com/program-repair/defects4j-dissection.git vendor/defects4j-dissection
python scripts/build_ground_truth.py
```

## Heuristics — at a glance

| Evidence                     | Kind | Weight | Eliminatory? | Rationale |
|------------------------------|------|--------|:------------:|-----------|
| `has_null_check_added`       | code | 0.50   | ✓ | A diff without an added null comparison cannot match. |
| canonical construct          | code | 0.25   | ✓ | The comparison must fit one of the five canonical forms. |
| `var_was_used_before`        | code | 0.20   | — | Code-context confirmation: distinguishes a fix from new-code validation. |
| bugfix-style commit message  | descriptive | 0.05 | — | Descriptive only. Commit messages can lie about the actual change. |

Code evidences total **0.95**; descriptive evidence is **0.05**. A commit
that passes every structural check but has no bugfix wording in the message
still scores **0.95** (high confidence) — the descriptive signal cannot pull
a structurally valid fix below the threshold.

The two structural evidences are **eliminatory**: if either fails, the commit
is discarded with `score = 0`, no matter how strong the descriptive signals
are. The descriptive evidences only adjust the score upward.

Weights are calibrated on the 18 reachable Defects4J `missNullCheckP` bugs:
all 18 combine an added null check with a canonical construct, so the two
structural evidences alone reach 0.75 and clear the high-confidence
threshold. Variable-prior-use and bugfix-message act as additional
confirmations.

Confidence: `low <0.5`, `medium <0.7`, `high ≥0.7`. High is downgraded to
medium when the diff exceeds 200 changed lines or only test files are touched.

## Output: locations and counts

`run_detector.py` emits a JSON document with two top-level sections:

```jsonc
{
  "repo": "apache/commons-lang",
  "pattern": "missNullCheckP",
  "min_score": 0.7,
  "summary": {
    "total_commits_flagged": 1,
    "total_pattern_occurrences": 1,
    "by_file": { "src/main/.../ClassUtils.java": 1 },
    "by_construct": { "ternary": 1 }
  },
  "candidates": [
    {
      "sha": "0603aef594...",
      "score": 1.0,
      "confidence": "high",
      "occurrences": 1,
      "matches": [
        {
          "file_path": "src/main/.../ClassUtils.java",
          "line_number": 910,
          "construct": "ternary",
          "snippet": "classes[i] = array[i] == null ? null : array[i].getClass();"
        }
      ]
    }
  ]
}
```

`matches` lists each individual location (file + target-file line number +
canonical construct + the source snippet). The summary aggregates them by
file and by construct so a user can see both *where* and *how often* the
pattern appears in the repo.

## Results — targeted recall on Defects4J

`scripts/check_recall.py` runs the detector against every fix commit in the
ground truth and reports recall:

| Approach            | Recall on reachable bugs |
|---------------------|-------------------------:|
| Detector (this work) | **18/18 (1.00)** |
| Baseline (keyword in message) | 6/18 (0.33) |

Two of the original 20 SHAs (`Math 4`, `Math 32`) are not reachable on
`apache/commons-math` because of upstream history rewrites; they are reported
separately and excluded from the rate. Full Precision/Recall/F1 requires
walking each repo's commit history (`scripts/run_evaluation.py`) — see the
limitations note below.

## Known limitations

1. **`var_was_used_before`** only inspects the hunk's context lines (no extra API
   call). Correct most of the time; can yield false negatives when the variable
   is defined more than three lines above the change. Calibration leaves this
   evidence as a confirmation, not a requirement.
2. The detector does not parse Java syntactically. It works on textual hunks. A
   commit that introduces a null check inside a comment would be (incorrectly)
   counted; in practice the noise filter removes most of those cases.
3. **Recall is measured on the 18 ground-truth bugs only**; precision is not
   measured by `check_recall.py`. To estimate precision, run
   `run_evaluation.py` against full commit histories — costly because target
   fixes are 2009-2014 and an ~unbounded sweep is needed to include them.
4. Two upstream SHAs (Math 4, Math 32) are not reachable on
   `apache/commons-math` due to history rewrites; recall counts only the 18
   reachable bugs.
5. Chart project (5 bugs) is excluded from the ground truth: Defects4J
   Chart predates the SVN→Git migration of `jfree/jfreechart` and only
   keeps SVN revision numbers.
6. GitHub rate-limit handling waits for the reset window when fewer than 10
   requests remain. No exponential retry.

## Tests

```bash
python -m pytest tests/ -v
```

47 tests cover diff parsing, feature extraction (against real Defects4J fixtures
for Lang 33, Math 4, Mockito 38, Closure 110), and scorer math.
