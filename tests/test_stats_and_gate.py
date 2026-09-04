from __future__ import annotations

from evalgate.gate import evaluate, passed
from evalgate.runner import SuiteResult
from evalgate.stats import (
    Interval,
    bootstrap_ci,
    bootstrap_ci_clustered,
    brier_score,
    cohens_kappa,
    expected_calibration_error,
)

POLICY = {
    "metrics": {
        "suspect_sha": {"direction": "higher", "floor": 0.55, "min_tolerance": 0.05},
        "brier": {"direction": "lower", "ceiling": 0.25, "min_tolerance": 0.03},
    }
}


# --- stats ------------------------------------------------------------------

def test_bootstrap_is_reproducible():
    """A gate whose threshold moves between runs is not a gate."""
    values = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0]
    assert bootstrap_ci(values) == bootstrap_ci(values)


def test_bootstrap_brackets_the_point_estimate():
    iv = bootstrap_ci([1.0, 0.0] * 20)
    assert iv.low <= iv.point <= iv.high


def test_clustered_bootstrap_is_wider_than_naive():
    """The whole reason the clustered version exists.

    Five identical trials per case carry no more information than one, so
    honest error bars must be wider than treating them as 25 independent draws.
    """
    groups = [[1.0] * 5, [1.0] * 5, [0.0] * 5, [1.0] * 5, [0.0] * 5]
    flat = [v for g in groups for v in g]
    assert bootstrap_ci_clustered(groups).half_width > bootstrap_ci(flat).half_width


def test_empty_inputs_do_not_explode():
    assert bootstrap_ci([]) == Interval(0.0, 0.0, 0.0)
    assert bootstrap_ci_clustered([]) == Interval(0.0, 0.0, 0.0)
    assert brier_score([], []) == 0.0
    assert expected_calibration_error([], []) == 0.0


def test_brier_rewards_honest_confidence():
    confident_and_right = brier_score([0.95, 0.95], [1.0, 1.0])
    confident_and_wrong = brier_score([0.95, 0.95], [0.0, 0.0])
    hedged = brier_score([0.5, 0.5], [1.0, 0.0])
    assert confident_and_right < hedged < confident_and_wrong


def test_ece_is_zero_for_a_perfectly_calibrated_agent():
    # Says 90% ten times, is right nine of them.
    conf = [0.9] * 10
    out = [1.0] * 9 + [0.0]
    assert expected_calibration_error(conf, out) < 1e-9


def test_ece_catches_overconfidence_that_accuracy_alone_misses():
    conf = [0.95] * 10
    out = [1.0] * 5 + [0.0] * 5
    assert expected_calibration_error(conf, out) > 0.4


def test_kappa_punishes_a_constant_rater():
    """A judge that always says 'good' has high raw agreement and zero skill."""
    oracle = [1] * 17 + [0] * 3
    always_yes = [1] * 20
    raw_agreement = sum(1 for a, b in zip(oracle, always_yes) if a == b) / len(oracle)
    assert raw_agreement == 0.85
    assert cohens_kappa(always_yes, oracle) == 0.0


def test_kappa_perfect_and_mismatched():
    assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert cohens_kappa([], []) == 0.0
    assert cohens_kappa([1, 0], [1]) == 0.0


# --- gate -------------------------------------------------------------------

def _result(sha_point: float, brier: float, half: float = 0.05) -> SuiteResult:
    res = SuiteResult(adapter="test", judge="heuristic", trials=3, cases=6)
    res.intervals["suspect_sha"] = Interval(sha_point, sha_point - half, sha_point + half)
    res.scalars["brier"] = brier
    return res


def test_first_run_passes_with_no_baseline():
    verdicts = evaluate(_result(0.9, 0.05), None, POLICY)
    assert passed(verdicts)
    assert any("no baseline" in v.reason for v in verdicts)


def test_hard_floor_blocks_even_without_a_baseline():
    verdicts = evaluate(_result(0.40, 0.05), None, POLICY)
    assert not passed(verdicts)
    assert any(v.metric == "suspect_sha" and "floor" in v.reason for v in verdicts)


def test_small_drop_inside_the_noise_band_passes():
    """The point of the whole design: do not fail on run-to-run wobble."""
    baseline = _result(0.90, 0.05)
    current = _result(0.86, 0.05)
    verdicts = evaluate(current, baseline, POLICY)
    assert passed(verdicts)
    assert any("within noise" in v.reason for v in verdicts)


def test_large_drop_beyond_the_noise_band_blocks():
    baseline = _result(0.90, 0.05, half=0.02)
    current = _result(0.62, 0.05, half=0.02)
    verdicts = evaluate(current, baseline, POLICY)
    assert not passed(verdicts)
    assert any("regressed" in v.reason for v in verdicts)


def test_lower_is_better_metric_blocks_when_it_rises():
    verdicts = evaluate(_result(0.9, 0.40), _result(0.9, 0.05), POLICY)
    assert not passed(verdicts)
    assert any(v.metric == "brier" and "ceiling" in v.reason for v in verdicts)


def test_improvement_never_blocks():
    verdicts = evaluate(_result(0.98, 0.02), _result(0.80, 0.10), POLICY)
    assert passed(verdicts)


def test_metric_absent_from_run_is_skipped_not_failed():
    res = SuiteResult(adapter="test", judge="heuristic", trials=3, cases=6)
    verdicts = evaluate(res, None, POLICY)
    assert passed(verdicts)
    assert all("not reported" in v.reason for v in verdicts)


# --- baselines are per adapter ----------------------------------------------

def test_baseline_path_is_keyed_by_adapter():
    """A triage run must never be compared against mock numbers.

    They measure different systems, so the comparison is not noisy, it is
    meaningless. Keying by adapter makes that mistake unrepresentable rather
    than something to remember.
    """
    from evalgate.cli import baseline_path

    assert baseline_path("mock:good").name == "mock-good.json"
    assert baseline_path("mock:degraded").name == "mock-degraded.json"
    assert baseline_path("triage").name == "triage.json"
    assert baseline_path("mock:good") != baseline_path("triage")


def test_baseline_path_survives_awkward_adapter_names():
    from evalgate.cli import baseline_path

    assert baseline_path("Weird/Name v2").name == "weird-name-v2.json"
    assert baseline_path("").name == "unknown.json"
    assert baseline_path("///").name == "unknown.json"
