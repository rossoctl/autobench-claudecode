"""Tests for copying task files into a repetition's fresh workspace.

WHY THIS FILE EXISTS. On 2026-09-09 a 25-repetition opus run died at repetition 1 with
`IsADirectoryError: tasks/xlsx-fin-colors/verdict/__pycache__`. Running the verdict tests by
hand leaves a `__pycache__/` inside `verdict/`; it is gitignored, so it is invisible in
`git status` and present on disk. The verdict copy was a flat per-entry `shutil.copy2`, which
dies on a directory.

The instructive part is that the project already knew this. `fresh_ws` uses `copytree` with an
IGNORE list and its docstring says, in as many words, that a stray cache directory "breaks a
flat copy outright". The lesson was written down and then not applied to the second copy site
140 lines below it. So these tests check the CALL SITES, not just that `IGNORE` exists --
knowing the right pattern was never the problem.
"""
import inspect
import pathlib
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

# The cache directories that appear from ordinary hand-verification of a task.
CACHE_DIRS = ["__pycache__", ".pytest_cache"]


def test_ignore_list_covers_the_caches_that_actually_appear():
    ignored = harness.IGNORE("anydir", CACHE_DIRS + ["keep_me.py"])
    assert set(ignored) == set(CACHE_DIRS)
    assert "keep_me.py" not in ignored


@pytest.mark.parametrize("cache", CACHE_DIRS)
def test_copytree_with_ignore_survives_a_cache_dir_where_a_flat_copy_dies(cache):
    """The mechanism: proves the failure is real and that the chosen fix removes it."""
    src = pathlib.Path(tempfile.mkdtemp())
    (src / "test_compliance.py").write_text("def test_x(): pass\n")
    (src / cache).mkdir()
    (src / cache / "stale.pyc").write_bytes(b"\x00")

    # The old approach: flat per-entry copy2 over iterdir().
    flat = pathlib.Path(tempfile.mkdtemp())
    with pytest.raises(IsADirectoryError):
        for item in src.iterdir():
            shutil.copy2(item, flat / item.name)

    # The fix.
    dst = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(src, dst, ignore=harness.IGNORE, dirs_exist_ok=True)
    assert (dst / "test_compliance.py").exists(), "the verdict test must arrive"
    assert not (dst / cache).exists(), f"{cache} must not be copied in"


def test_both_copy_sites_ignore_caches():
    """Neither copy site may use a flat copy2 over a directory listing.

    This is the guard for the real defect: a second copy site that did not inherit the first
    one's lesson. If a third copy site is ever added, this fails until it does.
    """
    src = inspect.getsource(harness.run_rep) + inspect.getsource(harness.fresh_ws)
    trees = [ln.strip() for ln in src.splitlines()
             if "copytree(" in ln and not ln.strip().startswith("#")]
    assert len(trees) >= 2, f"expected the verdict and workspace copies, found: {trees}"
    for ln in trees:
        assert "ignore=IGNORE" in ln, f"copy site without the cache filter: {ln}"
    flat = [ln.strip() for ln in src.splitlines()
            if "copy2(" in ln and not ln.strip().startswith("#")]
    assert not flat, f"flat copy2 is what broke: {flat}"


def test_verdict_arrives_after_the_tamper_check():
    """Ordering matters as much as the copy itself.

    The verdict must be installed AFTER `test_hashes` is taken, or a hidden-verdict task
    compares {} against {test_compliance.py} and every repetition is scored as tampered --
    it could then never pass however green pytest was. Cheap to assert, catastrophic to get
    wrong, and invisible in any single repetition's output.
    """
    src = inspect.getsource(harness.run_rep)
    tamper_check = src.index("after_tests = test_hashes(ws)")
    verdict_install = src.index('copytree(task["verdict"]')
    assert verdict_install > tamper_check, (
        "the verdict is installed BEFORE the tamper check is taken, so every "
        "hidden-verdict repetition will be scored as tampered")
