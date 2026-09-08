#!/usr/bin/env python3
"""Negative control: prove the confound detector actually FIRES.

A detector that never triggers is indistinguishable from one that is broken, and the
clean 0/3 on cortex-pyfix-001 tells us nothing on its own. Two levels:

  (1) UNIT -- feed analyse_transcript() synthetic stream-json containing a Skill call
      and a Task (subagent) call, and assert both are picked up.
  (2) LIVE -- give a child a CLAUDE_CONFIG_DIR that DOES contain a skill, allow the
      Skill tool, invoke it, and confirm the real transcript surfaces it.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from harness import analyse_transcript
from lib_child import child_env


def synth(*content_blocks):
    lines = [json.dumps({"type": "system", "subtype": "init", "slash_commands": []})]
    for cb in content_blocks:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [cb]}}))
    lines.append(json.dumps({"type": "result", "subtype": "success", "is_error": False}))
    return "\n".join(lines)


print("=== (1) UNIT: does the parser see Skill and Task? ===")
cases = {
    "plain edit only": synth(
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "x.py"}}),
    "skill invoked": synth(
        {"type": "tool_use", "name": "Skill", "input": {"skill": "brand-guidelines"}}),
    "subagent invoked": synth(
        {"type": "tool_use", "name": "Task", "input": {"subagent_type": "Explore"}}),
    "both": synth(
        {"type": "tool_use", "name": "Skill", "input": {"skill": "pdf"}},
        {"type": "tool_use", "name": "Task", "input": {"subagent_type": "general-purpose"}}),
}
unit_ok = True
for label, stdout in cases.items():
    tr = analyse_transcript(stdout)
    expect_skill = "skill" in label or label == "both"
    expect_sub = "subagent" in label or label == "both"
    got_skill, got_sub = bool(tr["skills"]), bool(tr["subagents"])
    ok = (got_skill == expect_skill) and (got_sub == expect_sub)
    unit_ok &= ok
    print(f"  {label:18} skills={got_skill} subagents={got_sub} "
          f"tools={tr['tools']} -> {'OK' if ok else 'MISMATCH'}")

print("\n=== (2) LIVE: a real skill invocation must show up ===")
cfg = tempfile.mkdtemp(prefix="neg-cfg-")
sk = pathlib.Path(cfg) / "skills"
sk.mkdir(parents=True)
shutil.copytree(os.path.expanduser("~/.claude/skills/brand-guidelines"),
                sk / "brand-guidelines")
env = child_env(extra={"CLAUDE_CONFIG_DIR": cfg,
                       "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
                       "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
r = subprocess.run(
    ["claude", "-p", "/brand-guidelines Give the accent orange hex only.",
     "--allowedTools", "Read Skill", "--output-format", "stream-json", "--verbose"],
    env=env, capture_output=True, text=True, timeout=300)
tr = analyse_transcript(r.stdout)
print(f"  exit={r.returncode}")
print(f"  tools      : {tr['tools']}")
print(f"  skills     : {tr['skills']}")
print(f"  subagents  : {tr['subagents']}")
live_ok = bool(tr["skills"])
print(f"  -> skill detected: {live_ok}")

print("\n===== NEGATIVE CONTROL =====")
print(f"  unit parser fires correctly : {unit_ok}")
print(f"  live skill call detected    : {live_ok}")
print(f"  --> {'DETECTOR IS LIVE' if (unit_ok and live_ok) else 'DETECTOR SUSPECT'}")
