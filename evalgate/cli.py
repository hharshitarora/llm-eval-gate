"""Command line entry point.

    python -m evalgate build                      rebuild fixture repos + dataset
    python -m evalgate run                        run the suite, print the gate
    python -m evalgate run --adapter mock:degraded    watch the gate block
    python -m evalgate baseline                   accept the current run as the baseline
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import fixtures, gate, report, runner

BASELINE = Path("baselines/baseline.json")
LATEST = Path("runs/latest.json")


def _build_adapter(spec: str):
    if spec.startswith("mock"):
        from .adapters.mock import MockAdapter

        profile = spec.split(":", 1)[1] if ":" in spec else "good"
        return MockAdapter(profile)
    if spec == "triage":
        from .adapters.triage import TriageAdapter

        return TriageAdapter()
    raise SystemExit(f"unknown adapter {spec!r} (expected mock, mock:degraded, or triage)")


def _cmd_build(args) -> int:
    cases = fixtures.build_all()
    fixtures.write_dataset(cases)
    print(f"built {len(cases)} fixture repos in {fixtures.SANDBOX}/")
    for c in cases:
        print(
            f"  {c.case_id:22} {c.difficulty:<6} culprit={c.culprit_sha[:10]} "
            f"owner={c.expected_owner:<16} decoys_after={c.decoys_after} "
            f"(same-file={c.decoys_same_file})"
        )
    print(f"\ndataset -> {fixtures.DATASET}")
    return 0


def _ensure_fixtures() -> None:
    if not fixtures.DATASET.exists():
        raise SystemExit("No dataset. Run: python -m evalgate build")
    missing = [
        c.case_id for c in fixtures.load_dataset()
        if not fixtures.repo_path(c).exists()
    ]
    if missing:
        raise SystemExit(
            f"Fixture repos missing for {', '.join(missing)}. Run: python -m evalgate build"
        )


def _cmd_run(args) -> int:
    _ensure_fixtures()
    adapter = _build_adapter(args.adapter)
    result = runner.run_suite(
        adapter, trials=args.trials, judge=args.judge, judge_model=args.judge_model
    )
    runner.save(result, LATEST)

    baseline = runner.load(BASELINE) if BASELINE.exists() else None
    verdicts = gate.evaluate(result, baseline, gate.load_policy())

    print(report.summary_console(result, verdicts))

    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(
            report.summary_markdown(result, verdicts), encoding="utf-8"
        )
        print(f"  markdown summary -> {args.markdown}")

    if not gate.passed(verdicts):
        return 1
    return 0


def _cmd_baseline(args) -> int:
    if not LATEST.exists():
        raise SystemExit("No run to promote. Run: python -m evalgate run")
    result = runner.load(LATEST)
    runner.save(result, BASELINE)
    print(f"baseline updated from {result.adapter} -> {BASELINE}")
    print("Commit it. Moving the baseline is a reviewable act, not a side effect.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="evalgate", description="CI quality gate for a non-deterministic agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="generate fixture repos and the golden dataset")

    run = sub.add_parser("run", help="run the suite and apply the gate")
    run.add_argument("--adapter", default="mock",
                     help="mock | mock:degraded | triage  (default: mock)")
    run.add_argument("--trials", type=int, default=3,
                     help="runs per case; >1 is what makes the noise band meaningful")
    run.add_argument("--judge", default="heuristic", choices=["heuristic", "llm"])
    run.add_argument("--judge-model", default=None, help="override EVALGATE_JUDGE_MODEL")
    run.add_argument("--markdown", default=None, help="also write a markdown summary here")

    sub.add_parser("baseline", help="promote the last run to the committed baseline")

    args = p.parse_args(argv)
    return {"build": _cmd_build, "run": _cmd_run, "baseline": _cmd_baseline}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
