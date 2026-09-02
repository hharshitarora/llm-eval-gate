"""Human-readable output.

The audience is someone looking at a red check on their pull request who wants
to know, in about five seconds, whether to trust it. So every failing line says
what moved, by how much, and how much movement was considered normal. A gate
that just says FAILED gets disabled within a month.
"""
from __future__ import annotations

from .gate import Verdict
from .runner import SuiteResult

_TICK = "PASS"
_CROSS = "FAIL"


def summary_markdown(result: SuiteResult, verdicts: list[Verdict]) -> str:
    ok = all(v.ok for v in verdicts)
    lines = [
        f"## Eval gate: {'PASSED' if ok else 'BLOCKED'}",
        "",
        f"`{result.adapter}` · {result.cases} cases × {result.trials} trials · "
        f"judge `{result.judge}`",
        "",
        "| Metric | Value | Baseline | Noise band | Verdict |",
        "|---|---|---|---|---|",
    ]
    for v in verdicts:
        base = f"{v.baseline:.3f}" if v.baseline is not None else "-"
        band = f"±{v.tolerance:.3f}" if v.tolerance else "-"
        mark = _TICK if v.ok else f"**{_CROSS}**"
        reason = f" · {v.reason}" if v.reason else ""
        lines.append(f"| `{v.metric}` | {v.current:.3f} | {base} | {band} | {mark}{reason} |")

    lines += [
        "",
        f"Judge/oracle agreement (Cohen's κ): **{result.scalars.get('judge_oracle_kappa', 0):.3f}** · "
        f"latency p50 {result.scalars.get('latency_p50_s', 0):.1f}s / "
        f"p95 {result.scalars.get('latency_p95_s', 0):.1f}s · "
        f"cost ${result.scalars.get('cost_total_usd', 0):.4f}",
        "",
        "<details><summary>Per-case breakdown</summary>",
        "",
        "| Case | Difficulty | Suspect | Explanation | Owner |",
        "|---|---|---|---|---|",
    ]
    for case_id, row in result.per_case.items():
        lines.append(
            f"| `{case_id}` | {row.get('difficulty', '?')} | {row.get('suspect_sha', 0):.2f} | "
            f"{row.get('explanation', 0):.2f} | {row.get('owner', 0):.2f} |"
        )
    lines += ["", "</details>"]

    if result.failures:
        lines += ["", "**Run failures**", "```"] + result.failures + ["```"]

    return "\n".join(lines)


def summary_console(result: SuiteResult, verdicts: list[Verdict]) -> str:
    ok = all(v.ok for v in verdicts)
    width = 72
    out = [
        "=" * width,
        f"  EVAL GATE: {'PASSED' if ok else 'BLOCKED'}",
        "=" * width,
        f"  {result.adapter}  |  {result.cases} cases x {result.trials} trials  |  "
        f"judge: {result.judge}",
        "-" * width,
        f"  {'metric':<14}{'value':>8}{'baseline':>10}{'band':>9}   verdict",
    ]
    for v in verdicts:
        base = f"{v.baseline:.3f}" if v.baseline is not None else "     -"
        band = f"{v.tolerance:.3f}" if v.tolerance else "    -"
        mark = "ok  " if v.ok else "FAIL"
        out.append(
            f"  {v.metric:<14}{v.current:>8.3f}{base:>10}{band:>9}   {mark}  {v.reason}"
        )
    out += [
        "-" * width,
        f"  judge/oracle kappa: {result.scalars.get('judge_oracle_kappa', 0):.3f}   "
        f"brier: {result.scalars.get('brier', 0):.3f}   "
        f"ece: {result.scalars.get('ece', 0):.3f}",
        f"  latency p50/p95: {result.scalars.get('latency_p50_s', 0):.1f}s / "
        f"{result.scalars.get('latency_p95_s', 0):.1f}s   "
        f"cost: ${result.scalars.get('cost_total_usd', 0):.4f}",
        "=" * width,
    ]
    if result.failures:
        out.append("  run failures:")
        out += [f"    ! {f}" for f in result.failures]
        out.append("=" * width)
    return "\n".join(out)
