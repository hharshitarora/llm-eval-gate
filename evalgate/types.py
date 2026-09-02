"""Value types shared across the harness.

Deliberately self-contained: the harness never imports the system under test.
It talks to it across a process boundary and validates whatever comes back,
so the same graders work against any agent that can emit this shape.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GoldenCase(BaseModel):
    """One evaluation case whose correct answer is known by construction.

    Ground truth here is not a judgement call. The fixture generator plants the
    bug, so `culprit_sha` is a fact about a repo we built, not an opinion.
    """

    case_id: str
    template: str
    difficulty: str = Field(description="easy | medium | hard")

    culprit_sha: str = Field(description="full SHA of the commit that introduced the bug")
    culprit_files: list[str] = Field(description="files the culprit commit touched")
    expected_owner: str = Field(description="author of the culprit commit")
    decoys_after: int = Field(description="commits landed after the culprit")
    decoys_same_file: int = Field(
        description="of those, how many touch a culprit file (defeats 'blame the newest edit')"
    )

    expected_error_type: str = Field(description="e.g. KeyError; 'none' for a non-crash case")
    reference_root_cause: str = Field(description="human-written correct explanation")


class AgentOutput(BaseModel):
    """The agent's answer, normalised. Mirrors the triage report contract."""

    summary: str = ""
    root_cause_hypothesis: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    suspect_commit: Optional[str] = None
    severity: str = ""
    recommended_owner: Optional[str] = None
    next_steps: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """One execution of the agent against one case. n of these per case."""

    case_id: str
    trial: int
    ok: bool
    output: Optional[AgentOutput] = None
    error: str = ""
    latency_s: float = 0.0
    cost_usd: float = 0.0


class Score(BaseModel):
    """One grader's verdict on one run. Always 0..1 so metrics compose."""

    grader: str
    case_id: str
    trial: int
    value: float
    detail: str = ""
