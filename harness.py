#!/usr/bin/env python3
"""Claude Code benchmark harness -- minimal end-to-end driver for one task.

Shape (per the agreed design): per task -> fresh workspace -> headless `claude -p` ->
programmatic verdict -> correlate Cortex events in [t0,t1] -> emit one NDJSON row.
No MCP provider, no A2A shim, no Kubernetes, no AutoBench.

Three spiked facts this relies on:
  * `claude -p --allowedTools "Read Edit Write Bash(python*) Bash(pytest*)"` edits
    files unattended (no --dangerously-skip-permissions).
  * HTTPS_PROXY + NODE_EXTRA_CA_CERTS are honoured from the CHILD ENVIRONMENT, so the
    user's global ~/.claude/settings.json stays untouched ("0 of 3 set").
  * CLAUDE_CONFIG_DIR -- NOT HOME -- scopes user skills; bundled skills need
    CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1 as a separate switch.

Two deliberate anti-footgun choices:
  * The verdict is `pytest -q` exit 0 AND every test_*.py byte-identical. Green tests
    alone are not a pass: deleting or rewriting the test also makes pytest green.
  * Persisted Cortex fields are a WHITELIST. Raw events carry `inference.messages` and
    `inference.completion` -- i.e. full prompts and model output -- and the session API
    is unauthenticated. Never let those reach an artifact.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from lib_child import child_env

# Repo-relative, with env overrides. `out/` is gitignored: it holds the SSE capture,
# which contains RAW PROMPTS, and the per-run NDJSON.
ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("HARNESS_OUT", ROOT / "out"))
VENV = pathlib.Path(os.environ.get("HARNESS_VENV", ROOT / ".venv"))
VENV_BIN = str(VENV / "bin")
VENV_PY = str(VENV / "bin" / "python")
SSE_FILE = OUT / "events" / "stream.sse"
SESSION_API = "http://127.0.0.1:47601"
CORTEX_PROXY = "http://127.0.0.1:47600"
CORTEX_CA = os.path.expanduser("~/.cortex/ca/ca.crt")
TARGET_HOST = (os.environ.get("ANTHROPIC_BASE_URL", "")
               .replace("https://", "").replace("http://", "").rstrip("/"))
# Tool names that indicate work happening OUTSIDE the single agent loop we mean to
# measure. Cortex counts such calls (they are real, billable, and traverse the same proxy
# because the child's HTTPS_PROXY is inherited by subprocesses) but cannot attribute them,
# so the TASK is no longer the unit it appears to be. Measured impact: 2.7-8.2x the tokens.
SUBAGENT_TOOLS = ("Agent", "Task")
BACKGROUND_TOOLS = ("TaskOutput", "TaskStop")
ALLOWED_TOOLS = "Read Edit Write Bash(python*) Bash(pytest*)"
# Pin the model explicitly. Inheriting it is not safe: the model actually used came from
# ANTHROPIC_MODEL in the ambient environment, which differed from settings.json, so
# run-to-run comparisons would drift silently. --model beats both env and settings, and
# `model_pin_honoured` below checks on the wire that it really did.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Fields safe to persist. Everything else in an event is dropped, content included.
EVENT_KEEP = ("at", "requestId", "sessionId", "host", "phase", "direction",
              "statusCode", "durationMs", "tunnel")
INF_KEEP = ("model", "promptTokens", "completionTokens", "totalTokens", "inputTokens",
            "outputTokens", "cacheReadTokens", "cacheWriteTokens", "reasoningTokens",
            "maxTokens", "stream", "isAction", "finishReason")
# The CLI's own `result` event -- the last line of --output-format stream-json -- is a
# SECOND, PROXY-INDEPENDENT instrument. Everything else in the measurement block comes from
# Cortex, so a row taken with the proxy absent measures nothing; these fields survive that.
# They are also the only timing here that is not wall-clock: duration_api_ms excludes local
# tool execution, which wall_seconds cannot separate (wall moved x1.34-1.81 for two models
# doing provably identical work, purely from machine load).
#
# WHITELISTED for the same reason as the Cortex fields, and it is not a formality: the
# result event also carries `result`, the final assistant text.
RESULT_KEEP = ("duration_ms", "duration_api_ms", "ttft_ms", "ttft_stream_ms",
               "time_to_request_ms", "num_turns", "total_cost_usd")


# ---------------------------------------------------------------- infrastructure

def cortex_alive():
    try:
        with urllib.request.urlopen(f"{SESSION_API}/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def sse_alive():
    r = subprocess.run(["pgrep", "-f", "47601/v1/events"], capture_output=True, text=True)
    return r.returncode == 0


class RunLock:
    """Serialise harness runs on this machine.

    Cortex events are correlated by TIME WINDOW against a single shared proxy, so two
    concurrent runs interleave: a smoke test run beside a sweep picked up the sweep's
    events and was flagged `multiple_models`. The confound detector caught it, but the
    right fix is to make the overlap impossible rather than merely detectable.

    Note this only guards runs started through the harness. Interactive Claude Code use on
    the same machine still lands in the same Cortex, which is why the per-invocation proxy
    env matters: an interactive session has no HTTPS_PROXY and so stays out of the window.
    """

    def __init__(self, path, wait_s=7200):
        self.path = pathlib.Path(path)
        self.wait_s = wait_s
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("w")
        waited = 0.0
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if waited == 0:
                    print("  another harness run holds the lock; waiting...")
                if waited >= self.wait_s:
                    raise RuntimeError(f"run lock still held after {self.wait_s}s")
                time.sleep(2)
                waited += 2

    def __exit__(self, *exc):
        if self.fh is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
        return False


class Capture:
    """Own the Cortex SSE capture for the duration of a run.

    Cortex's session store is in-memory with a 30-minute TTL, so the file on disk is the
    only durable record. Leaving that to a hand-started `nohup curl` means its absence is
    silent -- and a dead capture yields zero events, indistinguishable from "the proxy saw
    nothing". So the harness starts it, guarantees it is producing, and stops it.

    An already-running capture (e.g. a long-lived one across many runs) is adopted rather
    than duplicated, since two readers would both work but only confuse the log.
    """

    def __init__(self):
        self.proc = None
        self.adopted = False

    def __enter__(self):
        SSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if sse_alive():
            self.adopted = True
            return self
        self.fh = SSE_FILE.open("a")
        self.proc = subprocess.Popen(
            ["curl", "-sN", "--no-buffer", f"{SESSION_API}/v1/events"],
            stdout=self.fh, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.25)
            if sse_alive():
                break
        else:
            raise RuntimeError("could not start the Cortex SSE capture")
        return self

    def __exit__(self, *exc):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.fh.close()
        return False


def read_events():
    if not SSE_FILE.exists():
        return []
    out = []
    for line in SSE_FILE.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("data:"):
            s = s[5:].strip()
        if not s.startswith("{"):
            continue
        try:
            out.append(json.loads(s))
        except Exception:
            pass
    return out


def slim(ev):
    rec = {k: ev.get(k) for k in EVENT_KEEP if ev.get(k) is not None}
    inf = ev.get("inference") or {}
    kept = {k: inf[k] for k in INF_KEEP if k in inf and inf[k] is not None}
    if kept:
        rec["inference"] = kept
    return rec


def parse_at(s):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


# ---------------------------------------------------------------- task + verdict

def load_task(task_dir):
    """A task dir is prompt.md + workspace/, plus an optional meta.json.

    meta.json may set {"skill": "<name>", "skill_marker": "<phrase from its SKILL.md>"}.
    When set, the skill is copied into the curated CLAUDE_CONFIG_DIR, the prompt is
    prefixed with /<skill>, and the marker is checked ON THE WIRE (see run_rep) --
    because an explicit /skill-name is expanded client-side into the prompt and so
    produces NO tool_use, i.e. the transcript cannot confirm it was applied.
    """
    d = pathlib.Path(task_dir)
    meta = {}
    if (d / "meta.json").exists():
        meta = json.loads((d / "meta.json").read_text())
    vd = d / "verdict"
    return {"task_id": d.name,
            "prompt": (d / "prompt.md").read_text().strip(),
            "workspace": d / "workspace",
            # HIDDEN verdict tests, copied in only AFTER the agent exits.
            # Rationale: for a *compliance* task the test enumerates the conventions, so
            # an agent that can read it just complies -- the benchmark would measure
            # "can you read a test" and BOTH arms would pass, destroying the
            # discriminator. Tasks whose tests ARE the spec (cortex-pyfix) keep them in
            # workspace/ instead, where visibility is correct.
            "verdict": vd if vd.exists() else None,
            "skill": meta.get("skill"),
            "skill_marker": meta.get("skill_marker"),
            # Extra --allowedTools entries this task needs. The docx skill mandates
            # docx-js (Node), so without Bash(node*)/Bash(npm*) the agent silently falls
            # back to python-docx and we would be measuring the fallback, not the skill.
            "allowed_tools_extra": meta.get("allowed_tools_extra") or [],
            # SELECTION mode: a different benchmark from the on/off compliance arms.
            # All candidate skills are made available, the prompt does NOT name one, and
            # the verdict is "did the right skill fire" -- taken from the transcript,
            # which DOES see model-selected skills (unlike explicit /skill-name).
            "mode": meta.get("mode") or "compliance",
            "expected_skill": meta.get("expected_skill"),
            "candidate_skills": meta.get("candidate_skills") or []}


IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".venv", "venv")


def fresh_ws(task):
    """Copy the task workspace to a fresh temp dir.

    copytree (not copy2 per entry) so nested dirs work, and ignore build/test caches:
    a stray .pytest_cache from verifying the task by hand would otherwise be shipped
    into every repetition -- and, being a directory, breaks a flat copy outright.
    """
    ws = tempfile.mkdtemp(prefix=f"{task['task_id']}-")
    shutil.copytree(task["workspace"], ws, ignore=IGNORE, dirs_exist_ok=True)
    return ws


def test_hashes(ws):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pathlib.Path(ws).glob("test_*.py"))}


def pytest_run(ws):
    r = subprocess.run([VENV_PY, "-m", "pytest", "-q"], cwd=ws,
                       capture_output=True, text=True, timeout=300)
    out = (r.stdout + r.stderr).strip()
    return r.returncode, (out.splitlines()[-1] if out.splitlines() else ""), out


# ---------------------------------------------------------------- transcript

def analyse_transcript(stdout):
    """Which tools/skills/subagents ACTUALLY ran. Tokens come from Cortex; attribution
    comes from here. Flag the task confounded if the invoked set exceeds expectations --
    the same 'test for the impossible combination' discipline used elsewhere."""
    tools, skills, subagents, turns, result = [], [], [], 0, None
    skill_names, background = [], []
    for line in stdout.splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            turns += 1
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") != "tool_use":
                    continue
                name = c.get("name")
                tools.append(name)
                if name in ("Skill", "SlashCommand"):
                    inp = c.get("input") or {}
                    # The skill name lives under different keys depending on the tool;
                    # keep the raw blob too, for the confound message.
                    nm = (inp.get("skill") or inp.get("command")
                          or inp.get("name") or "")
                    skill_names.append(str(nm).lstrip("/").split()[0] if nm else "?")
                    skills.append(json.dumps(inp)[:120])
                elif name in SUBAGENT_TOOLS:
                    # Claude Code's subagent tool is `Agent` on this build (`Task` on
                    # others). Matching only "Task" made this detector silently blind:
                    # five runs spawned subagents and none were flagged.
                    subagents.append((c.get("input") or {}).get("subagent_type")
                                     or name)
                elif name in BACKGROUND_TOOLS:
                    # Not a subagent spawn, but evidence of async work whose LLM calls
                    # land in our window without belonging to the main loop.
                    background.append(name)
        elif t == "result":
            result = ev
    return {"tools": tools, "skills": skills, "skill_names": skill_names,
            "subagents": subagents, "background": background,
            "assistant_turns": turns, "result": result}


def result_fields(res):
    """Whitelisted timing/usage from the CLI's own `result` event, every key prefixed `cli_`.

    Prefixed because these are a DIFFERENT INSTRUMENT from the Cortex columns sitting beside
    them: they are what the client believed happened, counted before the request left the
    machine. `cli_total_cost_usd` especially -- that is the CLI's own estimate at its list
    prices, NOT this gateway's rates, so money still has to come from pricing.cost().

    Absent (timed out, killed, or a CLI build without the field) -> every key present and
    None, so the column exists in every row and a missing measurement can never be read as a
    zero one.
    """
    res = res or {}
    out = {f"cli_{k}": res.get(k) for k in RESULT_KEEP}
    # Shape-based filter rather than a key list: `usage` gains nested sub-objects across CLI
    # versions (cache_creation breakdowns, server_tool_use) and an int is the only thing a
    # token count can be. Same discipline as the Cortex whitelist -- decide what may be kept,
    # not what must be dropped.
    usage = {k: v for k, v in (res.get("usage") or {}).items() if isinstance(v, int)}
    out["cli_usage"] = usage or None
    return out


# ---------------------------------------------------------------- one repetition

def run_rep(task, rep, cfg_dir, model=DEFAULT_MODEL, arm="on", timeout=1800):
    ws = fresh_ws(task)
    before_tests = test_hashes(ws)
    if task.get("mode") == "selection" and not task.get("verdict"):
        # Selection tasks are scored from the transcript, not from a test suite, so an
        # empty workspace is expected and "no tests ran" is not a broken baseline.
        rc0, tail0, baseline_ok = None, "<selection task: transcript-scored>", True
    elif task.get("verdict"):
        # Hidden-verdict task: the workspace ships no tests, so there is no baseline to
        # take. The equivalent guard is the OFF-arm pre-screen -- a task the agent
        # passes WITHOUT the skill is not measuring the skill and must be discarded.
        rc0, tail0, baseline_ok = None, "<hidden verdict: no in-workspace baseline>", True
    else:
        rc0, tail0, out0 = pytest_run(ws)
        baseline_ok = (rc0 != 0 and "error" not in tail0.lower()
                       and "no tests ran" not in out0.lower())

    env = child_env(extra={
        # per-invocation Cortex capture; global settings stay untouched
        "HTTPS_PROXY": CORTEX_PROXY, "HTTP_PROXY": CORTEX_PROXY,
        "NODE_EXTRA_CA_CERTS": CORTEX_CA,
        # skill isolation: empty skills/ + bundled skills off => any skill is a confound
        "CLAUDE_CONFIG_DIR": cfg_dir,
        "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "PATH": VENV_BIN + os.pathsep + os.environ.get("PATH", ""),
        "VIRTUAL_ENV": str(VENV),
    })

    selection = task.get("mode") == "selection"
    prompt = task["prompt"]
    tools = ALLOWED_TOOLS
    if task.get("allowed_tools_extra"):
        tools = tools + " " + " ".join(task["allowed_tools_extra"])
    use_skill = bool(task.get("skill")) and arm == "on"
    if selection:
        # Deliberately do NOT name a skill in the prompt: the point is whether the model
        # picks the right one from the descriptions on its own.
        tools = tools + " Skill"
    elif use_skill:
        prompt = f"/{task['skill']} " + prompt
        tools = tools + " Skill"
    cmd = ["claude", "-p", prompt, "--add-dir", ws,
           "--model", model,
           "--allowedTools", tools,
           "--output-format", "stream-json", "--verbose"]

    t0 = dt.datetime.now().astimezone()
    wall0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True,
                           timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r = type("R", (), {"returncode": -1, "stdout": e.stdout or "", "stderr": "TIMEOUT"})()
        timed_out = True
    wall = time.time() - wall0
    t1 = dt.datetime.now().astimezone()
    time.sleep(4)  # let the final response event land in the SSE file

    tr = analyse_transcript(r.stdout)
    # Tamper check FIRST, while the workspace still holds only the agent's own files.
    # Taking it after installing the hidden verdict would compare {} against
    # {test_compliance.py} and mark every hidden-verdict task as tampered -- such a task
    # could then never pass, no matter how green pytest was.
    after_tests = test_hashes(ws)
    tests_untouched = before_tests == after_tests
    if task.get("verdict"):
        # Arrives only now, so it cannot be read or tampered with by the agent.
        # copytree + IGNORE for the same reason as fresh_ws: running the verdict tests by
        # hand leaves a __pycache__/ inside verdict/, and a flat per-entry copy2 dies on it
        # with IsADirectoryError. That is exactly what happened on 2026-09-09, killing a
        # 25-rep opus run at rep 1 -- the lesson was documented in fresh_ws and never
        # applied here, 140 lines away.
        shutil.copytree(task["verdict"], ws, ignore=IGNORE, dirs_exist_ok=True)
    rc1, tail1, out1 = pytest_run(ws)
    # "no artifact produced" is NOT the same failure as "artifact is non-compliant".
    # The first means the agent could not do the work at all -- e.g. its skill mandates a
    # Node library and Bash(node*) was not in the allow-list, which is a harness fault and
    # must never be scored as a compliance result.
    no_artifact = (not selection and "produced" in out1
                   and "no " in out1.lower() and rc1 != 0)
    passed = (rc1 == 0) and tests_untouched

    # Cortex correlation: response-phase events to the target host inside [t0,t1].
    win = []
    for ev in read_events():
        at = parse_at(ev.get("at", ""))
        if not at or not (t0 <= at <= t1):
            continue
        if TARGET_HOST and TARGET_HOST not in str(ev.get("host", "")):
            continue
        win.append(ev)
    resp = [e for e in win if e.get("phase") == "response"
            and (e.get("inference") or {}).get("totalTokens")]
    tunnels = [e for e in win if e.get("tunnel")]

    # Wire-level skill verification. The marker is matched IN MEMORY against
    # inference.messages and only a boolean escapes -- those messages are the full
    # prompt, and the session API is unauthenticated.
    skill_on_wire = None
    if task.get("skill_marker"):
        skill_on_wire = False
        for e in win:
            inf = e.get("inference") or {}
            if e.get("phase") == "request" and inf.get("messages"):
                if task["skill_marker"] in json.dumps(inf["messages"]):
                    skill_on_wire = True
                    break

    def tot(k):
        return sum((e.get("inference") or {}).get(k) or 0 for e in resp)

    models = sorted({(e.get("inference") or {}).get("model") for e in resp} - {None})

    # --- selection verdict -------------------------------------------------------
    fired = [s for s in tr.get("skill_names", []) if s and s != "?"]
    selection_correct = None
    if selection:
        exp = task.get("expected_skill")
        if exp is None:
            # Negative case: an over-eager selector is as wrong as a blind one, so a
            # selection benchmark that only tests true positives is half a benchmark.
            selection_correct = not fired
        else:
            selection_correct = exp in fired
        passed = bool(selection_correct)

    confounds = []
    # An explicit /skill-name yields NO tool_use, so a Skill tool_use means the MODEL
    # reached for a skill itself. That is only a CONFOUND when it is a DIFFERENT skill:
    # re-invoking the task's own skill is benign (observed on the ON arm, where the CLI
    # had already injected it and the model called Skill for the same name anyway).
    if selection:
        # Firing a skill IS the measurement here, so it is never a confound. Only note
        # when several fired, which muddies attribution.
        if len(set(fired)) > 1:
            confounds.append(f"multiple_skills_fired:{sorted(set(fired))}")
    else:
        foreign = [s for s in tr["skills"]
                   if not (task.get("skill") and f'"{task["skill"]}"' in s)]
        if foreign:
            confounds.append(f"foreign_skill_invoked:{foreign}")
    if tr["subagents"]:
        confounds.append(f"subagent_invoked:{tr['subagents']}")
    # NOTE: background tools (TaskOutput/TaskStop) are recorded in `background_tools` but
    # are deliberately NOT a confound. A background task here is a background SHELL command;
    # it issues no LLM calls of its own, so every token still belongs to the one agent loop
    # we are measuring. Treating it as a confound was wrong twice over: mechanically, and
    # empirically -- in both pptx cells the single most expensive repetition carries NO
    # background tool (28 calls/1.32M vs 27 flagged; 39 vs 47 flagged), so the flag marks a
    # SUBSET of a bimodal cost mode. Excluding on it therefore biases the median instead of
    # cleaning it, which is how the published pptx overhead came to be quoted as 3.0x.
    if task.get("skill_marker") and not selection:
        if arm == "on" and skill_on_wire is False:
            confounds.append("expected_skill_not_on_wire")
        # The OFF arm is the control: if the skill text reached the wire anyway the
        # comparison is void, so that is a confound too.
        if arm == "off" and skill_on_wire is True:
            confounds.append("skill_leaked_into_off_arm")
    if not baseline_ok:
        confounds.append("bad_baseline")
    if not resp:
        confounds.append("no_cortex_inference_events")
    if no_artifact:
        confounds.append("no_artifact_produced")
    if len(models) > 1:
        confounds.append(f"multiple_models:{models}")
    # Trust the wire, not the flag: confirm the requested model is what was actually
    # billed. A silently-substituted model would invalidate any cross-run comparison.
    pin_honoured = bool(models) and all(model in m for m in models)
    if models and not pin_honoured:
        confounds.append(f"model_pin_ignored:requested={model} saw={models}")

    rec = {
        "task_id": task["task_id"], "rep": rep,
        "t0": t0.isoformat(), "t1": t1.isoformat(),
        "passed": passed, "pytest_rc": rc1, "pytest_tail": tail1,
        "baseline_ok": baseline_ok, "baseline_tail": tail0,
        "hidden_verdict": bool(task.get("verdict")),
        "no_artifact_produced": no_artifact,
        "tests_untouched": tests_untouched,
        "child_exit": r.returncode, "timed_out": timed_out,
        "wall_seconds": round(wall, 1),
        # Client-side timing, from the CLI's result event. `cli_duration_api_ms` is the
        # latency measure; wall_seconds includes local tool execution and machine load.
        **result_fields(tr.get("result")),
        "assistant_turns": tr["assistant_turns"],
        "tool_calls": len(tr["tools"]),
        "tool_histogram": {t: tr["tools"].count(t) for t in sorted(set(tr["tools"]))},
        "skills_invoked": tr["skills"], "subagents_invoked": tr["subagents"],
        "background_tools": tr.get("background") or [],
        "arm": arm, "allowed_tools": tools, "mode": task.get("mode"),
        "skills_fired": fired, "selection_correct": selection_correct,
        "expected_selection": task.get("expected_skill"),
        "expected_skill": task.get("skill") if use_skill else None,
        "skill_on_wire": skill_on_wire,
        "llm_calls": len(resp), "cortex_tunnels": len(tunnels),
        "model_requested": model,
        "model": models[0] if len(models) == 1 else models,
        "model_pin_honoured": pin_honoured,
        "prompt_tokens": tot("promptTokens"), "completion_tokens": tot("completionTokens"),
        "total_tokens": tot("totalTokens"), "input_tokens": tot("inputTokens"),
        "output_tokens": tot("outputTokens"),
        "cache_read_tokens": tot("cacheReadTokens"),
        "cache_write_tokens": tot("cacheWriteTokens"),
        "confounded": bool(confounds), "confound_reasons": confounds,
        "workspace": ws,
        "cortex_events": [slim(e) for e in win],   # whitelisted, no prompts/completions
    }
    if r.returncode != 0:
        rec["stderr_tail"] = (r.stderr or "")[-300:]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default=str(OUT / "runs"))
    ap.add_argument("--arm", choices=["on", "off", "select"], default="on",
                    help="on = task skill available and invoked; off = control")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"model pinned via --model (default {DEFAULT_MODEL})")
    a = ap.parse_args()

    if not cortex_alive():
        sys.exit("Cortex session API not reachable on 47601 -- "
                 "start it with: abctl service start")

    task = load_task(a.task_dir)
    # Curated CLAUDE_CONFIG_DIR (NOT HOME -- HOME is not the lookup root) holding
    # EXACTLY the task's skill, or nothing at all. Bundled skills are switched off
    # separately in run_rep, so an unlisted skill simply cannot resolve.
    cfg_dir = tempfile.mkdtemp(prefix="harness-cfg-")
    skills_dir = pathlib.Path(cfg_dir) / "skills"
    skills_dir.mkdir()
    if task.get("mode") == "selection":
        for sk in task.get("candidate_skills") or []:
            src = pathlib.Path(os.path.expanduser(f"~/.claude/skills/{sk}"))
            if not src.exists():
                sys.exit(f"task lists candidate skill {sk!r} but {src} does not exist")
            shutil.copytree(src, skills_dir / sk)
    elif task.get("skill") and a.arm == "on":
        src = pathlib.Path(os.path.expanduser(f"~/.claude/skills/{task['skill']}"))
        if not src.exists():
            sys.exit(f"task names skill {task['skill']!r} but {src} does not exist")
        shutil.copytree(src, skills_dir / task["skill"])

    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", a.model.lower()).strip("-")
    ndjson = outdir / f"{task['task_id']}-{a.arm}-{slug}-{stamp}.ndjson"

    print(f"task     : {task['task_id']}")
    print(f"reps     : {a.reps}")
    print(f"target   : {TARGET_HOST}")
    print(f"model    : {a.model} (pinned via --model)")
    print(f"arm      : {a.arm}")
    print(f"skill    : {(task.get('skill') if a.arm == 'on' else None) or '<none>'}"
          + (f" (wire marker set)" if task.get('skill_marker') else ""))
    print(f"cfg dir  : {cfg_dir} "
          f"(skills={os.listdir(skills_dir) or 'empty'}, bundled skills disabled)")
    print(f"out      : {ndjson}\n")

    recs = []
    with RunLock(OUT / ".harness.lock"), Capture() as cap, \
            ndjson.open("w") as fh:
        print(f"capture  : {'adopted existing' if cap.adopted else 'started'} "
              f"-> {SSE_FILE}\n")
        for i in range(1, a.reps + 1):
            rec = run_rep(task, i, cfg_dir, model=a.model, arm=a.arm)
            recs.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            sel = ""
            if rec.get("mode") == "selection":
                sel = (f"fired={rec['skills_fired']} "
                       f"want={rec['expected_selection']} ")
            # API time beside wall time, because they answer different questions: wall
            # includes local tool execution and whatever else the machine was doing.
            api = rec.get("cli_duration_api_ms")
            api_s = f"api={api / 1000:.0f}s " if api else ""
            print(f"  rep {i}: passed={rec['passed']} "
                  f"{sel}"
                  f"pytest='{rec['pytest_tail'][:30]}' "
                  f"turns={rec['assistant_turns']} tools={rec['tool_calls']} "
                  f"llm_calls={rec['llm_calls']} pin_ok={rec['model_pin_honoured']} "
                  f"tok(in/out/cache)={rec['input_tokens']}/{rec['output_tokens']}/"
                  f"{rec['cache_read_tokens']} {api_s}wall={rec['wall_seconds']}s "
                  f"confounded={rec['confounded']}")
            if rec["confound_reasons"]:
                print(f"         reasons: {rec['confound_reasons']}")

    ok = [r for r in recs if not r["confounded"]]
    print(f"\n===== {task['task_id']} =====")
    print(f"  pass rate     : {sum(r['passed'] for r in recs)}/{len(recs)}")
    print(f"  confounded    : {sum(r['confounded'] for r in recs)}/{len(recs)}")

    def stats(key, rows):
        # Skip None rather than coercing: a timing the CLI did not report is a MISSING
        # measurement, and averaging it in as 0 would quietly halve a latency median.
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return "n/a"
        med = statistics.median(vals)
        mean = statistics.fmean(vals)
        cv = (statistics.pstdev(vals) / mean) if mean else 0.0
        return f"median={med:g} mean={mean:.1f} CV={cv:.2f}"

    # Medians/CV, not single values: this workload is not deterministic.
    for key in ("wall_seconds", "cli_duration_api_ms", "total_tokens", "input_tokens",
                "output_tokens", "cache_read_tokens", "llm_calls", "tool_calls"):
        print(f"  {key:18}: {stats(key, ok or recs)}")
    print(f"\n  ndjson: {ndjson}")


if __name__ == "__main__":
    main()
