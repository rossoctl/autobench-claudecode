#!/usr/bin/env python3
"""Negative control: prove the confound detector actually FIRES.

A detector that never triggers is indistinguishable from one that is broken, so a clean
0/3 on a task tells us nothing on its own. Two levels, deliberately separated because they
cost different amounts:

  (1) UNIT (free, always runs, gates a run)
      Delegates to `tests/test_confound_detector.py` via pytest. The synthetic cases live
      THERE, not here -- the two used to be separate copies, and the copy in this file only
      ever exercised `Task`, the one subagent name that was never the bug. One source of
      truth, mutation-checked: reintroducing the original `("Task",)` constant fails 6 of
      the 16 tests.

  (2) LIVE (costs one `claude -p` invocation, opt-in with --live)
      A MODEL-SELECTED skill, which is a real `Skill` tool_use in the transcript.

WHAT THIS FILE USED TO GET WRONG, and why the fix matters more than it sounds. The live
half invoked an EXPLICIT `/brand-guidelines` and asserted a `Skill` tool_use appeared. It
cannot: the CLI expands an explicit slash-command skill client-side into the prompt, so the
stream-json holds no tool_use at all -- a fact this project had already measured and
written down. So the control printed `DETECTOR SUSPECT` on a perfectly healthy system,
every single run. A control that fails when nothing is wrong is worse than no control,
because it teaches you to ignore it.

Hence the split by invocation path, which is the thing to keep straight:
  * MODEL-SELECTED skill  -> real `Skill` tool_use  -> the transcript is authoritative
                             (this file, --live)
  * EXPLICIT /skill-name  -> NO tool_use anywhere   -> verify on the WIRE via Cortex
                             (tools/skill_injection_probe.py)

Exits non-zero on failure so it can gate a run instead of scrolling past.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import analyse_transcript          # noqa: E402
from lib_child import child_env                 # noqa: E402

VENV_PY = str(ROOT / ".venv" / "bin" / "python")

# A model-selected fixture: the prompt must NOT name a skill, so firing one is the model's
# own choice and therefore a genuine Skill tool_use. Phase 3 measured this path 12/12
# correct, so a failure here is the detector, not the task.
LIVE_TASK = ROOT / "tasks" / "select-spreadsheet"


def unit():
    """The free half: run the real test suite."""
    print("=== (1) UNIT: synthetic positives for every declared tool name ===")
    py = VENV_PY if pathlib.Path(VENV_PY).exists() else sys.executable
    r = subprocess.run([py, "-m", "pytest", "-q", str(ROOT / "tests")],
                       cwd=str(ROOT), capture_output=True, text=True)
    print("  " + "\n  ".join(r.stdout.strip().splitlines()[-6:]))
    return r.returncode == 0


def live():
    """The paid half: a model-selected skill must surface as a real Skill tool_use."""
    print("\n=== (2) LIVE: a MODEL-SELECTED skill must appear in the transcript ===")
    task = json.loads((LIVE_TASK / "meta.json").read_text())
    prompt = (LIVE_TASK / "prompt.md").read_text()
    expected = task.get("expected_skill")
    print(f"  fixture   : {LIVE_TASK.name} (prompt names no skill; expects {expected!r})")

    cfg = tempfile.mkdtemp(prefix="neg-cfg-")
    skills = pathlib.Path(cfg) / "skills"
    skills.mkdir(parents=True)
    for sk in task.get("candidate_skills") or []:
        src = pathlib.Path(os.path.expanduser(f"~/.claude/skills/{sk}"))
        if not src.exists():
            print(f"  !! candidate skill {sk!r} not installed at {src}")
            return False
        shutil.copytree(src, skills / sk)

    ws = tempfile.mkdtemp(prefix="neg-ws-")
    allowed = " ".join(["Read", "Write", "Edit", "Skill"]
                       + (task.get("allowed_tools_extra") or []))
    env = child_env(extra={"CLAUDE_CONFIG_DIR": cfg,
                           "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
                           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    r = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", allowed,
         "--output-format", "stream-json", "--verbose"],
        env=env, cwd=ws, capture_output=True, text=True, timeout=900)
    tr = analyse_transcript(r.stdout)
    print(f"  exit      : {r.returncode}")
    print(f"  tools     : {tr['tools']}")
    print(f"  skills    : {tr['skill_names']}")
    print(f"  subagents : {tr['subagents']}")

    ok = bool(tr["skill_names"])
    if ok and expected:
        ok = expected in tr["skill_names"]
    print(f"  -> a model-selected Skill tool_use was detected: {ok}")
    if not ok:
        print("     NOTE a wrong-skill or no-skill answer can be the MODEL's choice rather")
        print("     than a detector fault. Re-run before concluding; check `tools` above")
        print("     for whether it did the work some other way.")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="also run the LIVE half (costs one claude -p invocation)")
    a = ap.parse_args()

    unit_ok = unit()
    live_ok = live() if a.live else None

    print("\n===== NEGATIVE CONTROL =====")
    print(f"  unit  : {'PASS' if unit_ok else 'FAIL'}")
    print(f"  live  : {'PASS' if live_ok else 'FAIL' if live_ok is False else 'skipped (--live)'}")
    good = unit_ok and (live_ok is not False)
    print(f"  --> {'DETECTOR IS LIVE' if good else 'DETECTOR SUSPECT'}")
    sys.exit(0 if good else 1)
