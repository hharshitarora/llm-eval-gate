# Design decisions

Trade-offs made while building this, including the ones that cost something.

## A separate repo, not a folder inside the agent

An eval suite that lives inside the thing it grades tends to drift toward
testing the implementation rather than the behaviour, because it can reach in.
Keeping it outside forced the process boundary, and the process boundary is what
makes the harness reusable. The cost is a second repo to keep in sync, paid for
by `TRIAGE_REPO_PATH` and one adapter file.

## Process isolation over imports

The obvious implementation is `from triage.graph import build_graph` and call it
in the same interpreter. That is faster and would let me measure token spend
directly.

It also means the harness shares a dependency tree with the system under test,
so a langchain upgrade in one breaks the other, and grading a Node or Go agent
later means rewriting the runner rather than adding an adapter. The harness
starts a process and reads JSON off stdout instead.

**What that costs:** `cost_usd` is 0 for the real agent, because measuring spend
would mean instrumenting its LLM client. The cost grader skips cleanly rather
than reporting a fabricated number. Correct trade, but it is a real gap and the
README says so.

## The mock adapter is not a testing shortcut

It looks like a stub. It is doing two jobs neither of which a stub does.

CI has no API key, and cannot have one for pull requests from forks. Without a
hermetic adapter the eval workflow is permanently yellow, nobody can run the
gate on a fork, and a gate nobody can run is not a gate.

Second, a regression detector that has never detected a regression is an
assertion, not a feature. `mock:degraded` is a synthetic quality drop: fewer
right answers *and* unchanged confidence when wrong. CI runs it every build and
fails if the gate lets it through. The gate is itself under test.

## Clustered bootstrap, not the naive one

I wrote the naive version first: bootstrap over all 30 observations. It reported
a half-width of about 0.13 on accuracy.

That is too tight, and the reason is that five trials of `zero_division` are
five looks at the same question. They are correlated, so treating them as 30
independent draws overstates how much information the suite carries and makes
the gate fire on noise.

Resampling whole cases instead widens the band to about 0.27. That is worse
looking and more honest. It also changes what the gate can claim: with six cases
the relative check only catches large regressions, and the absolute floors do
most of the real work. The README states that rather than implying the gate is
sharper than it is.

## Judged against the objective signal, not hand labels

The textbook way to validate an LLM judge is to hand-label a sample and measure
agreement. I did not do that, because labels I write about outputs I generated
would be a number that looks like validation without being it.

Instead the judge is scored against the one signal that is objectively true:
whether the agent named the planted commit. Kappa rather than raw agreement,
because raw agreement flatters a constant rater on a skewed set.

**Limitation:** the two are not measuring identical things. An agent can name the
right commit and explain it badly, so perfect kappa is not the target and a
moderate score is expected. It is a real check on judge quality, not a proof of
judge correctness. Human spot labels would be a genuine improvement and the
score is printed every run so the gap stays visible.

## Absolute bounds *and* relative regression

Either alone has a hole. Relative-only never blocks an agent that was bad from
the first commit, since it becomes its own baseline. Absolute-only cannot catch
a slide from 0.92 to 0.71 if the floor is 0.55.

Both are wired, and they fail for different reasons in the output so it is
obvious which one fired.

## `completed` is graded separately from accuracy

Tempting to fold crashes into accuracy: a run that produced nothing got the
answer wrong, so score it 0. That hides a crash rate inside an average, and an
agent that crashes 30% of the time and is perfect otherwise is a different
problem from one that runs every time and is 70% accurate. Its floor is 1.0. A
crash is never within noise.

## Fixture SHAs are committed and CI-verified

The dataset could have been generated fresh on each run, which would never
drift. But then nobody can inspect ground truth without executing the generator,
and a reviewer cannot tell whether the answer key changed under them.

Committing `cases.jsonl` and having CI fail on any diff makes ground truth a
reviewable artifact. Changing it becomes a visible act in a pull request, which
is the correct weight for changing an answer key.

## Deliberately not built

- **A web dashboard.** The output goes where the decision is made: the terminal
  and the pull request comment.
- **More metrics.** Every metric in `gate.json` can block a merge. Ones that
  cannot are noise, and noise trains people to ignore the gate.
- **Retry-until-pass.** Deliberately absent. It is the single fastest way to
  turn a quality gate back into a decoration.
- **A larger golden set.** Six cases is honestly too few, and the README says
  so. Adding cases is appending a template, but padding the set before the
  mechanics were right would have been the wrong order.
