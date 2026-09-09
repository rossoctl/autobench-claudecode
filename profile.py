#!/usr/bin/env python3
"""Cost profile: the same xlsx work across several models.

Prices identical work across models. NOTE the original premise -- "compliance tasks cannot
rank correctness because pass rate is saturated" -- was FALSIFIED by the first four-model
run: haiku-4-5 fails the ON arm 3 of 5 times and opus-5 passes the OFF arm 1 of 5, so there
is real resolution outside the sonnet band. Pass rate is reported as a measurement.

Two modes so the analysis is never coupled to a 2-hour run:
    profile.py --run       execute the grid (serialised by the harness run lock)
    profile.py --report    recompile from out/runs, no invocations

Reported per cell and then across models:
  * tok/LLMcall        tokens per LLM CALL (one /v1/chat/completions) -- a MODEL constant.
                       NOTE one task = one `claude -p` run and makes SEVERAL LLM calls.
  * llm_calls          LLM calls per task -- TASK-dependent, not a model property
  * cache tiers        uncached / cacheRead / cacheWrite, and cache-read share
  * cost per solved task = median tokens / pass rate (undefined at pass rate 0)
  * skill-overhead multiple, from the OFF arm of each xlsx task

Deliberately NOT reported: any dollar figure. Cortex never populates costMicros
(priced:false always, in-tree TODO), so a money number would come from a price list we
invented. Tokens are reported by tier; apply your own pricing.
"""
import argparse
import glob
import json
import pathlib
import statistics
import subprocess
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"

MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-5",
]
# (task, arm). The two xlsx tasks in both arms; cortex-pyfix as a NO-SKILL cost reference
# so "what does a task cost with no skill at all" has an answer on the same models.
CELLS = [
    ("xlsx-fin-colors", "on"),
    ("xlsx-fin-colors", "off"),
    ("xlsx-fin-font-clean", "on"),
    ("xlsx-fin-font-clean", "off"),
    ("cortex-pyfix-001", "on"),      # no skill: meta.json has none
]
SHORT = {"claude-haiku-4-5-20251001": "haiku-4-5", "claude-sonnet-4-6": "sonnet-4-6",
         "claude-sonnet-5": "sonnet-5", "claude-opus-5": "opus-5"}


def run(reps):
    total = len(MODELS) * len(CELLS)
    i = 0
    for model in MODELS:
        for task, arm in CELLS:
            i += 1
            print(f"\n[{i}/{total}] {task} arm={arm} model={model}", flush=True)
            r = subprocess.run(
                [sys.executable, "-u", str(ROOT / "harness.py"), str(ROOT / "tasks" / task),
                 "--reps", str(reps), "--arm", arm, "--model", model],
                capture_output=True, text=True, timeout=14400)
            for line in r.stdout.splitlines():
                if line.strip().startswith("rep ") or "pass rate" in line:
                    print("   " + line.strip(), flush=True)
            if r.returncode != 0:
                print(f"   !! exit={r.returncode}: {r.stdout.strip()[-300:]}", flush=True)


# ------------------------------------------------------------------ reporting

def load():
    """Every rep, keyed (task, arm, model). Keyed on the record, not the filename."""
    by = defaultdict(list)
    for d in ("out/runs", "out/runs-archive"):
        for f in sorted(glob.glob(str(ROOT / d / "*.ndjson"))):
            for line in pathlib.Path(f).read_text().splitlines():
                r = json.loads(line)
                by[(r["task_id"], r.get("arm", "on"),
                    r.get("model_requested") or "<unpinned>")].append(r)
    return by


def integrity(rs):
    """The two identities that must hold; a cell failing them is quarantined."""
    bad = []
    for r in rs:
        p, i, cr, cw = (r["prompt_tokens"], r["input_tokens"],
                        r["cache_read_tokens"], r["cache_write_tokens"])
        if p and i + cr + cw != p:
            bad.append(("prompt!=in+cr+cw", r["rep"]))
        if r["total_tokens"] and r["total_tokens"] != p + r["completion_tokens"]:
            bad.append(("total!=prompt+completion", r["rep"]))
    return bad


def med(rs, k):
    return statistics.median(r[k] for r in rs)


def cv(rs, k):
    v = [r[k] for r in rs]
    m = statistics.fmean(v)
    return (statistics.pstdev(v) / m) if m else 0.0


def report(reps):
    by = load()
    print("=" * 100)
    print("xlsx COST PROFILE".center(100))
    print("=" * 100)
    print("\nI predicted pass rate would be saturated -- OFF pinned at 0 by the pre-screen,")
    print("ON at 100 because the skill states the answer -- and therefore useless for")
    print("ranking models. THE DATA REFUTES THAT. Saturation only held for the two")
    print("mid-tier models it was observed on. Resolution exists at BOTH ends:")
    print("  * haiku-4-5 ON xlsx-fin-font-clean = 0.40 -- it does not reliably comply")
    print("    even when the skill states the rule.")
    print("  * opus-5 OFF xlsx-fin-colors = 0.20 -- it sometimes knows the convention")
    print("    with no skill at all.")
    print("So these tasks DO rank models, below and above the sonnet band. Read pass rate")
    print("as a real measurement, not as a formality.\n")

    cells = {}
    for task, arm in CELLS:
        for m in MODELS:
            rs = by.get((task, arm, m), [])
            rs = [r for r in rs if r.get("rep", 0) <= 10**9]
            clean = [r for r in rs if not r["confounded"]]
            if not clean:
                continue
            bad = integrity(clean)
            if bad:
                print(f"  QUARANTINED {task}/{arm}/{m}: {bad}")
                continue
            calls = med(clean, "llm_calls")
            cells[(task, arm, m)] = dict(
                n=len(clean), dropped=len(rs) - len(clean),
                pas=sum(r["passed"] for r in clean) / len(clean),
                tok=med(clean, "total_tokens"), tok_cv=cv(clean, "total_tokens"),
                calls=calls, tpc=med(clean, "total_tokens") / calls if calls else float("nan"),
                inp=med(clean, "input_tokens"), cr=med(clean, "cache_read_tokens"),
                cwr=med(clean, "cache_write_tokens"), out=med(clean, "completion_tokens"),
                wall=med(clean, "wall_seconds"), wall_cv=cv(clean, "wall_seconds"),
                prompt=med(clean, "prompt_tokens"))

    # ---- per-cell table
    print(f"{'task':21} {'arm':4} {'model':11} {'n':>2} {'pass':>5} {'tokens':>9} {'CV':>5} "
          f"{'calls':>5} {'tok/LLMc':>8} {'uncached':>8} {'cacheR':>9} {'cacheW':>7} {'out':>6} {'wall':>6}")
    for task, arm in CELLS:
        for m in MODELS:
            c = cells.get((task, arm, m))
            if not c:
                print(f"{task:21} {arm:4} {SHORT[m]:11} {'--':>2}  (no clean reps)")
                continue
            print(f"{task:21} {arm:4} {SHORT[m]:11} {c['n']:>2} {c['pas']:>5.2f} "
                  f"{c['tok']:>9,.0f} {c['tok_cv']:>5.2f} {c['calls']:>5.0f} {c['tpc']:>8,.0f} "
                  f"{c['inp']:>8,.0f} {c['cr']:>9,.0f} {c['cwr']:>7,.0f} {c['out']:>6,.0f} "
                  f"{c['wall']:>5.0f}s")
        print()

    base = "claude-sonnet-4-6"

    # ---- Q: is tokens-per-LLM-call a MODEL constant or a task interaction?
    print("-" * 100)
    print("Is tokens per LLM CALL a MODEL property? (ratio vs sonnet-4-6, per cell)")
    print("One task = one `claude -p` run = SEVERAL LLM calls, so this is per-call, not per-task.\n")
    print(f"{'model':11} " + " ".join(f"{t[:15]+'/'+a:20}" for t, a in CELLS) + " spread")
    for m in MODELS:
        ratios, cellsr = [], []
        for task, arm in CELLS:
            a, b = cells.get((task, arm, base)), cells.get((task, arm, m))
            if a and b:
                r = b["tpc"] / a["tpc"]
                ratios.append(r); cellsr.append(f"{r:>20.2f}")
            else:
                cellsr.append(f"{'-':>20}")
        spread = (max(ratios) - min(ratios)) if len(ratios) > 1 else float("nan")
        verdict = ""
        if len(ratios) > 1:
            verdict = "  <= CONSTANT" if spread <= 0.15 else "  <= varies by task"
        print(f"{SHORT[m]:11} " + " ".join(cellsr) + f" {spread:.2f}{verdict}")

    # ---- Q: does the model change behaviour (call count) for identical work?
    print("\n" + "-" * 100)
    print("Behaviour: LLM calls PER TASK, ratio vs sonnet-4-6 (task-dependent if it varies)\n")
    for m in MODELS:
        parts = []
        for task, arm in CELLS:
            a, b = cells.get((task, arm, base)), cells.get((task, arm, m))
            parts.append(f"{task[:14]}/{arm}={b['calls']/a['calls']:.2f}x"
                         if (a and b and a["calls"]) else f"{task[:14]}/{arm}=-")
        print(f"  {SHORT[m]:11} " + "  ".join(parts))

    # ---- Q: cost per solved task
    print("\n" + "-" * 100)
    print("Cost per SOLVED task = median tokens / pass rate (undefined at pass rate 0)\n")
    print(f"{'task':21} {'arm':4} " + " ".join(f"{SHORT[m]:>16}" for m in MODELS))
    for task, arm in CELLS:
        row = []
        for m in MODELS:
            c = cells.get((task, arm, m))
            if not c:
                row.append(f"{'-':>16}")
            elif c["pas"] == 0:
                row.append(f"{'undefined(0%)':>16}")
            else:
                row.append(f"{c['tok']/c['pas']:>16,.0f}")
        print(f"{task:21} {arm:4} " + " ".join(row))

    # ---- Q: does the skill cost the same multiple on every model?
    print("\n" + "-" * 100)
    print("Skill-overhead multiple (xlsx ON / OFF tokens), per model\n")
    for task in ("xlsx-fin-colors", "xlsx-fin-font-clean"):
        parts = []
        for m in MODELS:
            on, off = cells.get((task, "on", m)), cells.get((task, "off", m))
            parts.append(f"{SHORT[m]}={on['tok']/off['tok']:.2f}x" if (on and off)
                         else f"{SHORT[m]}=-")
        print(f"  {task:21} " + "  ".join(parts))

    # ---- cache tiers
    print("\n" + "-" * 100)
    print("Cache-read share of prompt tokens (how much context is re-read)\n")
    for m in MODELS:
        parts = []
        for task, arm in CELLS:
            c = cells.get((task, arm, m))
            parts.append(f"{task[:14]}/{arm}={c['cr']/c['prompt']:.0%}"
                         if (c and c["prompt"]) else f"{task[:14]}/{arm}=-")
        print(f"  {SHORT[m]:11} " + "  ".join(parts))

    print("\n" + "=" * 100)
    print(f"n={reps} per cell. CV on a {reps}-sample median is indicative, not tight.")
    print("No dollar figures: Cortex leaves costMicros unpopulated, so pricing would be")
    print("invented. Tokens are split by tier above -- apply your own rates.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    if a.run:
        run(a.reps)
    if a.report or not a.run:
        report(a.reps)
