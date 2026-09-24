"""Every failing repetition must record WHICH assertion failed, not just how many did.

WHY THIS FILE EXISTS. `pytest_run` has always returned the full pytest output, and `run_rep`
has always thrown it away except for the last line -- so a row said "2 failed, 1 passed" and
nothing more. That is not enough to act on, and it misled twice:

  * A docx cell read as "the skill did not close the gap" when the open question was which of
    its two independent rules the model missed. The answer was recoverable only by re-running.
  * A 2/3 read as a partial success, when it was really 3/3 on the rule under test plus one
    repetition tripping a brittle structure guard -- a row that says nothing about the skill.

A compliance task deliberately scores several rules plus a guard, so "how many failed" and
"which failed" are different measurements and only the second one distinguishes a skill that
missed a rule from an instrument that is broken.
"""
import inspect
import pathlib
import subprocess
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness


def write_ws(tmp_path, body):
    (tmp_path / "test_compliance.py").write_text(textwrap.dedent(body))
    return tmp_path


def test_pytest_run_names_the_failing_tests(tmp_path):
    ws = write_ws(tmp_path, '''
        def test_one_rule():
            assert False, "body text is not Arial 12pt: [('Q3 held at 91%', 'Cambria', '11pt')]"

        def test_another_rule():
            assert False, "heading text is not black: [('Heading 1', 'Q3 Retention', '365f91')]"

        def test_a_rule_that_holds():
            assert True
        ''')
    rc, tail, out = harness.pytest_run(ws)
    assert rc != 0
    fails = harness.failed_assertions(out)
    assert len(fails) == 2, f"expected one entry per failing test, got {fails}"
    names = " ".join(fails)
    assert "test_one_rule" in names and "test_another_rule" in names
    assert "test_a_rule_that_holds" not in names
    # The offending VALUE is the actionable half: "not Arial" and "Cambria at 11pt" lead to
    # different next steps. pytest truncates this line to the terminal width, which is why
    # pytest_run widens COLUMNS -- without that the message is cut before it says anything.
    assert "Cambria" in names, f"the assertion message was truncated away: {fails}"


def test_a_green_run_records_no_failures(tmp_path):
    """An empty list must mean "nothing failed", so it cannot also mean "not captured"."""
    ws = write_ws(tmp_path, '''
        def test_it_holds():
            assert True
        ''')
    rc, tail, out = harness.pytest_run(ws)
    assert rc == 0
    assert harness.failed_assertions(out) == []


def test_entries_are_bounded(tmp_path):
    """A guard's message can dump every paragraph in the document. Rows are read by eye and
    by `sweep.py`, and one unbounded field makes both unusable."""
    ws = write_ws(tmp_path, f'''
        def test_dumps_the_document():
            assert False, "paragraph dump: {"x" * 4000}"
        ''')
    rc, tail, out = harness.pytest_run(ws)
    fails = harness.failed_assertions(out)
    assert len(fails) == 1 and len(fails[0]) <= 400


def test_run_rep_persists_the_failure_detail():
    """The call site, not just the helper -- this is the lesson from test_workspace_setup:
    the pattern was already known and simply not applied where it mattered."""
    src = inspect.getsource(harness.run_rep)
    assert '"pytest_failures": failed_assertions(out1)' in src, (
        "run_rep no longer records which assertion failed -- a failing cell then reports a "
        "pass rate with no reason attached, which is not a result anyone can act on")
    # out1 is the VERDICT's output. Recording the baseline's failures instead would be worse
    # than nothing: the baseline is REQUIRED to fail, so those entries are the expected state.
    assert "rc1, tail1, out1 = pytest_run(ws)" in src


def test_the_verdict_runner_asks_for_the_summary():
    """`-rf` is what puts `FAILED ...` in the output at all. Dropping it would empty the new
    field on every row while every test above still passes on a hand-built output string."""
    assert "-rf" in inspect.getsource(harness.pytest_run)


def test_sweep_reports_distinct_rules():
    src = (pathlib.Path(__file__).resolve().parent.parent / "sweep.py").read_text()
    assert "pytest_failures" in src, (
        "sweep.py prints the per-task summary a long run is actually watched through; if it "
        "still shows only the count, the detail is recorded and never read")
