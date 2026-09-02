"""Grading the one thing a string comparison cannot: the explanation.

Two judges ship here, and the choice between them is a real trade-off rather
than a fallback.

`heuristic` is deterministic, free, and runs in CI. It measures how many of the
reference explanation's salient terms (identifiers, file paths, code-shaped
tokens) survive into the agent's hypothesis. It cannot recognise a correct
explanation phrased differently, and it says so in its own docstring rather than
pretending otherwise.

`llm` reads for meaning and is the honest grader of explanation quality, but it
costs money, drifts with the vendor's model, and is itself a fallible model
whose agreement with the objective signal has to be measured. `stats.kappa`
does that measuring; the run report prints it every time.
"""
from __future__ import annotations

import re
from typing import Literal

from ..types import GoldenCase, RunResult, Score

# Code-shaped tokens: snake_case identifiers, dotted paths, file names.
_SALIENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+|[a-z][a-z0-9]*_[a-z0-9_]+")

_STOP = {"is_none", "self_", "the_", "a_b"}


def salient_terms(text: str) -> set[str]:
    """Identifiers and paths worth checking for. Deliberately narrow."""
    found = {m.group(0).lower().rstrip(".") for m in _SALIENT.finditer(text)}
    return {t for t in found if t not in _STOP and len(t) > 3}


def grade_heuristic(case: GoldenCase, run: RunResult) -> Score:
    """Salient-term recall of the reference explanation. Free and deterministic.

    A proxy, not a semantic judge. It will under-credit a correct explanation
    that uses different words, which is precisely why the LLM judge exists and
    why their disagreement is reported rather than hidden.
    """
    if not run.ok or run.output is None:
        return Score(grader="explanation", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="no output")

    want = salient_terms(case.reference_root_cause)
    if not want:
        return Score(grader="explanation", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="reference has no salient terms")

    got = run.output.root_cause_hypothesis.lower()
    hits = {t for t in want if t in got}
    value = len(hits) / len(want)
    missed = sorted(want - hits)[:4]
    return Score(
        grader="explanation", case_id=case.case_id, trial=run.trial,
        value=round(value, 4),
        detail="" if value == 1.0 else f"missing: {', '.join(missed)}",
    )


_RUBRIC = """You are grading an incident-triage agent's root-cause explanation.

REFERENCE (the known-correct explanation, written by the engineer who planted the bug):
{reference}

AGENT'S EXPLANATION:
{hypothesis}

Score 0-3 on whether the agent identified the same underlying mechanism:
  3 - same mechanism, correctly described
  2 - right mechanism, imprecise or partially described
  1 - related to the right area but the mechanism is wrong
  0 - wrong, or too vague to be actionable

Judge the mechanism only. Different wording, extra detail, or a different writing
style are all fine. Do not reward confidence or fluency."""


def _llm_judge_factory(model: str | None = None):
    """Built lazily so importing this module never requires an API key."""
    from pydantic import BaseModel, Field

    from ..llm import structured

    class Verdict(BaseModel):
        score: int = Field(ge=0, le=3, description="0-3 per the rubric")
        reason: str = Field(description="one short sentence")

    def grade_llm(case: GoldenCase, run: RunResult) -> Score:
        if not run.ok or run.output is None:
            return Score(grader="explanation", case_id=case.case_id, trial=run.trial,
                         value=0.0, detail="no output")
        prompt = _RUBRIC.format(
            reference=case.reference_root_cause,
            hypothesis=run.output.root_cause_hypothesis or "(empty)",
        )
        verdict = structured(prompt, Verdict, model=model)
        return Score(
            grader="explanation", case_id=case.case_id, trial=run.trial,
            value=round(verdict.score / 3.0, 4), detail=verdict.reason[:200],
        )

    return grade_llm


JudgeKind = Literal["heuristic", "llm"]


def get_judge(kind: JudgeKind = "heuristic", model: str | None = None):
    if kind == "heuristic":
        return grade_heuristic
    if kind == "llm":
        return _llm_judge_factory(model)
    raise ValueError(f"unknown judge {kind!r}")
