#!/usr/bin/env python3
"""Can Cortex verify that an EXPLICIT /skill-name was applied, where the transcript cannot?

The transcript shows no tool_use for an explicit slash-command skill -- the CLI expands
it client-side into the prompt. But Cortex sits on the wire and its request-phase event
carries inference.messages, i.e. the fully-assembled prompt. So the injected SKILL.md
text should be visible there.

Discipline: the marker check is done IN MEMORY and only a BOOLEAN plus token counts are
reported. Raw messages are never printed or persisted -- the session API is
unauthenticated and carries user content.

Arms: skill invoked vs the same question without the skill. The 'off' arm must NOT
contain the marker, otherwise the marker proves nothing.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import datetime as dt
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lib_child import child_env
from harness import read_events, parse_at, CORTEX_PROXY, CORTEX_CA, TARGET_HOST

# A phrase present in brand-guidelines/SKILL.md but very unlikely in a bare question.
MARKER = "Anthropic's official brand identity"
SECOND = "post-processing"


def build_cfg(with_skill):
    d = tempfile.mkdtemp(prefix="inj-cfg-")
    sk = pathlib.Path(d) / "skills"
    sk.mkdir(parents=True)
    if with_skill:
        shutil.copytree(os.path.expanduser("~/.claude/skills/brand-guidelines"),
                        sk / "brand-guidelines")
    return d


def arm(label, prompt, with_skill):
    cfg = build_cfg(with_skill)
    env = child_env(extra={
        "HTTPS_PROXY": CORTEX_PROXY, "HTTP_PROXY": CORTEX_PROXY,
        "NODE_EXTRA_CA_CERTS": CORTEX_CA,
        "CLAUDE_CONFIG_DIR": cfg,
        "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    t0 = dt.datetime.now().astimezone()
    r = subprocess.run(["claude", "-p", prompt, "--allowedTools", "Read Skill"],
                       env=env, capture_output=True, text=True, timeout=300)
    t1 = dt.datetime.now().astimezone()
    time.sleep(4)

    marker_hits, prompt_tokens, n_req = 0, 0, 0
    for ev in read_events():
        at = parse_at(ev.get("at", ""))
        if not at or not (t0 <= at <= t1):
            continue
        if TARGET_HOST and TARGET_HOST not in str(ev.get("host", "")):
            continue
        inf = ev.get("inference") or {}
        if ev.get("phase") == "request" and inf.get("messages"):
            n_req += 1
            # in-memory only; never printed
            blob = json.dumps(inf["messages"])
            if MARKER in blob or SECOND in blob:
                marker_hits += 1
        if ev.get("phase") == "response":
            prompt_tokens += inf.get("promptTokens") or 0

    print(f"  {label:26} exit={r.returncode} req_events={n_req} "
          f"marker_present={marker_hits > 0} prompt_tokens={prompt_tokens} "
          f"answer={r.stdout.strip()[:44]!r}")
    return {"label": label, "marker": marker_hits > 0,
            "prompt_tokens": prompt_tokens, "req_events": n_req}


if __name__ == "__main__":
    print(f"marker (not printed again): {len(MARKER)} chars from SKILL.md\n")
    on = arm("skill ON  (/brand-...)", "/brand-guidelines Give the accent orange hex only.", True)
    off = arm("skill OFF (bare question)", "Give the accent orange hex for Anthropic's brand, hex only.", False)
    print("\n===== SKILL INJECTION VISIBILITY =====")
    print(f"  ON  marker in wire prompt : {on['marker']}  (prompt_tokens={on['prompt_tokens']})")
    print(f"  OFF marker in wire prompt : {off['marker']}  (prompt_tokens={off['prompt_tokens']})")
    verdict = "PASS" if (on["marker"] and not off["marker"]) else "INCONCLUSIVE"
    print(f"  --> Cortex can confirm explicit skill injection: {verdict}")
