"""Precision / Recall / F1 metrics and markdown report rendering."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import CommitCandidate


@dataclass(frozen=True)
class Metrics:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def evaluate(predicted_shas: set[str], truth_shas: set[str]) -> Metrics:
    """Compute Precision / Recall / F1 for a set of predicted SHAs."""
    tp = len(predicted_shas & truth_shas)
    fp = len(predicted_shas - truth_shas)
    fn = len(truth_shas - predicted_shas)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return Metrics(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn)


def render_report(
    detector_metrics: Metrics,
    baseline_metrics: Metrics,
    detector_candidates: Iterable[CommitCandidate],
    truth_shas: set[str],
) -> str:
    """Render the evaluation report as Markdown."""
    candidates = list(detector_candidates)
    predicted_shas = {c.commit.sha for c in candidates}
    fps = [c for c in candidates if c.commit.sha not in truth_shas]
    fns = sorted(truth_shas - predicted_shas)

    lines: list[str] = []
    lines.append("# missNullCheckP — Evaluation Report\n")
    lines.append("## Metrics: detector vs baseline\n")
    lines.append("| Approach | Precision | Recall | F1 | TP | FP | FN |")
    lines.append("|----------|-----------|--------|----|----|----|----|")
    lines.append(_metric_row("Detector", detector_metrics))
    lines.append(_metric_row("Baseline (keyword)", baseline_metrics))
    lines.append("")

    lines.append("## False positives (detector predicted but not in ground truth)\n")
    if fps:
        for c in fps:
            lines.append(
                f"- `{c.commit.sha[:10]}` score={c.score:.2f} "
                f"({c.confidence}) — {_first_line(c.commit.message)}"
            )
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## False negatives (ground-truth fixes the detector missed)\n")
    if fns:
        for sha in fns:
            lines.append(f"- `{sha[:10]}`")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Score distribution (detector)\n")
    bucket_counts = _score_buckets(c.score for c in candidates)
    if not candidates:
        lines.append("_No candidates returned._")
    else:
        lines.append("| Bucket | Count |")
        lines.append("|--------|-------|")
        for bucket, count in bucket_counts:
            lines.append(f"| {bucket} | {count} |")
    lines.append("")
    return "\n".join(lines)


def _metric_row(name: str, m: Metrics) -> str:
    return (
        f"| {name} | {m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} "
        f"| {m.tp} | {m.fp} | {m.fn} |"
    )


def _first_line(message: str) -> str:
    line = message.splitlines()[0] if message else ""
    return line[:100]


def _score_buckets(scores: Iterable[float]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    labels = [
        ("0.70-0.79", 0.70, 0.80),
        ("0.80-0.89", 0.80, 0.90),
        ("0.90-1.00", 0.90, 1.01),
    ]
    for s in scores:
        for label, lo, hi in labels:
            if lo <= s < hi:
                counter[label] += 1
                break
    return [(label, counter[label]) for label, _, _ in labels]
