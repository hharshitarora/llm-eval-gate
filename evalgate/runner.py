"""Run the suite and reduce it to a comparable set of metrics.

Every case is run `trials` times. That is the whole reason this harness can
gate anything: one run per case gives a number with no error bar, and a number
with no error bar cannot be compared to last week's number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_dataset
from .graders.deterministic import grade_completed, grade_owner, grade_suspect
from .graders.judge import get_judge
from .stats import (
    Interval,
    bootstrap_ci_clustered,
    brier_score,
    cohens_kappa,
    expected_calibration_error,
    mean,
    _percentile,
)
from .types import GoldenCase, RunResult, Score


@dataclass
class SuiteResult:
    adapter: str
    judge: str
    trials: int
    cases: int
    intervals: dict[str, Interval] = field(default_factory=dict)
    scalars: dict[str, float] = field(default_factory=dict)
    per_case: dict[str, dict[str, float]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "adapter": self.adapter,
            "judge": self.judge,
            "trials": self.trials,
            "cases": self.cases,
            "intervals": {
                k: {"point": v.point, "low": v.low, "high": v.high}
                for k, v in self.intervals.items()
            },
            "scalars": self.scalars,
            "per_case": self.per_case,
            "failures": self.failures,
        }

    @staticmethod
    def from_dict(data: dict) -> "SuiteResult":
        res = SuiteResult(
            adapter=data.get("adapter", "?"),
            judge=data.get("judge", "?"),
            trials=int(data.get("trials", 1)),
            cases=int(data.get("cases", 0)),
        )
        for key, iv in data.get("intervals", {}).items():
            res.intervals[key] = Interval(iv["point"], iv["low"], iv["high"])
        res.scalars = dict(data.get("scalars", {}))
        res.per_case = dict(data.get("per_case", {}))
        res.failures = list(data.get("failures", []))
        return res


def run_suite(adapter, *, trials: int = 3, judge: str = "heuristic",
              judge_model: str | None = None, cases: list[GoldenCase] | None = None) -> SuiteResult:
    cases = cases if cases is not None else load_dataset()
    judge_fn = get_judge(judge, judge_model)  # type: ignore[arg-type]

    runs: list[RunResult] = []
    scores: dict[str, list[Score]] = {"suspect_sha": [], "owner": [], "completed": [], "explanation": []}

    for case in cases:
        for trial in range(trials):
            run = adapter.run(case, trial)
            runs.append(run)
            scores["suspect_sha"].append(grade_suspect(case, run))
            scores["owner"].append(grade_owner(case, run))
            scores["completed"].append(grade_completed(case, run))
            scores["explanation"].append(judge_fn(case, run))

    result = SuiteResult(
        adapter=getattr(adapter, "name", "unknown"),
        judge=judge,
        trials=trials,
        cases=len(cases),
    )

    case_order = [c.case_id for c in cases]
    for name, items in scores.items():
        by_case = {cid: [] for cid in case_order}
        for s in items:
            by_case[s.case_id].append(s.value)
        result.intervals[name] = bootstrap_ci_clustered(list(by_case.values()))

    # --- calibration: does a stated confidence mean anything? ---
    confidences, outcomes = [], []
    for run, sha_score in zip(runs, scores["suspect_sha"]):
        if run.ok and run.output is not None:
            confidences.append(run.output.confidence)
            outcomes.append(sha_score.value)
    result.scalars["brier"] = round(brier_score(confidences, outcomes), 4)
    result.scalars["ece"] = round(expected_calibration_error(confidences, outcomes), 4)

    # --- is the judge worth listening to? ---
    judge_binary = [1 if s.value >= 0.5 else 0 for s in scores["explanation"]]
    oracle_binary = [1 if s.value >= 0.5 else 0 for s in scores["suspect_sha"]]
    result.scalars["judge_oracle_kappa"] = round(cohens_kappa(judge_binary, oracle_binary), 4)

    latencies = sorted(r.latency_s for r in runs)
    result.scalars["latency_p50_s"] = round(_percentile(latencies, 0.50), 3)
    result.scalars["latency_p95_s"] = round(_percentile(latencies, 0.95), 3)
    result.scalars["cost_total_usd"] = round(sum(r.cost_usd for r in runs), 4)

    # --- per-case, so a report can point at what actually broke ---
    for case in cases:
        result.per_case[case.case_id] = {
            name: round(mean(s.value for s in items if s.case_id == case.case_id), 3)
            for name, items in scores.items()
        }
        result.per_case[case.case_id]["difficulty"] = case.difficulty  # type: ignore[assignment]

    result.failures = [
        f"{r.case_id}[{r.trial}]: {r.error}" for r in runs if not r.ok
    ][:20]
    return result


def save(result: SuiteResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(result.to_dict(), fh, indent=2)
        fh.write("\n")


def load(path: Path) -> SuiteResult:
    with open(path, encoding="utf-8") as fh:
        return SuiteResult.from_dict(json.load(fh))
