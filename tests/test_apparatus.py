"""Tests for the apparatus fields -- what measured a row, as distinct from what was measured.

WHY THIS FILE EXISTS. The venv is inside the experiment, not outside it: it runs the verdict
that decides passed/failed, and `harness.py` prepends its bin/ to the child's PATH so the agent
under test reaches the same libraries. So `openpyxl 3.1.5 -> 3.2` can move an xlsx compliance
pass rate with no model involved. Every published repetition was measured on 3.14.3 with
pytest 9.1.1 and openpyxl 3.1.5, and until these fields existed that was recoverable only from
a pyvenv.cfg mtime -- which is to say, not from the data at all.

The conformance tests below are deliberately STRICT rather than advisory. `profile-modelskill
doctor` warns a consumer whose venv has drifted, because they only want a number; a contributor
running pytest is about to produce rows that will be compared against the frozen grid, and a
drifted apparatus makes that comparison meaningless in a way no later analysis can detect.
"""
import inspect
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = (ROOT / ".python-version").read_text().strip()
LOCK = ROOT / "requirements.lock"


def locked():
    """name -> version from requirements.lock, ignoring the hash and comment lines."""
    return {m.group(1).lower().replace("_", "-"): m.group(2) for m in
            re.finditer(r"(?m)^([A-Za-z0-9._-]+)==([^\s\\;]+)", LOCK.read_text())}


# --------------------------------------------------------------- shape

def test_the_two_interpreters_are_separate_fields():
    """They answer different questions and can legitimately differ.

    A consumer may drive the CLI with system python3 3.12 against a 3.14.3 venv -- that is
    supported. Collapsing them into one `python_version` would make that row claim the verdict
    ran on 3.12.
    """
    a = harness.apparatus()
    assert set(a) == {"py_driver", "py_venv", "venv_packages"}
    assert a["py_driver"] == "%d.%d.%d" % sys.version_info[:3]
    assert re.fullmatch(r"\d+\.\d+\.\d+", a["py_venv"])


def test_plumbing_is_not_recorded_as_an_instrument():
    """pip is installed in the venv and scores nothing; a version bump to it is not a change
    to the instrument, and listing it would invite reading one as the other."""
    pkgs = harness.apparatus()["venv_packages"]
    assert "pip" not in pkgs and "setuptools" not in pkgs
    assert "openpyxl" in pkgs, "the library the xlsx verdicts assert through"


def test_it_is_cheap_enough_to_call_per_repetition():
    """Cached, so a 25-rep run pays for one subprocess and not twenty-five."""
    assert harness.apparatus() is harness.apparatus()


# --------------------------------------------------------------- conformance to the pins

def test_the_venv_matches_python_version():
    a = harness.apparatus()
    assert a["py_venv"] == PIN, (
        f".venv runs {a['py_venv']}, .python-version pins {PIN}. The venv runs the verdict and "
        f"sits on the agent's PATH, so this is a changed instrument, not a changed tool. "
        f"Rebuild: uv venv --python {PIN} && uv pip sync requirements.lock")


def test_the_venv_matches_requirements_lock():
    pkgs = harness.apparatus()["venv_packages"]
    want = locked()
    drift = {n: (pkgs.get(n), v) for n, v in want.items() if pkgs.get(n) != v}
    assert not drift, (
        f"installed vs locked: {drift}. A verdict library at an unlocked version can move a "
        f"pass rate on its own. Fix: uv pip sync requirements.lock")


# --------------------------------------------------------------- persisted, not merely computed

def test_run_rep_persists_them():
    """The defect this guards is the one that already happened once with the result event:
    a function that computes the right thing, and a row that never carries it."""
    assert "**apparatus()" in inspect.getsource(harness.run_rep), (
        "run_rep no longer records the apparatus -- a rebuilt venv becomes indistinguishable "
        "from a model regression")


def test_the_fields_are_json_serialisable_and_carry_no_paths():
    """Versions only. The venv path is a local absolute path and identifies a machine and a
    user account; `out/` already holds prompts, so nothing else needs to leak."""
    blob = json.dumps(harness.apparatus())
    assert str(ROOT) not in blob and "/Users/" not in blob
