// The gate's verdict rule, ported line for line from evalgate/gate.py, for the project page.
window.G = (() => {
  const halfWidth = (iv) => Math.max(iv.high - iv.point, iv.point - iv.low);
  const valueHw = (res, m) => res.intervals[m] ? [res.intervals[m].point, halfWidth(res.intervals[m])]
    : (m in (res.scalars || {}) ? [res.scalars[m], 0] : [null, 0]);
  const f3 = (x) => x.toFixed(3);

  function evaluate(cur, base, policy) {
    const out = [];
    for (const [m, rule] of Object.entries(policy.metrics)) {
      const dir = rule.direction || "higher", minTol = rule.min_tolerance || 0;
      const [v, hNow] = valueHw(cur, m);
      if (v === null) { out.push({ m, ok: true, v: 0, base: null, tol: 0, reason: "not reported by this run" }); continue; }
      if (dir === "higher" && "floor" in rule && v < rule.floor) { out.push({ m, ok: false, v, base: null, tol: 0, kind: "floor", reason: `below hard floor ${f3(rule.floor)}` }); continue; }
      if (dir === "lower" && "ceiling" in rule && v > rule.ceiling) { out.push({ m, ok: false, v, base: null, tol: 0, kind: "ceiling", reason: `above hard ceiling ${f3(rule.ceiling)}` }); continue; }
      if (!base) { out.push({ m, ok: true, v, base: null, tol: 0, reason: "no baseline yet" }); continue; }
      const [b, hBase] = valueHw(base, m);
      if (b === null) { out.push({ m, ok: true, v, base: null, tol: 0, reason: "not in baseline" }); continue; }
      const tol = Math.max(minTol, hNow + hBase), drop = dir === "higher" ? b - v : v - b;
      if (drop > tol) out.push({ m, ok: false, v, base: b, tol, kind: "regression", reason: `regressed ${f3(drop)} against a noise band of ${f3(tol)}` });
      else out.push({ m, ok: true, v, base: b, tol, reason: drop > 0 ? "within noise" : "no regression" });
    }
    return out;
  }

  // The console summary, rebuilt from the verdicts in the same layout evalgate prints.
  function consoleText(s, verdicts) {
    const ok = verdicts.every((v) => v.ok), line = "=".repeat(72), dash = "-".repeat(72), sc = s.cur.scalars || {};
    const rows = verdicts.map((v) => `  ${v.m.padEnd(15)} ${f3(v.v).padStart(6)} ${(v.base === null ? "-" : f3(v.base)).padStart(9)} ${(v.tol ? f3(v.tol) : "-").padStart(8)}   ${(v.ok ? "ok" : "FAIL").padEnd(5)} ${v.reason}`);
    return [line, `  EVAL GATE: ${ok ? "PASSED" : "BLOCKED"}`, line,
      `  ${s.cur.adapter}  |  ${s.cur.cases} cases x ${s.cur.trials} trials  |  judge: ${s.cur.judge}`, dash,
      "  metric           value  baseline     band   verdict", ...rows, dash,
      `  judge/oracle kappa: ${f3(sc.judge_oracle_kappa || 0)}   brier: ${f3(sc.brier || 0)}   ece: ${f3(sc.ece || 0)}`, line].join("\n");
  }

  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const load = () => fetch("data.json").then((r) => r.json());
  return { evaluate, consoleText, halfWidth, esc, load, f3 };
})();
