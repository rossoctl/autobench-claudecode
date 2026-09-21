#!/usr/bin/env python3
"""Run a set of tasks through one arm and print a compact matrix.

Used for (a) the skill-OFF pre-screen -- any task the agent passes WITHOUT the skill is
not measuring the skill and gets discarded -- and (b) the skill-ON arm for survivors.
"""
import argparse
import glob
import os
import json
import pathlib
import re
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("HARNESS_OUT", ROOT / "out"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["on", "off", "select"], required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--pattern", default="xlsx-*")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    # Passed straight through to the harness. The run LOCK stays at OUT/.harness.lock whatever
    # this is set to, so a different output directory isolates the ROWS without letting two
    # runs overlap -- which would make the time-window correlation attribute one run's
    # inference events to the other.
    ap.add_argument("--out", default=str(OUT / "runs"))
    ap.add_argument("--skill-variant", default=None, metavar="NAME",
                    help="pass through to the harness: apply the edit recipe "
                         "skills/<skill>-NAME/overlay.json (ON arm only)")
    a = ap.parse_args()
    out = pathlib.Path(a.out)

    tasks = sorted(p for p in (ROOT / "tasks").glob(a.pattern) if p.is_dir())
    print(f"arm={a.arm} reps={a.reps} model={a.model} "
          f"skill_variant={a.skill_variant or 'as-installed'} "
          f"tasks={[t.name for t in tasks]}\n")

    rows = []
    for t in tasks:
        r = subprocess.run(
            [sys.executable, "-u", str(ROOT / "harness.py"), str(t),
             "--reps", str(a.reps), "--arm", a.arm, "--model", a.model,
             "--out", str(out)]
            + (["--skill-variant", a.skill_variant] if a.skill_variant else []),
            capture_output=True, text=True, timeout=7200)
        slug = re.sub(r"[^a-z0-9]+", "-", a.model.lower()).strip("-")
        latest = sorted(glob.glob(str(out / f"{t.name}-{a.arm}-{slug}-*.ndjson")))
        if not latest:
            print(f"  {t.name:28} NO OUTPUT (exit={r.returncode})")
            print("   " + r.stdout.strip()[-400:])
            continue
        recs = [json.loads(l) for l in pathlib.Path(latest[-1]).read_text().splitlines()]
        npass = sum(x["passed"] for x in recs)
        conf = sum(x["confounded"] for x in recs)
        wires = {x.get("skill_on_wire") for x in recs}
        toks = statistics.median(x["total_tokens"] for x in recs)
        wall = statistics.median(x["wall_seconds"] for x in recs)
        reasons = sorted({r2 for x in recs for r2 in x["confound_reasons"]})
        rows.append({"task": t.name, "pass": npass, "n": len(recs), "conf": conf,
                     "wire": wires, "tokens": toks, "wall": wall,
                     "reasons": reasons, "file": latest[-1],
                     "fails": [x["pytest_tail"] for x in recs if not x["passed"]]})
        if a.arm == "select":
            fired = [x.get("skills_fired") for x in recs]
            want = recs[0].get("expected_selection")
            print(f"  {t.name:24} correct={npass}/{len(recs)} want={want or '<none>'} "
                  f"fired={fired} confounded={conf} tok_med={toks} wall_med={wall}s")
        else:
            print(f"  {t.name:28} pass={npass}/{len(recs)} confounded={conf} "
                  f"skill_on_wire={wires} tok_med={toks} wall_med={wall}s")
        if reasons:
            print(f"      confounds: {reasons}")
        for f in rows[-1]["fails"][:1]:
            print(f"      e.g. fail: {f[:100]}")

    print(f"\n===== ARM {a.arm.upper()} SUMMARY =====")
    for r in rows:
        verdict = ""
        if a.arm == "select":
            verdict = ("  <== correct" if r["pass"] == r["n"]
                       else "  <== WRONG every time" if r["pass"] == 0
                       else "  <== inconsistent")
        elif a.arm == "off":
            verdict = ("  <== DISCARD (passes without the skill)" if r["pass"] == r["n"]
                       else "  <== keep" if r["pass"] == 0
                       else "  <== marginal (partial pass unaided)")
        print(f"  {r['task']:28} {r['pass']}/{r['n']}{verdict}")
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", a.model.lower()).strip("-")
    # Beside the rows it summarizes, not in OUT -- otherwise two output directories share one
    # summary file and the second sweep silently overwrites the first one's verdicts.
    (out / f"sweep-{a.arm}-{slug}.json").write_text(
        json.dumps([{k: (sorted(v) if isinstance(v, set) else v) for k, v in r.items()}
                    for r in rows], indent=2))


if __name__ == "__main__":
    main()
