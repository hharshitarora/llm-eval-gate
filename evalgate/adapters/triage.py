"""Adapter for hharshitarora/incident-triage-agent.

It shells out to the agent's own CLI and parses `--json`. No imports, no
monkeypatching, no shared virtualenv. The harness only knows how to start a
process and read a JSON object off stdout, which is why pointing it at a
different agent is a fifty-line file rather than a refactor.

One deliberate gap: `cost_usd` is left at 0. Measuring spend would mean reaching
inside the system under test to instrument its LLM client, and the whole design
depends on not doing that. Cost is graded only for adapters that report it
themselves; the cost grader skips cleanly when nothing does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..fixtures import log_path, repo_path
from ..types import AgentOutput, GoldenCase, RunResult

_DEFAULT_SUT = Path("../incident-triage-agent")


def _resolve_python(sut: Path) -> str:
    """Prefer the system-under-test's own venv, so we grade its real deps."""
    explicit = os.environ.get("TRIAGE_PYTHON")
    if explicit:
        return explicit
    for candidate in (sut / ".venv/Scripts/python.exe", sut / ".venv/bin/python"):
        if candidate.exists():
            return str(candidate.resolve())
    return sys.executable


class TriageAdapter:
    name = "triage"

    def __init__(self, sut_path: str | None = None, timeout_s: int = 180) -> None:
        self.sut = Path(sut_path or os.environ.get("TRIAGE_REPO_PATH") or _DEFAULT_SUT).resolve()
        if not (self.sut / "triage").is_dir():
            raise FileNotFoundError(
                f"No triage package at {self.sut}. Clone incident-triage-agent next to this "
                "repo, or set TRIAGE_REPO_PATH."
            )
        self.python = _resolve_python(self.sut)
        self.timeout_s = timeout_s

    def run(self, case: GoldenCase, trial: int) -> RunResult:
        cmd = [
            self.python, "-m", "triage",
            "--repo", str(repo_path(case).resolve()),
            "--log", str(log_path(case).resolve()),
            "--json",
        ]
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=self.sut, capture_output=True, text=True,
                timeout=self.timeout_s, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                case_id=case.case_id, trial=trial, ok=False,
                error=f"timed out after {self.timeout_s}s",
                latency_s=round(time.perf_counter() - started, 3),
            )
        elapsed = round(time.perf_counter() - started, 3)

        if proc.returncode != 0:
            return RunResult(
                case_id=case.case_id, trial=trial, ok=False,
                error=f"exit {proc.returncode}: {proc.stderr.strip()[-400:]}",
                latency_s=elapsed,
            )

        try:
            payload = json.loads(_last_json_object(proc.stdout))
            output = AgentOutput(**payload)
        except Exception as exc:  # noqa: BLE001 - any parse failure is a graded failure
            return RunResult(
                case_id=case.case_id, trial=trial, ok=False,
                error=f"unparseable output: {exc}",
                latency_s=elapsed,
            )

        return RunResult(
            case_id=case.case_id, trial=trial, ok=True,
            output=output, latency_s=elapsed, cost_usd=0.0,
        )


def _last_json_object(text: str) -> str:
    """Pull the trailing JSON object out of stdout, ignoring any log chatter."""
    depth = 0
    end = -1
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == "}":
            if depth == 0:
                end = i
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0 and end != -1:
                return text[i:end + 1]
    raise ValueError("no JSON object found in stdout")
