"""A deterministic stand-in for the real agent.

This exists for two reasons, and both matter more than they sound.

1. **CI has no API key.** Without a hermetic adapter the eval workflow would be
   permanently yellow, and a gate nobody can run is not a gate.
2. **You need a regression to prove a regression detector works.** The `degraded`
   profile is a synthetic quality drop: it gets fewer answers right *and* stays
   just as confident when it is wrong. Running the gate against it makes the
   whole pipeline fail on purpose, on demand, in about four seconds.

Determinism comes from hashlib, not `hash()`, because CPython salts `hash()`
per process and the numbers would move between runs.
"""
from __future__ import annotations

import hashlib
import random

from ..types import AgentOutput, GoldenCase, RunResult

# P(correct suspect commit) by difficulty, per profile.
_ACCURACY = {
    "good": {"easy": 0.97, "medium": 0.88, "hard": 0.55},
    # Clearly below the suspect_sha floor on any mix of difficulties, so the
    # regression is caught by accuracy as well as by calibration.
    "degraded": {"easy": 0.70, "medium": 0.45, "hard": 0.20},
}

# How stated confidence relates to being right.
#
# The good profile is calibrated *by construction*. For a case it gets right
# with probability p, it says p + (1-p)k when right and p - pk when wrong, whose
# mean is exactly p for any spread k. So confidence still discriminates (higher
# when it is right) while the average confidence in a bin matches the accuracy
# in that bin, which is what calibration means.
#
# Getting this wrong is not academic: the first version used flat confidences
# regardless of difficulty, and once the suite grew to include two hard cases
# the reference "good" agent tripped the ECE ceiling. A healthy fixture must be
# healthy on every axis the gate measures, or it fails the gate for reasons that
# say nothing about the gate.
_CONFIDENCE_SPREAD = 0.5

# The degraded profile stays confident while being wrong, on purpose. That is
# the failure a pure accuracy check misses.
_DEGRADED_CONFIDENCE = {"right": 0.88, "wrong": 0.83}

_COST_PER_CASE = {"good": 0.0112, "degraded": 0.0094}
_LATENCY_S = {"good": 11.4, "degraded": 9.8}

_WRONG_SHA = "0" * 40


def _seed(*parts: object) -> random.Random:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(raw).digest()[:8], "big"))


class MockAdapter:
    """Simulates an agent at a chosen quality level."""

    def __init__(self, profile: str = "good") -> None:
        if profile not in _ACCURACY:
            raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(_ACCURACY)}")
        self.profile = profile
        self.name = f"mock:{profile}"

    def run(self, case: GoldenCase, trial: int) -> RunResult:
        rng = _seed(self.name, case.case_id, trial)

        p_correct = _ACCURACY[self.profile][case.difficulty]
        correct = rng.random() < p_correct

        if self.profile == "good":
            k = _CONFIDENCE_SPREAD
            mean_conf = p_correct + (1 - p_correct) * k if correct else p_correct - p_correct * k
        else:
            mean_conf = _DEGRADED_CONFIDENCE["right" if correct else "wrong"]
        confidence = min(0.99, max(0.01, rng.gauss(mean_conf, 0.04)))

        if correct:
            sha = case.culprit_sha
            hypothesis = case.reference_root_cause
        else:
            sha = _WRONG_SHA
            hypothesis = (
                f"A recent change to {case.culprit_files[0] if case.culprit_files else 'the module'} "
                "appears related, though the specific commit is unclear."
            )

        return RunResult(
            case_id=case.case_id,
            trial=trial,
            ok=True,
            output=AgentOutput(
                summary=f"{case.expected_error_type} observed in {case.case_id}.",
                root_cause_hypothesis=hypothesis,
                confidence=round(confidence, 4),
                suspect_commit=sha,
                severity="high",
                recommended_owner=case.expected_owner if correct else None,
                next_steps=["Revert the suspect commit", "Add a regression test"],
            ),
            latency_s=round(rng.gauss(_LATENCY_S[self.profile], 1.8), 3),
            cost_usd=round(rng.gauss(_COST_PER_CASE[self.profile], 0.0012), 6),
        )
