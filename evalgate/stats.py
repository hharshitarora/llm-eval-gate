"""The statistics that make a gate meaningful instead of superstitious.

The problem this module exists to solve: an agent's score moves between
identical runs. If accuracy is 0.83 today and 0.78 tomorrow with no code change,
a naive `if new < baseline: fail` gate fires constantly, everyone learns to
re-run it until it passes, and the gate is now decoration.

So the gate needs to know how much the number moves *on its own*. That is what
`bootstrap_ci` measures, over trials the harness deliberately ran more than once
per case. The tolerance is derived from observed noise, not picked by feel.

Calibration gets its own treatment because the agent emits a confidence field.
An agent that is 70% accurate and says so is far more useful on-call than one
that is 70% accurate and says 95%, and accuracy alone cannot tell them apart.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float

    @property
    def half_width(self) -> float:
        return max(self.high - self.point, self.point - self.low)

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.low:.3f}, {self.high:.3f}]"


def bootstrap_ci(
    values: list[float], *, confidence: float = 0.95, iterations: int = 2000, seed: int = 20260101
) -> Interval:
    """Percentile bootstrap over per-observation scores.

    Seeded so two runs of the harness on identical data produce identical
    intervals. A gate whose threshold wobbles is no better than the metric
    wobbling.
    """
    values = list(values)
    if not values:
        return Interval(0.0, 0.0, 0.0)
    point = mean(values)
    if len(values) == 1:
        return Interval(point, point, point)

    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iterations):
        means.append(mean(values[rng.randrange(n)] for _ in range(n)))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    return Interval(point, _percentile(means, tail), _percentile(means, 1.0 - tail))


def bootstrap_ci_clustered(
    groups: list[list[float]], *, confidence: float = 0.95,
    iterations: int = 2000, seed: int = 20260101,
) -> Interval:
    """Bootstrap that resamples *cases*, not individual runs.

    This matters more than it looks. Five trials of `zero_division` are five
    looks at the same question, so they move together; treating them as thirty
    independent observations reports a tighter interval than the data supports
    and quietly makes the gate trigger-happy.

    Resampling whole cases keeps the clustering intact. The honest interval is
    wider, which is the correct answer: with a six-case set most of the
    uncertainty is "which cases are in the set", not "how did the coin land".
    """
    groups = [g for g in groups if g]
    if not groups:
        return Interval(0.0, 0.0, 0.0)

    flat = [v for g in groups for v in g]
    point = mean(flat)
    if len(groups) == 1:
        return Interval(point, point, point)

    rng = random.Random(seed)
    k = len(groups)
    means = []
    for _ in range(iterations):
        drawn: list[float] = []
        for _ in range(k):
            drawn.extend(groups[rng.randrange(k)])
        means.append(mean(drawn))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    return Interval(point, _percentile(means, tail), _percentile(means, 1.0 - tail))


def brier_score(confidences: list[float], outcomes: list[float]) -> float:
    """Mean squared error between stated confidence and what happened.

    0 is perfect. 0.25 is what you get by always saying 50%. Above that the
    confidence field is actively misleading.
    """
    if not confidences:
        return 0.0
    return mean((c - o) ** 2 for c, o in zip(confidences, outcomes))


def expected_calibration_error(
    confidences: list[float], outcomes: list[float], bins: int = 10
) -> float:
    """Weighted gap between stated confidence and observed accuracy, per bin.

    Complements Brier: Brier mixes calibration with raw accuracy, ECE isolates
    the "does 90% mean 90%" question that an on-call engineer is really asking.
    """
    if not confidences:
        return 0.0
    n = len(confidences)
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i for i, c in enumerate(confidences)
            if (lo < c <= hi) or (b == 0 and c <= hi)
        ]
        if not idx:
            continue
        acc = mean(outcomes[i] for i in idx)
        conf = mean(confidences[i] for i in idx)
        total += (len(idx) / n) * abs(acc - conf)
    return total


def cohens_kappa(a: list[int], b: list[int]) -> float:
    """Chance-corrected agreement between two binary raters.

    Used to check the LLM judge against the objective signal. Raw agreement
    flatters a judge on a skewed dataset: if 85% of runs are correct, a judge
    that says "correct" every time scores 85% agreement while being useless.
    Kappa scores that judge at 0, which is the point.
    """
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for cls in (0, 1):
        pe += (a.count(cls) / n) * (b.count(cls) / n)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)
