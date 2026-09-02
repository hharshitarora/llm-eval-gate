# llm-eval-gate

[![eval-gate](https://github.com/hharshitarora/llm-eval-gate/actions/workflows/eval.yml/badge.svg)](https://github.com/hharshitarora/llm-eval-gate/actions/workflows/eval.yml)

> A CI quality gate for an agent whose output changes between identical runs.

Blocking a merge on a unit test is easy: the test passes or it does not. Blocking
a merge on "the agent got worse" is not, because the agent's score moves on its
own. Score 0.83 today, 0.78 tomorrow, same code. Fail the build on that and
everyone learns to hit rerun until it goes green, and the gate is now a
decoration that costs money.

This is a working answer to that problem, pointed at
[incident-triage-agent](https://github.com/hharshitarora/incident-triage-agent):
an agent that reads a crash log, walks git history, and names the commit that
caused the incident.

## What it looks like when it fires

```
========================================================================
  EVAL GATE: BLOCKED
========================================================================
  mock:degraded  |  6 cases x 5 trials  |  judge: heuristic
------------------------------------------------------------------------
  metric           value  baseline     band   verdict
  completed        1.000     1.000        -   ok    no regression
  suspect_sha      0.533         -        -   FAIL  below hard floor 0.550
  explanation      0.829     0.940    0.184   ok    within noise
  owner            0.533     0.900    0.267   FAIL  regressed 0.367 against a noise band of 0.267
  brier            0.327         -        -   FAIL  above hard ceiling 0.250
  ece              0.327         -        -   FAIL  above hard ceiling 0.200
------------------------------------------------------------------------
  judge/oracle kappa: 0.225   brier: 0.327   ece: 0.327
  latency p50/p95: 9.5s / 11.7s   cost: $0.2857
========================================================================
```

Exit code 1, merge blocked, and every failing line says what moved, by how much,
and how much movement was considered normal.

> These numbers come from the built-in `mock:degraded` profile, a synthetic
> agent used to prove the gate bites. They are not measurements of the real
> triage agent. Grading that needs an API key: see [Grading a real
> agent](#grading-a-real-agent).

## The four things that make it more than a for-loop

### 1. Ground truth is a fact, not a judgement

The golden set is not scraped or hand-labelled. A generator plants a known bug
in a synthetic repo, so the correct answer is a SHA of a commit we wrote
ourselves. Checking accuracy is then a string comparison, not a model call.

The fixtures are byte reproducible. Author, email and commit timestamp are
pinned per commit, global gitconfig is ignored, and line endings are forced, so
every machine produces the same SHAs:

```
config_keyerror        easy   culprit=f1f6483e59 owner=Dana Lee        decoys_after=3 (same-file=1)
split_indexerror       medium culprit=ae5b84ea25 owner=Tom Vance       decoys_after=3 (same-file=1)
none_attributeerror    medium culprit=363c5aaa9e owner=Sofia Klein     decoys_after=2 (same-file=1)
zero_division          medium culprit=e99dd2e745 owner=Elena Duarte    decoys_after=3 (same-file=1)
type_error_concat      easy   culprit=f095179388 owner=Nils Berger     decoys_after=2 (same-file=0)
silent_wrong_total     hard   culprit=dcb3be7233 owner=Grace Oyelaran  decoys_after=3 (same-file=1)
```

CI rebuilds them and fails if a single SHA drifts, because the moment ground
truth moves, every accuracy number ever recorded becomes meaningless.

**The decoy columns are the difficulty knob.** Every case lands commits *after*
the culprit, so "blame the newest commit" scores zero. Most also land a later
commit touching the culprit's own file, so "blame the newest edit to the file in
the traceback" scores zero too. Passing requires reading the diffs.

`silent_wrong_total` is the hard one: no traceback at all, just a failing
assertion and a rounding change two calls away from the reported entry point.

### 2. Deterministic graders first, judge only where it is unavoidable

| Grader | How | Why not an LLM |
|---|---|---|
| `suspect_sha` | exact match against the planted commit | it is a SHA comparison |
| `owner` | culprit commit's author, surname match | it is in the commit metadata |
| `completed` | schema-valid output produced | it is a parse, tracked separately so crashes never hide inside an accuracy average |
| `explanation` | rubric judge, 0 to 3 | genuinely needs reading for meaning |

Reaching for a judge where an equality check would do is how eval suites end up
slow, expensive, and quietly wrong.

### 3. Calibration, because a confidence number should mean something

The agent emits `confidence: 0.0 to 1.0`. Almost nobody checks whether a stated
90% is right 90% of the time, so the field becomes decoration.

Two metrics fix that. **Brier score** is the mean squared error between stated
confidence and what happened (always guessing 50% scores 0.25, so anything worse
is actively misleading). **ECE** isolates the calibration question from raw
accuracy.

This is not academic. In the run above, the degraded agent got *less* accurate
while staying just as confident. An accuracy-only gate with a generous threshold
could have let that through. Brier and ECE both slammed it.

### 4. The judge gets judged

"How do you know your judge is right?" is the question a good reviewer asks, and
usually there is no answer.

Here the judge is scored against the objective signal using Cohen's kappa, and
the number prints on every run. Kappa rather than raw agreement on purpose: when
85% of runs are correct, a judge that says "correct" every time scores 85% raw
agreement while being worthless. Kappa scores it 0.

The heuristic judge in the run above scores κ ≈ 0.47. That is moderate, not
good, and it is reported rather than buried, because a judge you cannot trust is
a metric you cannot gate on.

## The noise band

The core mechanic. A drop only blocks a merge if it exceeds the run to run noise
of the metric itself.

Noise is measured with a **clustered bootstrap** that resamples *cases*, not
individual runs. Five trials of the same case are five looks at one question and
move together. Treating them as independent observations reports a tighter
interval than the data supports and makes the gate trigger happy. Resampling
whole cases keeps that structure and gives an honestly wider band.

Tolerance for each metric is:

```
max(policy_min_tolerance, baseline_half_width + current_half_width)
```

Two independent ways to block, in [`gate.json`](./gate.json), reviewed like code:

- **absolute bounds** (`floor` / `ceiling`) catch an agent that was always bad,
  including on its first ever run
- **relative regression** catches an agent that was fine yesterday

## Quickstart

No API key. No network. Under five seconds.

```bash
git clone https://github.com/hharshitarora/llm-eval-gate
cd llm-eval-gate
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m evalgate build                      # generate fixture repos + dataset
python -m evalgate run                        # run the suite, apply the gate
python -m evalgate run --adapter mock:degraded   # watch it block, exit 1
```

Core dependencies are `pydantic` and `python-dotenv`. The LLM stack is a
separate `requirements-llm.txt` install, so the hermetic path cannot silently
start depending on it.

## Grading a real agent

```bash
pip install -r requirements-llm.txt
cp .env.example .env          # add OPENAI_API_KEY, set TRIAGE_REPO_PATH
python -m evalgate run --adapter triage --judge llm --trials 3
```

The harness never imports the system under test. It starts a process, reads a
JSON object off stdout, and validates it. Pointing this at a different agent is
[one ~50 line adapter](./evalgate/adapters/triage.py), not a refactor.

## Limitations

Stated plainly, because a gate you have wrong confidence in is worse than none.

- **Six cases is a small set.** The clustered bootstrap correctly reports a wide
  band (≈0.27 on accuracy), which means the *relative* check only catches large
  regressions today and the absolute floors are doing most of the work. That is
  the honest reading of six cases. More cases narrow the band, and adding one is
  appending a template.
- **Synthetic bugs are not production bugs.** They are clean, single commit, and
  Python. Real incidents are messier.
- **The heuristic judge is a proxy.** It measures salient-term recall and cannot
  recognise a correct explanation phrased differently. That is why its kappa is
  printed, and why `--judge llm` exists.
- **Cost is only graded for adapters that report it.** Measuring spend would mean
  instrumenting the system under test, and the whole design depends on not
  reaching inside it.

## Design notes

[`DECISIONS.md`](./DECISIONS.md) covers the trade-offs: why a separate repo, why
process isolation, why the mock adapter exists, and what was deliberately left
out.

## Related

- [incident-triage-agent](https://github.com/hharshitarora/incident-triage-agent)
  is the system under test: a LangGraph agent that traces a production crash to
  the commit that caused it.
