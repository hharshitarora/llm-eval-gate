"""Turn a suite result into a merge decision.

Two independent reasons to block, because they catch different failures:

  * an **absolute bound** ("accuracy must be at least 0.60"), which catches an
    agent that was always bad, including on its very first run
  * a **relative regression** against the committed baseline, which catches an
    agent that was fine yesterday and is worse today

The relative check is the interesting one. A drop only counts if it exceeds the
combined bootstrap noise of the baseline and the current run. Anything smaller
is indistinguishable from rerunning the same code, and blocking on it would
train everyone to hit retry until green, which is worse than having no gate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .runner import SuiteResult

POLICY_PATH = Path("gate.json")


@dataclass(frozen=True)
class Verdict:
    metric: str
    ok: bool
    current: float
    baseline: float | None
    tolerance: float
    reason: str


def load_policy(path: Path = POLICY_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _value_and_halfwidth(result: SuiteResult, metric: str) -> tuple[float | None, float]:
    if metric in result.intervals:
        iv = result.intervals[metric]
        return iv.point, iv.half_width
    if metric in result.scalars:
        return result.scalars[metric], 0.0
    return None, 0.0


def evaluate(
    current: SuiteResult, baseline: SuiteResult | None, policy: dict
) -> list[Verdict]:
    verdicts: list[Verdict] = []

    for metric, rule in policy.get("metrics", {}).items():
        direction = rule.get("direction", "higher")
        min_tol = float(rule.get("min_tolerance", 0.0))

        value, half_now = _value_and_halfwidth(current, metric)
        if value is None:
            verdicts.append(Verdict(metric, True, 0.0, None, 0.0, "not reported by this run"))
            continue

        # --- absolute bound ---
        if direction == "higher" and "floor" in rule and value < float(rule["floor"]):
            verdicts.append(Verdict(
                metric, False, value, None, 0.0,
                f"below hard floor {float(rule['floor']):.3f}",
            ))
            continue
        if direction == "lower" and "ceiling" in rule and value > float(rule["ceiling"]):
            verdicts.append(Verdict(
                metric, False, value, None, 0.0,
                f"above hard ceiling {float(rule['ceiling']):.3f}",
            ))
            continue

        # --- relative regression ---
        if baseline is None:
            verdicts.append(Verdict(metric, True, value, None, 0.0, "no baseline yet"))
            continue

        base_value, half_base = _value_and_halfwidth(baseline, metric)
        if base_value is None:
            verdicts.append(Verdict(metric, True, value, None, 0.0, "not in baseline"))
            continue

        tolerance = max(min_tol, half_now + half_base)
        drop = (base_value - value) if direction == "higher" else (value - base_value)

        if drop > tolerance:
            verdicts.append(Verdict(
                metric, False, value, base_value, tolerance,
                f"regressed {drop:.3f} against a noise band of {tolerance:.3f}",
            ))
        else:
            detail = "within noise" if drop > 0 else "no regression"
            verdicts.append(Verdict(metric, True, value, base_value, tolerance, detail))

    return verdicts


def passed(verdicts: list[Verdict]) -> bool:
    return all(v.ok for v in verdicts)
