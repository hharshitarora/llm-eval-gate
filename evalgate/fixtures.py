"""Build fixture git repositories from bug templates.

Reproducibility is the point. Commit SHAs are ground truth, so they have to be
identical on every machine or nobody can check our answers. That means pinning
everything git would otherwise pull from the environment:

  * author/committer name, email and timestamp are fixed per commit index
  * `core.autocrlf=false` and explicit "\\n" writes, so Windows and Linux
    produce byte-identical blobs
  * global/system gitconfig is ignored, so a contributor's ~/.gitconfig cannot
    change a SHA
  * no GPG signing, fixed initial branch

`test_fixtures.py` rebuilds every repo and asserts the SHAs still match the
committed dataset, which turns fixture drift into a failing test.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .templates import ALL_TEMPLATES, Template
from .types import GoldenCase

SANDBOX = Path(".sandbox")
DATASET = Path("datasets/golden/cases.jsonl")

# Any fixed instant works; it just has to never change.
_BASE_EPOCH = 1767171600  # 2026-01-01T05:00:00Z

_GIT_CONFIG = [
    # Fixture repos are created by this process, so trusting them is correct.
    # Command scope is protected config, which is the only place git honours this
    # once GIT_CONFIG_GLOBAL is nulled out.
    "-c", "safe.directory=*",
    "-c", "core.autocrlf=false",
    "-c", "core.fileMode=false",
    "-c", "commit.gpgsign=false",
    "-c", "gc.auto=0",
    "-c", "init.defaultBranch=main",
]

# Ignore whatever the contributor has configured globally.
_CLEAN_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}


def _git(repo: Path, *args: str, env_extra: dict[str, str] | None = None) -> str:
    env = {**os.environ, **_CLEAN_ENV, **(env_extra or {})}
    proc = subprocess.run(
        ["git", *_GIT_CONFIG, "-C", str(repo), *args],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" plus explicit \n keeps blobs identical across platforms.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content.replace("\r\n", "\n"))


def _force_rmtree(path: Path) -> None:
    """Delete a git repo on Windows too.

    Git writes objects read-only and Windows refuses to unlink a read-only file.
    `ignore_errors=True` would swallow that and leave a half-deleted repo behind,
    which then gets rebuilt on top of itself. So clear the flag, retry, and let a
    genuine failure raise instead of hiding.
    """
    if not path.exists():
        return

    def _retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)


def build_template(tpl: Template, root: Path = SANDBOX) -> GoldenCase:
    """Materialise one template into a git repo and return its golden case."""
    repo = root / tpl.name
    _force_rmtree(repo)
    repo.mkdir(parents=True)

    _git(repo, "init", "-q")

    culprit_sha = ""
    culprit_files: list[str] = []
    culprit_owner = ""
    culprit_index = -1

    for i, commit in enumerate(tpl.commits):
        for rel, content in commit.files.items():
            _write(repo, rel, content)
        _git(repo, "add", "-A")

        stamp = f"{_BASE_EPOCH + i * 86400} +0000"
        _git(
            repo, "commit", "-q", "--no-gpg-sign", "-m", commit.message,
            env_extra={
                "GIT_AUTHOR_NAME": commit.author,
                "GIT_AUTHOR_EMAIL": commit.email,
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": commit.author,
                "GIT_COMMITTER_EMAIL": commit.email,
                "GIT_COMMITTER_DATE": stamp,
            },
        )

        if commit.is_culprit:
            culprit_sha = _git(repo, "rev-parse", "HEAD")
            culprit_files = sorted(commit.files)
            culprit_owner = commit.author
            culprit_index = i

    if not culprit_sha:
        raise ValueError(f"template {tpl.name} has no culprit commit")

    after = tpl.commits[culprit_index + 1:]
    same_file = sum(1 for c in after if set(c.files) & set(culprit_files))

    log_path = root / f"{tpl.name}.log"
    with open(log_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(tpl.error_log.replace("\r\n", "\n"))

    return GoldenCase(
        case_id=tpl.name,
        template=tpl.name,
        difficulty=tpl.difficulty,
        culprit_sha=culprit_sha,
        culprit_files=culprit_files,
        expected_owner=culprit_owner,
        decoys_after=len(after),
        decoys_same_file=same_file,
        expected_error_type=tpl.expected_error_type,
        reference_root_cause=tpl.reference_root_cause,
    )


def build_all(root: Path = SANDBOX) -> list[GoldenCase]:
    root.mkdir(parents=True, exist_ok=True)
    return [build_template(t, root) for t in ALL_TEMPLATES]


def write_dataset(cases: list[GoldenCase], path: Path = DATASET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for case in cases:
            fh.write(case.model_dump_json() + "\n")


def load_dataset(path: Path = DATASET) -> list[GoldenCase]:
    with open(path, encoding="utf-8") as fh:
        return [GoldenCase(**json.loads(line)) for line in fh if line.strip()]


def repo_path(case: GoldenCase, root: Path = SANDBOX) -> Path:
    return root / case.template


def log_path(case: GoldenCase, root: Path = SANDBOX) -> Path:
    return root / f"{case.template}.log"


if __name__ == "__main__":  # pragma: no cover
    built = build_all()
    write_dataset(built)
    print(f"built {len(built)} fixture repos in {SANDBOX}/")
    for c in built:
        print(
            f"  {c.case_id:22} {c.difficulty:6} culprit={c.culprit_sha[:10]} "
            f"decoys_after={c.decoys_after} same_file={c.decoys_same_file}"
        )
