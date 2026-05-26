"""Tunable constants for the missNullCheckP detector.

All weights and thresholds live here so the scorer module stays purely about
the math. Each value carries a comment explaining the rationale derived from
inspecting the 20 missNullCheckP bugs in defects4j-dissection.
"""
from __future__ import annotations

# --- score weights (must sum to 1.0) -----------------------------------------
# Calibration is grounded on the 18 reachable missNullCheckP bugs from the
# Defects4J ground truth: 18/18 of them combine an added null check with a
# canonical construct, so the two structural evidences alone must clear the
# 0.7 threshold. The remaining two evidences (variable previously seen,
# bugfix-style message) act as confirmations that boost confidence and help
# disambiguate from defensive validation introduced in brand-new code.

# Adding a null check is the necessary signal: its absence rules the
# candidate out entirely. (Eliminatory.)
W_NULL_CHECK_ADDED = 0.50

# A canonical guard, ternary, or requireNonNull form distinguishes a real
# repair from a one-off comparison embedded in unrelated logic. (Eliminatory.)
W_CANONICAL_CONSTRUCT = 0.25

# Code-context evidence: the protected variable was already referenced before
# the patch. Strong confirmation that the change is a fix to existing logic
# rather than eager validation around a freshly introduced variable.
W_VAR_USED_BEFORE = 0.20

# Descriptive evidence only: bugfix-style language in the commit message
# ("npe", "fix null", ...). Kept very low because commit messages are
# unreliable: the actual code change is the source of truth. Removing it
# from a candidate that already passes the structural checks must still
# leave a near-perfect score (1.00 - 0.05 = 0.95).
W_BUGFIX_MESSAGE = 0.05

# --- confidence thresholds (high >= 0.7 per project requirement) -------------
SCORE_LOW_MAX = 0.5
SCORE_MEDIUM_MAX = 0.7

# --- detector defaults -------------------------------------------------------
# Minimum score to surface a commit as a candidate. Project target is high
# similarity, so we keep the cut at 0.7.
DEFAULT_MIN_SCORE = 0.7

# --- noise / size penalties --------------------------------------------------
# Commits larger than this many changed lines are considered too noisy for the
# heuristic; we cap their confidence at "medium" even if the score is high.
LARGE_DIFF_LINES = 200

# --- bugfix message keywords -------------------------------------------------
BUGFIX_KEYWORDS: tuple[str, ...] = (
    "npe",
    "nullpointerexception",
    "null pointer",
    "null check",
    "null-check",
    "nullcheck",
    "avoid null",
    "guard against null",
    "fix null",
    "handle null",
    "missing null",
    "fixes #",
    "bug fix",
    "bugfix",
)

# --- diff filtering ----------------------------------------------------------
# Only files whose path ends with one of these extensions are kept when a
# commit is materialised from the GitHub API. The detector is designed for
# Java; any commit that touches only non-Java files (Python, Markdown, YAML,
# configuration, etc.) produces an empty file list and is automatically
# discarded by the scorer (no null check possible → score 0). Centralising
# the list here lets the project be retargeted to another language without
# touching the pipeline.
ANALYZED_EXTENSIONS: tuple[str, ...] = (".java",)

JAVA_TEST_PATH_MARKERS: tuple[str, ...] = ("/test/", "/tests/", "Test.java", "Tests.java")
