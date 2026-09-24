"""The verdict is an instrument and every row must name the version of it that scored the row.

WHY THIS FILE EXISTS. `docx-brand-arial-black` published a 0/6 unaided baseline built from two
batches 36 minutes apart, with a rewrite of the verdict's structure guard in between -- the guard
had been keying on style names, and unaided runs write every paragraph as `Normal`. Under one
consistent verdict that baseline is 1/6, which is a marginal cell rather than a zero one, and the
whole ON-arm comparison reads differently.

Nothing in the rows could have shown that. `apparatus()` pinned the venv that RUNS the verdict and
`skill_apparatus()` pinned the treatment, but the assertions themselves were unrecorded, so an
edited rule and a changed model looked identical. Recovering it needed git-log archaeology against
run timestamps.

The digest covers the test files present at verdict time, which is the instrument in both shapes a
task takes: a hidden verdict copied in after the agent exits, and a task whose visible tests ARE
the spec.
"""
import hashlib
import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent


def hashes(*pairs):
    return {name: hashlib.sha256(body.encode()).hexdigest() for name, body in pairs}


def test_a_changed_assertion_changes_the_digest():
    """The whole point: the same file name with a different rule is a different instrument."""
    strict = harness.verdict_apparatus(hashes(("test_compliance.py", "assert size == 24")))
    relaxed = harness.verdict_apparatus(hashes(("test_compliance.py", "assert size >= 20")))
    assert strict["verdict_sha"] != relaxed["verdict_sha"]
    assert strict["verdict_files"] == relaxed["verdict_files"] == 1


def test_identical_verdicts_digest_identically():
    """Two batches of the same cell must be joinable on this field, or it buys nothing."""
    a = harness.verdict_apparatus(hashes(("test_compliance.py", "x"), ("test_extra.py", "y")))
    b = harness.verdict_apparatus(hashes(("test_extra.py", "y"), ("test_compliance.py", "x")))
    assert a == b, "digest depends on dict order, so it cannot identify a verdict"


def test_an_added_test_file_changes_the_digest():
    one = harness.verdict_apparatus(hashes(("test_compliance.py", "x")))
    two = harness.verdict_apparatus(hashes(("test_compliance.py", "x"), ("test_more.py", "x")))
    assert one["verdict_sha"] != two["verdict_sha"]
    # Same bytes under a different NAME must also differ: pytest collects by filename, so a
    # renamed file is a different set of tests even when nothing inside it moved.
    renamed = harness.verdict_apparatus(hashes(("test_renamed.py", "x")))
    assert renamed["verdict_sha"] != one["verdict_sha"]


def test_no_verdict_is_none_not_a_digest_of_nothing():
    """A sha256 of the empty set is a real hexdigest and would read, in the rows, as "some
    verdict scored this". Same reasoning as `skill_sha` on the OFF arm."""
    assert harness.verdict_apparatus({}) == {"verdict_sha": None, "verdict_files": 0}


def test_run_rep_digests_the_verdict_that_ran_not_the_workspace_the_agent_saw():
    """The call site and its ORDER. Taken beside `after_tests` -- before the hidden verdict is
    copied in -- this field would be empty for exactly the tasks whose verdict is the whole
    instrument, while every test above still passed."""
    src = inspect.getsource(harness.run_rep)
    assert "**verdict_apparatus(scoring_tests)" in src
    copy_at = src.index('shutil.copytree(task["verdict"]')
    digest_at = src.index("scoring_tests = test_hashes(ws)")
    assert copy_at < digest_at, (
        "the verdict digest is taken BEFORE the hidden verdict is installed, so it records the "
        "workspace the agent saw instead of the tests that scored it")
    assert digest_at < src.index("rc1, tail1, out1 = pytest_run(ws)")


def test_every_compliance_task_yields_a_digest():
    """A field that is None on real tasks is a field nobody filters on.

    Resolved through `load_task`, so this sees a task the way the harness does: `meta.json` is
    optional and a hidden `verdict/` is an optional directory. Compliance tasks carry one;
    `cortex-pyfix-001` carries visible tests in `workspace/` instead, and both must digest.

    Selection tasks are exempt because `passed` there is `bool(selection_correct)` from the
    transcript -- pytest does not decide the row. Three of the four ship no test file at all;
    `select-none` does, since it is the control where the right answer is to use no skill and
    just fix the code, and a digest for it is harmless rather than meaningful.
    """
    checked = 0
    for task_dir in sorted((ROOT / "tasks").iterdir()):
        if not task_dir.is_dir():
            continue
        task = harness.load_task(task_dir)
        if task.get("mode") == "selection":
            continue
        ap = harness.verdict_apparatus(
            harness.test_hashes(task["verdict"] or task["workspace"]))
        assert ap["verdict_sha"] and ap["verdict_files"] >= 1, (
            f"{task_dir.name} produces no verdict digest, so its rows could not be separated "
            f"from rows scored by a different version of the same file")
        checked += 1
    assert checked >= 4, f"only {checked} compliance tasks were checked; the glob is wrong"
