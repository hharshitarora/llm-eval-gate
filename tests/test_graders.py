from __future__ import annotations

import pytest

from evalgate.graders.deterministic import grade_completed, grade_owner, grade_suspect
from evalgate.graders.judge import grade_heuristic, salient_terms
from evalgate.types import AgentOutput, GoldenCase, RunResult

SHA = "f1f6483e59ab1c2d3e4f5061728394a5b6c7d8e9"


def make_case(**over) -> GoldenCase:
    base = dict(
        case_id="c1", template="c1", difficulty="easy",
        culprit_sha=SHA, culprit_files=["app/settings.py"], expected_owner="Dana Lee",
        decoys_after=3, decoys_same_file=1, expected_error_type="KeyError",
        reference_root_cause="get_timeout in app/settings.py dropped the cfg.get default.",
    )
    base.update(over)
    return GoldenCase(**base)


def make_run(**over) -> RunResult:
    out = AgentOutput(**over.pop("output", {})) if "output" in over else None
    base = dict(case_id="c1", trial=0, ok=True, output=out)
    base.update(over)
    return RunResult(**base)


# --- suspect_sha ------------------------------------------------------------

def test_exact_sha_scores_one():
    run = make_run(output={"suspect_commit": SHA})
    assert grade_suspect(make_case(), run).value == 1.0


def test_short_prefix_is_credited():
    run = make_run(output={"suspect_commit": SHA[:10]})
    assert grade_suspect(make_case(), run).value == 1.0


def test_case_and_whitespace_insensitive():
    run = make_run(output={"suspect_commit": f"  {SHA[:12].upper()}  "})
    assert grade_suspect(make_case(), run).value == 1.0


def test_prefix_below_seven_chars_is_not_credited():
    """Guards against a 3-character 'match' scoring a point by luck."""
    run = make_run(output={"suspect_commit": SHA[:4]})
    score = grade_suspect(make_case(), run)
    assert score.value == 0.0
    assert "too short" in score.detail


def test_wrong_sha_scores_zero():
    run = make_run(output={"suspect_commit": "0" * 40})
    assert grade_suspect(make_case(), run).value == 0.0


def test_no_suspect_scores_zero():
    run = make_run(output={"suspect_commit": None})
    assert grade_suspect(make_case(), run).value == 0.0


def test_failed_run_scores_zero():
    assert grade_suspect(make_case(), make_run(ok=False, error="boom")).value == 0.0


# --- owner ------------------------------------------------------------------

def test_owner_exact_match():
    run = make_run(output={"recommended_owner": "Dana Lee"})
    assert grade_owner(make_case(), run).value == 1.0


def test_owner_surname_match_is_enough():
    run = make_run(output={"recommended_owner": "dana lee <dana@example.com>"})
    assert grade_owner(make_case(), run).value == 1.0


def test_owner_wrong_person_scores_zero():
    run = make_run(output={"recommended_owner": "Marcus Ihde"})
    assert grade_owner(make_case(), run).value == 0.0


def test_owner_unassigned_scores_zero():
    run = make_run(output={"recommended_owner": None})
    assert grade_owner(make_case(), run).value == 0.0


# --- completed --------------------------------------------------------------

def test_completed_tracks_crashes_separately():
    assert grade_completed(make_case(), make_run(output={})).value == 1.0
    assert grade_completed(make_case(), make_run(ok=False, error="timeout")).value == 0.0


# --- heuristic judge --------------------------------------------------------

def test_salient_terms_finds_identifiers_and_paths():
    terms = salient_terms("get_timeout in app/settings.py dropped the cfg.get default.")
    assert "get_timeout" in terms
    assert any("settings.py" in t for t in terms)


def test_heuristic_judge_full_credit_on_verbatim_reference():
    case = make_case()
    run = make_run(output={"root_cause_hypothesis": case.reference_root_cause})
    assert grade_heuristic(case, run).value == 1.0


def test_heuristic_judge_zero_on_unrelated_text():
    run = make_run(output={"root_cause_hypothesis": "Something went wrong somewhere."})
    assert grade_heuristic(make_case(), run).value == 0.0


def test_heuristic_judge_reports_what_was_missing():
    run = make_run(output={"root_cause_hypothesis": "get_timeout misbehaved"})
    score = grade_heuristic(make_case(), run)
    assert 0.0 < score.value < 1.0
    assert "missing" in score.detail
