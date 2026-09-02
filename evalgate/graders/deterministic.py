"""Graders that need no model, no key, and no judgement.

These carry most of the weight on purpose. An LLM judge is the right tool for
"is this explanation correct", and the wrong tool for "is this the right commit",
which is a string comparison against a SHA we planted ourselves. Reaching for a
judge where an equality check will do is how eval suites end up expensive,
slow, and quietly wrong.
"""
from __future__ import annotations

from ..types import GoldenCase, RunResult, Score

_MIN_SHA_PREFIX = 7


def _norm_sha(value: str | None) -> str:
    return (value or "").strip().lower()


def grade_suspect(case: GoldenCase, run: RunResult) -> Score:
    """Did the agent name the commit that actually introduced the bug?

    Prefix matching is allowed down to 7 characters, because agents legitimately
    report short SHAs. Anything shorter is treated as no answer rather than a
    lucky match.
    """
    if not run.ok or run.output is None:
        return Score(grader="suspect_sha", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="no output")

    got = _norm_sha(run.output.suspect_commit)
    want = _norm_sha(case.culprit_sha)

    if not got:
        return Score(grader="suspect_sha", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="no suspect named")
    if len(got) < _MIN_SHA_PREFIX:
        return Score(grader="suspect_sha", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail=f"sha too short to credit: {got!r}")

    hit = want.startswith(got) or got.startswith(want)
    return Score(
        grader="suspect_sha", case_id=case.case_id, trial=run.trial,
        value=1.0 if hit else 0.0,
        detail="" if hit else f"got {got[:10]}, want {want[:10]}",
    )


def grade_owner(case: GoldenCase, run: RunResult) -> Score:
    """Did it route the incident to the person who wrote the culprit commit?

    Scored independently of suspect_sha: an agent can identify the right change
    and still misattribute it, and in an on-call context that is its own failure.
    """
    if not run.ok or run.output is None:
        return Score(grader="owner", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="no output")

    got = (run.output.recommended_owner or "").strip().lower()
    want = case.expected_owner.strip().lower()
    if not got:
        return Score(grader="owner", case_id=case.case_id, trial=run.trial,
                     value=0.0, detail="unassigned")

    # Surname match is enough; agents vary on how they render full names.
    hit = got == want or want.split()[-1] in got
    return Score(
        grader="owner", case_id=case.case_id, trial=run.trial,
        value=1.0 if hit else 0.0,
        detail="" if hit else f"got {got!r}, want {want!r}",
    )


def grade_completed(case: GoldenCase, run: RunResult) -> Score:
    """Did the run produce schema-valid output at all?

    Tracked separately so a crash rate never hides inside an accuracy average.
    """
    return Score(
        grader="completed", case_id=case.case_id, trial=run.trial,
        value=1.0 if (run.ok and run.output is not None) else 0.0,
        detail=run.error[:200],
    )


DETERMINISTIC_GRADERS = (grade_suspect, grade_owner, grade_completed)
