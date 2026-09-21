"""Tests for bin/profile-modelskill -- the consumer-facing CLI.

WHY THIS FILE EXISTS. The CLI is the surface a consumer sees, so its failure mode is not a
traceback, it is a plausible-looking table. Three ways that happens, all pinned below:

  a missing measurement rendered as zero   -- a repetition with no api timing is the FASTEST
                                              row in the cell if None becomes 0
  a confounded repetition averaged in      -- void, not failed; it must not reach a median
  membership that names the wrong files    -- a provenance block listing files the numbers do
                                              not come from is worse than no provenance

The permutation guard is here for a different reason: cost_significance.perm_test enumerates
every split, so a 29-vs-11 cell is 2.3 billion of them. Unguarded that is not a wrong number,
it is a hang, and the tempting fix -- quietly sampling instead -- would put a second estimator
under the same column heading.
"""
import importlib.machinery
import importlib.util
import inspect
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import profile as prof      # noqa: E402


def _load_cli():
    """Import the CLI by path: it is a bin/ script with no .py suffix, deliberately.

    A pip-installable distribution would put a top-level module named `profile` on sys.path
    and shadow the stdlib profiler for the whole environment, editable installs included.
    """
    path = ROOT / "bin" / "profile-modelskill"
    # An explicit SourceFileLoader is required: the file has no .py suffix, so import machinery
    # will not guess that it is Python source.
    spec = importlib.util.spec_from_file_location(
        "pms", path, loader=importlib.machinery.SourceFileLoader("pms", str(path)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pms = _load_cli()


def row(task="t1", arm="on", model="claude-sonnet-5", rep=1, *, cr=95_000, cw=5_000,
        uncached=100, out=1_000, calls=6, tools=5, wall=40.0, passed=True, confounded=False,
        api_ms=None):
    """A row that satisfies profile.integrity -- otherwise the cell is quarantined, and the
    test would pass for the wrong reason."""
    prompt = uncached + cr + cw
    r = {"task_id": task, "arm": arm, "model_requested": model, "model": model, "rep": rep,
         "passed": passed, "confounded": confounded, "confound_reasons": [],
         "prompt_tokens": prompt, "input_tokens": uncached, "cache_read_tokens": cr,
         "cache_write_tokens": cw, "completion_tokens": out, "output_tokens": out,
         "total_tokens": prompt + out, "llm_calls": calls, "tool_calls": tools,
         "wall_seconds": wall}
    if api_ms is not None:
        r["cli_duration_api_ms"] = api_ms
        r["cli_duration_ms"] = api_ms + 12_000
        r["cli_ttft_ms"] = 3_000
    return r


def write(tmp_path, name, rows):
    p = tmp_path / f"{name}.ndjson"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


# --------------------------------------------------------------- isolation from the grid

def test_default_out_cannot_be_reached_by_a_freeze():
    """The whole reason the default is out/modelskill and not out/runs.

    profile.RUN_DIRS is a fixed tuple, and `profile.py --freeze` pins whatever it globs there.
    A consumer's exploratory repetitions landing in that glob would join cells other people
    have published numbers for.
    """
    rel = pms.DEFAULT_OUT.relative_to(pms.ROOT).as_posix()
    assert rel not in prof.RUN_DIRS
    for d in prof.RUN_DIRS:
        assert not rel.startswith(d + "/") and rel != d


# --------------------------------------------------------------- missing vs zero

def test_missing_latency_is_a_dash_not_a_zero(tmp_path, capsys):
    write(tmp_path, "t1-on-claude-sonnet-5-1", [row(rep=i) for i in (1, 2, 3)])
    assert pms.report(tmp_path) == 0
    out = capsys.readouterr().out
    assert "carry no api timing" in out
    assert "0/3" in out, "the timed-row count must show that none of them were timed"
    # A zero would sort as the fastest cell in a comparison; a dash cannot.
    assert " 0.0 " not in out.split("LATENCY")[1].split("Wall time")[0]


def test_latency_is_reported_when_the_rows_carry_it(tmp_path, capsys):
    write(tmp_path, "t1-on-claude-sonnet-5-1",
          [row(rep=i, api_ms=48_120) for i in (1, 2, 3)])
    pms.report(tmp_path)
    out = capsys.readouterr().out
    lat = out.split("LATENCY")[1]
    assert "48.1" in lat, "api milliseconds should render as seconds"
    assert "3/3" in lat
    assert "carry no api timing" not in out


# --------------------------------------------------------------- confounds

def test_confounded_repetitions_are_excluded_from_every_number(tmp_path):
    rows = [row(rep=1), row(rep=2),
            # Void: a subagent spawn, a leaked skill, a substituted model. Ten times the
            # tokens, so if it were averaged in no median could hide it.
            row(rep=3, cr=950_000, calls=60, confounded=True)]
    write(tmp_path, "t1-on-claude-sonnet-5-1", rows)
    by, membership, total = pms.load_rows(tmp_path)
    m = pms.cell_metrics(by[("t1", "on", "claude-sonnet-5")], "claude-sonnet-5", "B")
    assert (m["n"], m["dropped"]) == (2, 1)
    assert m["tok"] == 101_100
    assert total == 3, "membership counts every row on disk, including the void ones"


# --------------------------------------------------------------- zero pass rate

def test_zero_pass_rate_does_not_divide_by_zero(tmp_path, capsys):
    """An OFF-arm cell that never passes is the NORMAL case -- that is the gate working."""
    write(tmp_path, "t1-off-claude-sonnet-5-1",
          [row(arm="off", rep=i, passed=False) for i in (1, 2, 3)])
    assert pms.report(tmp_path) == 0
    out = capsys.readouterr().out
    assert "undefined" in out, "cost per solved task does not exist when nothing is solved"


# --------------------------------------------------------------- cold-cache detector

def test_cold_baseline_is_per_cell_not_pooled(tmp_path, capsys):
    """A model whose steady-state cacheWrite share is simply higher is not permanently cold.

    haiku sits near 14% of prompt tokens where sonnet sits near 5%. Pooling the baseline
    flagged every haiku repetition in the grid -- 5 of 5 in one cell -- which tells a reader
    nothing about any repetition.
    """
    write(tmp_path, "t1-on-claude-haiku-4-5-20251001-1",
          [row(model="claude-haiku-4-5-20251001", rep=i, cr=86_000, cw=14_000)
           for i in (1, 2, 3, 4, 5)])
    write(tmp_path, "t1-on-claude-sonnet-5-1",
          [row(rep=1, cr=80_000, cw=20_000)] + [row(rep=i) for i in (2, 3, 4, 5)])
    pms.report(tmp_path)
    out = capsys.readouterr().out
    cold = out.split("COLD-CACHE")[1].split("These re-tier")[0]
    assert "haiku" not in cold, "a uniformly higher share is a model property, not a cold cache"
    assert cold.count("rep 1") == 1 and "sonnet-5" in cold


def test_a_tiny_cell_reports_no_cold_repetition(tmp_path, capsys):
    """With two repetitions the median IS the data, so a cold first rep becomes its own
    baseline and would be silently declared normal. Better to report nothing."""
    write(tmp_path, "t1-on-claude-sonnet-5-1",
          [row(rep=1, cr=80_000, cw=20_000), row(rep=2)])
    pms.report(tmp_path)
    assert "COLD-CACHE" not in capsys.readouterr().out


# --------------------------------------------------------------- provenance

def test_membership_names_only_the_files_the_numbers_came_from(tmp_path, capsys):
    write(tmp_path, "t1-on-claude-sonnet-5-1", [row(rep=i) for i in (1, 2, 3)])
    write(tmp_path, "t2-on-claude-sonnet-5-1", [row(task="t2", rep=i) for i in (1, 2, 3)])
    pms.report(tmp_path, tasks=["t1"])
    out = capsys.readouterr().out
    head = out.split("VOLUME")[0]
    assert "t1-on" in head and "t2-on" not in head
    assert "3 repetition(s)" in head


def test_partial_use_of_a_file_is_stated(tmp_path, capsys):
    """One file, two arms: the digest covers the whole file, so the row count must say so."""
    write(tmp_path, "mixed", [row(rep=1), row(rep=2), row(arm="off", rep=3, passed=False)])
    pms.report(tmp_path, arms=["on"])
    assert "2 of 3 row(s)" in capsys.readouterr().out


def test_internal_bookkeeping_never_reaches_the_json(tmp_path, capsys):
    write(tmp_path, "t1-on-claude-sonnet-5-1", [row(rep=i) for i in (1, 2, 3)])
    pms.report(tmp_path, as_json=True)
    blob = capsys.readouterr().out
    assert "_src" not in blob
    parsed = json.loads(blob)
    assert parsed["cells"][0]["n"] == 3 and parsed["membership"][0]["rows_used"] == 3


# --------------------------------------------------------------- significance guard

def test_intractable_exact_test_is_skipped_and_says_so(tmp_path, capsys):
    """29 v 11 is C(40,29) = 2.3 billion splits. Enumerating it is a hang, and swapping in a
    sampled p under the same heading would be a different estimator wearing the same label."""
    write(tmp_path, "t1-on-claude-haiku-4-5-20251001-1",
          [row(model="claude-haiku-4-5-20251001", rep=i, out=1_000 + i * 10)
           for i in range(1, 30)])
    write(tmp_path, "t1-on-claude-sonnet-5-1",
          [row(rep=i, out=2_000 + i * 10) for i in range(1, 12)])
    pms.report(tmp_path, significance=True)
    out = capsys.readouterr().out
    sig = out.split("SIGNIFICANCE")[1]
    assert "exact test skipped" in sig and "2,311,801,440 splits" in sig
    assert "sampled" not in sig.lower(), "no silent substitution of a different estimator"
    # The skipped pair must carry no p at all -- not a blank column that reads as 0.000.
    skipped = [ln for ln in sig.splitlines() if "skipped" in ln]
    assert len(skipped) == 1 and "0." not in skipped[0].split("skipped")[0]


def test_tractable_exact_test_reports_p_and_its_floor(tmp_path, capsys):
    write(tmp_path, "t1-on-claude-opus-5-1",
          [row(model="claude-opus-5", rep=i, out=1_000 + i * 5) for i in range(1, 6)])
    write(tmp_path, "t1-on-claude-sonnet-5-1",
          [row(rep=i, out=5_000 + i * 5) for i in range(1, 6)])
    pms.report(tmp_path, significance=True)
    sig = capsys.readouterr().out.split("SIGNIFICANCE")[1]
    # 5 v 5 -> C(10,5) = 252 splits -> the smallest two-sided p this design can produce is
    # 2/252 = 0.008. Printing p without that floor beside it overstates the result.
    assert "0.008" in sig
    assert "floor" in sig


# --------------------------------------------------------------- quarantine

def test_a_cell_failing_the_token_identities_is_quarantined(tmp_path, capsys):
    bad = row(rep=1)
    bad["total_tokens"] += 5_000          # total != prompt + completion
    write(tmp_path, "t1-on-claude-sonnet-5-1", [bad, row(rep=2), row(rep=3)])
    assert pms.report(tmp_path) == 1, "nothing reportable is left, so this is not a success"
    assert "QUARANTINED" in capsys.readouterr().out


# --------------------------------------------------------------- doctor

def test_doctor_blocks_on_a_missing_instrument(monkeypatch, capsys):
    """Cortex down is not a degraded run, it is an unmeasurable one: every token field is 0
    and the row self-flags no_cortex_inference_events."""
    monkeypatch.setattr(pms.harness, "cortex_alive", lambda: False)
    monkeypatch.setattr(pms.shutil, "which", lambda _: None)
    assert pms.cmd_doctor(None) == 1
    out = capsys.readouterr().out
    assert "BLOCK" in out and "abctl service start" in out
    assert "claude CLI" in out and "not on PATH" in out


def _locked():
    """name -> version from requirements.lock, so these tests track the real pins."""
    return {m.group(1).lower().replace("_", "-"): m.group(2) for m in re.finditer(
        r"(?m)^([A-Za-z0-9._-]+)==([^\s\\;]+)", (pms.ROOT / "requirements.lock").read_text())}


def test_a_drifted_apparatus_warns_and_does_not_block(monkeypatch):
    """A venv on the wrong interpreter still measures; it just stops being comparable to the
    frozen grid. That is the consumer's call, so it is a warning -- and a warning must not
    become an exit code, or `doctor` in a script fails for a judgement call."""
    pkgs = dict(_locked(), openpyxl="3.2.0")      # one bumped library, the realistic case
    monkeypatch.setattr(pms.harness, "apparatus", lambda: {
        "py_driver": "3.12.12", "py_venv": "3.12.12", "venv_packages": pkgs})
    rows = pms.apparatus_checks()
    assert [r[0] for r in rows] == [pms.WARN, pms.WARN]
    detail = " ".join(r[2] for r in rows)
    assert "3.14.3" in detail, "the warning must name the version that is pinned"
    assert "openpyxl 3.2.0 != 3.1.5" in detail, "and which library drifted, with both versions"
    assert pms.BLOCK not in [r[0] for r in rows]


def test_a_drifted_verdict_library_outranks_its_transitive_dependencies(monkeypatch):
    """With several drifts only three are shown, and alphabetical order shows `et-xmlfile`
    before `openpyxl` -- burying the one the reader chose and can act on."""
    monkeypatch.setattr(pms.harness, "apparatus", lambda: {
        "py_driver": "3.14.3", "py_venv": "3.14.3", "venv_packages": {}})
    detail = [r[2] for r in pms.apparatus_checks() if "packages" in r[1]][0]
    shown = detail.split("(")[1].split(")")[0]
    assert "openpyxl" in shown and "pytest" in shown
    assert "et-xmlfile" not in shown, "a transitive dependency took a slot from a chosen one"


def test_a_matching_apparatus_is_silent(monkeypatch):
    pin = (pms.ROOT / ".python-version").read_text().strip()
    monkeypatch.setattr(pms.harness, "apparatus", lambda: {
        "py_driver": "3.14.3", "py_venv": pin, "venv_packages": _locked()})
    assert [r[0] for r in pms.apparatus_checks()] == [pms.OK, pms.OK]


def test_a_missing_library_is_reported_as_missing_not_as_a_version(monkeypatch):
    """`None != 3.1.5` rendered naively reads as a version called None."""
    monkeypatch.setattr(pms.harness, "apparatus", lambda: {
        "py_driver": "3.14.3", "py_venv": (pms.ROOT / ".python-version").read_text().strip(),
        "venv_packages": {}})
    detail = [r[2] for r in pms.apparatus_checks() if "packages" in r[1]][0]
    assert "MISSING" in detail and "None" not in detail


def test_doctor_reports_credentials_by_digest_only():
    """Standing rule: never render a credential's contents. Three leaks in this project's
    history came from printing something believed safe, once via a neighbouring process's
    environment. The check is on the CHANNEL, not on intent."""
    secret = "sk-ant-not-a-real-token-abcdef123456"
    shown = pms._secret_shape(secret)
    assert secret not in shown
    assert "sha256:" in shown and len(shown.split("sha256:")[1]) == 8
    assert pms._secret_shape("") == "unset" and pms._secret_shape(None) == "unset"
    # And that doctor routes both token variables through it rather than formatting them.
    src = inspect.getsource(pms.doctor_checks)
    assert "_secret_shape(tok)" in src and "_secret_shape(key)" in src
    assert "{tok}" not in src and "{key}" not in src


# --------------------------------------------------------------- run planning

def test_run_is_planned_not_performed_under_dry_run(capsys):
    assert pms.main(["run", "--task", "cortex-pyfix-001", "--reps", "1", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would run" in out and "harness.py" in out
    assert "--out" in out, "every invocation must be pinned to the chosen output directory"


def test_few_repetitions_are_flagged_before_spending_money(capsys):
    pms.main(["compare", "--task", "cortex-pyfix-001", "--models", "claude-sonnet-5",
              "--reps", "2", "--dry-run"])
    out = capsys.readouterr().out
    assert "billable" in out
    assert "fewer than 3 repetitions" in out


def test_an_unpriced_model_still_runs_but_is_flagged(capsys):
    pms.main(["compare", "--task", "cortex-pyfix-001", "--models", "claude-not-in-card",
              "--reps", "5", "--dry-run"])
    out = capsys.readouterr().out
    assert "no rate card entry" in out
    assert "would run" in out, "volume and latency are still measurable without a price"


def test_unknown_task_lists_the_real_ones():
    with pytest.raises(SystemExit) as e:
        pms.resolve_task("no-such-task")
    assert "cortex-pyfix-001" in str(e.value)
