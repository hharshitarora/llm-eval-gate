"""The boundary between the harness and whatever it is grading.

An adapter turns a GoldenCase into a RunResult. That is the entire contract.
The harness never imports the system under test, so swapping in a different
agent means writing one small adapter, not touching a grader.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..types import GoldenCase, RunResult


@runtime_checkable
class Adapter(Protocol):
    name: str

    def run(self, case: GoldenCase, trial: int) -> RunResult:
        """Execute the system under test once against one case."""
        ...
