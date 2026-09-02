"""The hermetic end-to-end path: no API key, no network, under five seconds."""
from __future__ import annotations

import json

from evalgate import fixtures, gate, report, runner
from evalgate.adapters.mock import MockAdapter


def _cases():
    return fixtures.load_dataset()


def test_mock_adapter_is_deterministic():
    """Reruns must be identical, or the noise band measures the mock, not the agent."""
    case = _cases()[0]
    a = MockAdapter("good").run(case, 0)
    b = MockAdapter("good").run(case, 0)
    assert a.model_dump() == b.model_dump()


def test_different_trials_differ():
    """...but trials must vary, or there is no variance to measure at all."""
    case = _cases()[0]
    adapter = MockAdapter("good")
    outputs = {adapter.run(case, t).output.confidence for t in range(5)}
    assert len(outputs) > 1


def test_suite_runs_and_reports_every_metric():
    result = runner.run_suite(MockAdapter("good"), trials=3, judge="heuristic", cases=_cases())
    assert result.cases == 6
    for key in ("suspect_sha", "owner", "completed", "explanation"):
        assert key in result.intervals
    for key in ("brier", "ece", "judge_oracle_kappa", "latency_p50_s", "cost_total_usd"):
        assert key in result.scalars
    assert result.intervals["completed"].point == 1.0
    assert not result.failures


def test_good_profile_clears_the_committed_policy():
    result = runner.run_suite(MockAdapter("good"), trials=5, judge="heuristic", cases=_cases())
    verdicts = gate.evaluate(result, None, gate.load_policy())
    assert gate.passed(verdicts), [v for v in verdicts if not v.ok]


def test_degraded_profile_is_blocked():
    """The regression detector has to actually detect a regression."""
    result = runner.run_suite(MockAdapter("degraded"), trials=5, judge="heuristic", cases=_cases())
    verdicts = gate.evaluate(result, None, gate.load_policy())
    assert not gate.passed(verdicts)
    blocked = {v.metric for v in verdicts if not v.ok}
    assert "suspect_sha" in blocked
    # Overconfidence is its own failure, invisible to an accuracy-only gate.
    assert {"brier", "ece"} & blocked


def test_degraded_is_worse_than_good_on_every_headline_metric():
    good = runner.run_suite(MockAdapter("good"), trials=5, cases=_cases())
    bad = runner.run_suite(MockAdapter("degraded"), trials=5, cases=_cases())
    assert bad.intervals["suspect_sha"].point < good.intervals["suspect_sha"].point
    assert bad.scalars["brier"] > good.scalars["brier"]


def test_result_survives_a_json_round_trip(tmp_path):
    """Baselines are files. If they do not round-trip, the gate compares garbage."""
    original = runner.run_suite(MockAdapter("good"), trials=2, cases=_cases())
    path = tmp_path / "baseline.json"
    runner.save(original, path)
    restored = runner.load(path)
    assert restored.intervals["suspect_sha"].point == original.intervals["suspect_sha"].point
    assert restored.scalars == original.scalars
    assert json.loads(path.read_text(encoding="utf-8"))["adapter"] == "mock:good"


def test_reports_render_for_both_outcomes():
    result = runner.run_suite(MockAdapter("degraded"), trials=3, cases=_cases())
    verdicts = gate.evaluate(result, None, gate.load_policy())
    md = report.summary_markdown(result, verdicts)
    console = report.summary_console(result, verdicts)
    assert "BLOCKED" in md and "BLOCKED" in console
    assert "| `suspect_sha` |" in md
    for case in _cases():
        assert case.case_id in md
