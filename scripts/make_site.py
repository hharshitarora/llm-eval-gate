"""Builds site/data.json for the project page from files in this repo.

Nothing on the page is typed in by hand. It reads gate.json, the golden set,
the November baseline, the September baseline from git history, one recorded
answer from the triage agent (docs/example-answer.json), and a fresh run of the
deliberately degraded mock, which is seeded and needs no key.

    python scripts/make_site.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evalgate import fixtures, runner  # noqa: E402
from evalgate.adapters.mock import MockAdapter  # noqa: E402

SITE = ROOT / "site"
EXAMPLE = "attribute_rename"
SEPTEMBER = "ed019a3~1"  # the last commit before November was promoted to the baseline


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


def main() -> None:
    cases = fixtures.build_all()
    case = next(c for c in cases if c.case_id == EXAMPLE)
    repo = fixtures.repo_path(case)
    commits = []
    for row in git(repo, "log", "--reverse", "--format=%H\x1f%an\x1f%ad\x1f%s", "--date=short").splitlines():
        sha, author, date, subject = row.split("\x1f")
        commits.append({"sha": sha, "author": author, "date": date, "subject": subject,
                        "files": git(repo, "show", "--name-only", "--format=", sha).split()})

    degraded = runner.run_suite(MockAdapter("degraded"), trials=5).to_dict()
    data = {
        "policy": json.loads((ROOT / "gate.json").read_text(encoding="utf-8")),
        "sept": json.loads(git(ROOT, "show", f"{SEPTEMBER}:baselines/triage.json")),
        "nov": json.loads((ROOT / "baselines" / "triage.json").read_text(encoding="utf-8")),
        "mock_base": json.loads((ROOT / "baselines" / "mock-good.json").read_text(encoding="utf-8")),
        "mock_degraded": {**degraded, "adapter": "mock:degraded"},
        "cases": [{k: v for k, v in c.model_dump().items() if k != "expected_owner"} for c in cases],
        "example": {
            **case.model_dump(),
            "commits": commits,
            "log": fixtures.log_path(case).read_text(encoding="utf-8").strip(),
            "answer": json.loads((ROOT / "docs" / "example-answer.json").read_text(encoding="utf-8"))["output"],
        },
    }
    data["example"]["owner"] = data["example"].pop("expected_owner")
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {SITE / 'data.json'}")


if __name__ == "__main__":
    main()
