"""The fixtures are the ground truth, so they get tested harder than anything else.

If a SHA in the committed dataset stops matching a freshly built repo, every
accuracy number in every baseline silently becomes meaningless. That failure
would be invisible without this file.
"""
from __future__ import annotations

import re
import shutil

import pytest

from evalgate import fixtures
from evalgate.fixtures import TEMPLATES


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("sandbox")
    cases = fixtures.build_all(root)
    yield root, {c.case_id: c for c in cases}
    shutil.rmtree(root, ignore_errors=True)


def test_matches_committed_dataset(built):
    """Rebuilt SHAs must equal the ones we shipped, or the dataset is a lie."""
    _, cases = built
    committed = {c.case_id: c for c in fixtures.load_dataset()}
    assert set(committed) == set(cases)
    for case_id, case in cases.items():
        assert case.culprit_sha == committed[case_id].culprit_sha, (
            f"{case_id} drifted: rebuilding produced {case.culprit_sha[:10]}, "
            f"dataset says {committed[case_id].culprit_sha[:10]}"
        )
        assert case.expected_owner == committed[case_id].expected_owner


def test_rebuild_is_byte_identical(tmp_path):
    """Two builds on the same machine, same SHAs. Catches any hidden clock or env read."""
    a = {c.case_id: c.culprit_sha for c in fixtures.build_all(tmp_path / "a")}
    b = {c.case_id: c.culprit_sha for c in fixtures.build_all(tmp_path / "b")}
    assert a == b


def test_every_template_has_exactly_one_culprit():
    for tpl in TEMPLATES:
        culprits = [c for c in tpl.commits if c.is_culprit]
        assert len(culprits) == 1, f"{tpl.name} has {len(culprits)} culprit commits"


def test_culprit_is_never_head(built):
    """The core difficulty guarantee: 'blame the newest commit' must score zero."""
    root, cases = built
    for case_id, case in cases.items():
        head = fixtures._git(root / case.template, "rev-parse", "HEAD")
        assert head != case.culprit_sha, f"{case_id}: culprit is HEAD, case is trivially gameable"
        assert case.decoys_after >= 2, f"{case_id}: only {case.decoys_after} decoys after the culprit"


def test_most_cases_defeat_blame_latest_edit(built):
    """Also defeat 'blame the newest edit to the file in the traceback'.

    Not required of every case. type_error_concat is deliberately the easy one,
    and a suite where every case is hard cannot show a difficulty gradient.
    """
    _, cases = built
    with_same_file = [c for c in cases.values() if c.decoys_same_file > 0]
    assert len(with_same_file) >= 6, "too few cases resist the newest-edit heuristic"
    without = [c for c in cases.values() if c.decoys_same_file == 0]
    assert len(without) >= 3, (
        "need several cases WITHOUT a same-file decoy as a control group, or "
        "'the agent blames the newest edit to the file' cannot be told apart "
        "from 'the agent is just wrong'"
    )


def _log_for(root, case) -> str:
    return (root / f"{case.template}.log").read_text(encoding="utf-8")


_SYMBOL = re.compile(r"^\s*(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def test_every_log_anchors_somewhere_in_the_repo(built):
    """A case with no legitimate starting point is not hard, it is unfair.

    Two kinds of anchor count, because real tracebacks provide both:

      * the package path, when the frame is in the file that changed
      * a symbol defined in the changed file, when it is not. An AttributeError
        names the code that *read* the attribute, never the module where the
        class lives, so `attribute_rename` is anchored only by the word `User`
        appearing both in the error and in `class User`.

    Requiring the path alone would have rejected a perfectly fair case.
    """
    root, cases = built
    for case_id, case in cases.items():
        log = _log_for(root, case)
        packages = {f.split("/")[0] for f in case.culprit_files}
        if any(p in log for p in packages):
            continue
        symbols = set()
        for rel in case.culprit_files:
            source = (root / case.template / rel).read_text(encoding="utf-8")
            symbols.update(_SYMBOL.findall(source))
        assert symbols & set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", log)), (
            f"{case_id}: log mentions neither {packages} nor any symbol from {case.culprit_files}"
        )


def test_some_cases_require_an_indirect_hop(built):
    """The difficulty gradient, asserted rather than assumed.

    Most logs name the culprit file outright, so the work is choosing between
    commits. `silent_wrong_total` names only the entry point and never the file
    that changed, so the agent has to follow a call into another module. A suite
    with no such case would overstate how well an agent handles real incidents;
    a suite where every case is like that could not show a gradient at all.
    """
    root, cases = built
    indirect = []
    for case_id, case in cases.items():
        log = _log_for(root, case)
        stems = [f.split("/")[-1] for f in case.culprit_files]
        if not any(s in log for s in stems):
            indirect.append(case_id)

    expected = ["attribute_rename", "import_rename", "pagination_offset", "silent_wrong_total"]
    assert sorted(indirect) == expected, (
        f"unexpected indirect cases: {indirect}"
    )
    # Four, each indirect for a different and realistic reason:
    #   silent_wrong_total, pagination_offset : no traceback at all, just a wrong
    #       number, so nothing names any file
    #   attribute_rename : an AttributeError names the code that *read* the
    #       attribute, never the module defining the class
    #   import_rename    : the log carries the dotted module "store.inventory",
    #       not the path "inventory.py"
    # A third of the suite being indirect is deliberate. Fewer and the set would
    # overstate how often a traceback hands you the answer; many more and every
    # case would be measuring the same skill.
    assert len(indirect) < len(cases) / 2


def test_difficulty_values_are_known(built):
    _, cases = built
    assert {c.difficulty for c in cases.values()} <= {"easy", "medium", "hard"}
