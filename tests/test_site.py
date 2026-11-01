"""The project page reads site/data.json. If it drifts from the golden set or the gate's own verdicts, fail here."""
import json
from pathlib import Path

import pytest

from evalgate.gate import evaluate, load_policy, passed
from evalgate.runner import SuiteResult

DATA = Path(__file__).resolve().parent.parent / "site" / "data.json"


@pytest.mark.skipif(not DATA.exists(), reason="site/data.json not built; run scripts/make_site.py")
def test_site_data_matches_the_golden_set_and_the_gate():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    ex = d["example"]
    culprit = next(c for c in ex["commits"] if c["sha"] == ex["culprit_sha"])
    assert culprit["author"] == ex["owner"]
    assert ex["answer"]["suspect_commit"] and ex["culprit_sha"].startswith(ex["answer"]["suspect_commit"])
    assert all("expected_owner" not in c for c in d["cases"])

    policy = load_policy()
    run = lambda k: SuiteResult.from_dict(d[k])
    # the verdicts the page computes in JS must be the ones the gate gives
    assert passed(evaluate(run("nov"), run("sept"), policy))
    assert not passed(evaluate(run("mock_degraded"), run("mock_base"), policy))
