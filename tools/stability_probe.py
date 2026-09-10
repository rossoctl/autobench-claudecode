#!/usr/bin/env python3
"""Do the profile's cells reproduce across sessions? Recomputes 7.3.2 of EVALUATION.md.

BACKGROUND. The 2026-09-08 grid put `xlsx-fin-font-clean`/ON at n=5 per model and made
`sonnet-5` look 33.5% cheaper than `sonnet-4-6` at p=0.056 -- marginal, and the report
predicted ~8 reps/cell would settle it. On 2026-09-09 we bought 3 more reps per sonnet to
do exactly that. They did not settle it; they falsified the premise that the cell is stable
enough to accumulate reps across sessions, so this script exists to make that falsification
reproducible instead of anecdotal.

That left two explanations we could not separate: (a) a gateway-side change in what the
`claude-sonnet-5` alias resolves to, or (b) a fat tail in that one cell which n=5 missed.
They predict different things about OTHER cells, so a second probe on `cortex-pyfix-001`/ON
was run the same evening -- the cheapest cell in the grid, and the only one whose cost
finding is statistically established. Hence one script, several cells: pass --task to pick.

WHAT IT COMPARES, per cell. Three readings of the same question, plus the control that makes
the result interpretable:

  reading 1  the 09-08 grid alone (5 v 5)     -- what is published
  reading 2  the 09-09 probe alone (3 v 3)    -- same task, arm, skill, harness, proxy, alias
  reading 3  both sessions pooled (8 v 8)     -- the "~8 reps" the report promised

  session test   for EACH model separately, 09-08 reps vs 09-09 reps. This is the load-bearing
                 comparison: `sonnet-4-6` is the control. If both models drifted, suspect the
                 rig. If only one did, the rig held and the drift is in that model's path.

WORKLOAD vs DIAGNOSTIC, and why the verdict only reads the first group. An earlier version of
this script tested every measure alike and concluded from pyfix that BOTH models had drifted --
which was wrong, and wrong in an instructive way. Pyfix's LLM calls, tool calls and tokens
reproduced to within 0.1%, while mean cost moved x1.28-1.29 for both models. That cost move was
one repetition: the first rep of each 09-09 run found a cold cache and moved ~29k prompt tokens
from cacheRead (0.10x) to cacheWrite (1.25x) at an unchanged total, which at sonnet-5's input
rate accounts for $0.0509 of a $0.0509 gap -- exactly, to the cent. Cost and wall time are
therefore reported but not verdict-bearing: cost follows the tier split, which follows run
ORDER, and wall time follows whatever else the machine was doing. Only volume measures speak to
what the model did. The cold-rep check below names such reps instead of letting them inflate a
mean, and the cost row is re-run with them dropped so the reader can watch the gap dissolve.

READ THE FLOORS. A 3v3 permutation test enumerates C(6,3)=20 splits, and because the groups
are the same size the observed split's complement always ties it, so the smallest two-sided p
is 2/20 = 0.100 -- a 3v3 comparison CANNOT reach 0.05 no matter how cleanly the groups
separate. The per-model session test is 5v3, where there is no complement inside C(8,3)=56,
so its floor is 1/56 = 0.018. Both floors are hit on font-clean: "p=0.100" and "p=0.018"
there mean complete separation at the design's limit, not a measured probability, which is why
the floor is printed beside every p.

The probe files are DELIBERATELY EXCLUDED from results/profile-manifest.json (see the reasons
recorded there), so this script reads them by name rather than through the manifest. Pooling
them into the grid would make those cells two-session mixtures while every other cell stays
pure 09-08, which is precisely the like-for-like property the cost comparisons in 7.3-7.6
rest on.
"""
import argparse
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import profile as prof                                              # noqa: E402
from cost_significance import clean, method1, perm_test, rep_cost    # noqa: E402

ARM = "on"
S46, S5 = "claude-sonnet-4-6", "claude-sonnet-5"
# Runs bought on 2026-09-09, ~23h after the grid for font-clean and ~25h for pyfix. Named, not
# globbed: a glob would quietly absorb any future ad-hoc rep, and each comparison is about a
# specific pair of runs. Add a cell here only alongside its manifest exclusion.
PROBES = {
    "xlsx-fin-font-clean": {
        S46: "xlsx-fin-font-clean-on-claude-sonnet-4-6-20260909212425.ndjson",
        S5: "xlsx-fin-font-clean-on-claude-sonnet-5-20260909212902.ndjson",
    },
    "cortex-pyfix-001": {
        S46: "cortex-pyfix-001-on-claude-sonnet-4-6-20260909221514.ndjson",
        S5: "cortex-pyfix-001-on-claude-sonnet-5-20260909221714.ndjson",
    },
}
# WORKLOAD -- how much work the model chose to do. Two independent sources: llm_calls comes off
# the wire (Cortex), tool_calls out of the transcript. If they move together, a wire-counting
# artefact is ruled out. These decide the verdict.
WORKLOAD = [("llm_calls", "LLM calls"), ("tool_calls", "tool calls"), ("total_tokens", "tokens")]
# DIAGNOSTIC -- real, worth seeing, but not evidence about the model. wall_seconds tracks machine
# load; cost tracks the cache tier split, which tracks run order. See the module docstring.
DIAGNOSTIC = [("wall_seconds", "wall s")]
# A model is called reproduced when no WORKLOAD measure moves more than this and none clears 0.05.
REPRO_TOL = 0.10
# A rep is called cold when its cacheWrite share of prompt tokens exceeds this multiple of the
# 09-08 median share. 2x is far above the observed within-session scatter (which is a few percent)
# and far below the observed cold-start signature (3.5x), so the threshold is not doing fine work.
COLD_MULT = 2.0


def probe_rows(task, model):
    path = ROOT / "out" / "runs" / PROBES[task][model]
    return clean(json.loads(ln) for ln in prof.rows_of(path))


def costs(rows, model, scenario="B"):
    return [rep_cost(r, model, scenario) for r in rows]


def gap(label, value):
    word = "cheaper" if value > 0 else "DEARER "
    return f"{label} {abs(value):>6.1%} {word}"


def fmt_floor(splits, floor, equal):
    """Show the floor as a fraction as well as a decimal -- at 8v8 it rounds to 0.000, which
    reads as "no floor" when it in fact means the design can no longer be the binding constraint."""
    return f"floor {1 if not equal else 2}/{splits}={floor:.4f}".rstrip("0").rstrip(".")


def reading(label, a46, a5):
    """One head-to-head on scenario-B cost, sonnet-5 vs sonnet-4-6.

    Two gaps, same convention as 7.3.1: `m1` is between the published per-column-median
    figures, `mean` is what the permutation test actually operates on. They differ because a
    median token profile priced is not the mean of priced reps.
    """
    c46, c5 = costs(a46, S46), costs(a5, S5)
    m46, m5 = statistics.fmean(c46), statistics.fmean(c5)
    p, splits, floor = perm_test(c5, c46)
    r46, r5 = method1(a46, S46, "B"), method1(a5, S5, "B")
    print(f"  {label:24} {len(c5)}v{len(c46)}  s4-6 ${m46:.4f}  s5 ${m5:.4f}   "
          f"{gap('m1', (r46 - r5) / r46)}  {gap('mean', (m46 - m5) / m46)}  "
          f"p={p:.3f} ({fmt_floor(splits, floor, len(c5) == len(c46))})")


def cw_share(r):
    """cacheWrite as a fraction of prompt tokens. Cheap tokens re-billed at 12.5x the cache-read
    rate, so this one ratio moves cost even when the token TOTAL does not budge."""
    prompt = r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
    return r["cache_write_tokens"] / prompt if prompt else 0.0


def cold_reps(grid, probe):
    """Probe reps whose cache was cold relative to the grid's steady state."""
    base = statistics.median(cw_share(r) for r in grid)
    return [r for r in probe if cw_share(r) > COLD_MULT * base], base


def session_test(model, grid, probe):
    """Per-model 09-08 vs 09-09. Returns True if every WORKLOAD measure reproduced."""
    print(f"\n  {prof.SHORT[model]}: 09-08 grid (n={len(grid)}) vs 09-09 probe (n={len(probe)})")
    reproduced = True

    def row(name, g, q, fmt="10.1f"):
        mg, mq = statistics.fmean(g), statistics.fmean(q)
        p, splits, floor = perm_test(q, g)
        ratio = mq / mg if mg else float("nan")
        print(f"    {name:14} 09-08 {mg:>{fmt}}   09-09 {mq:>{fmt}}   "
              f"x{ratio:>5.2f}   p={p:.3f} ({fmt_floor(splits, floor, len(g) == len(q))})")
        return abs(ratio - 1) <= REPRO_TOL and p > 0.05

    print("    -- workload (decides the verdict) --")
    for k, name in WORKLOAD:
        reproduced &= row(name, [r[k] for r in grid], [r[k] for r in probe])

    print("    -- diagnostic (reported, not evidence about the model) --")
    for k, name in DIAGNOSTIC:
        row(name, [r[k] for r in grid], [r[k] for r in probe])
    row("cost $ (B)", costs(grid, model), costs(probe, model), "10.4f")

    cold, base = cold_reps(grid, probe)
    print(f"    cacheWrite share of prompt: 09-08 median {base:.1%}, probe reps "
          + ", ".join(f"#{r['rep']} {cw_share(r):.1%}" for r in probe))
    if cold:
        warm = [r for r in probe if r not in cold]
        tag = ", ".join(f"#{r['rep']}" for r in cold)
        print(f"    -> COLD CACHE in probe rep(s) {tag}: same tokens, re-tiered to cacheWrite.")
        if len(warm) >= 1:
            row("cost, warm only", costs(grid, model), costs(warm, model), "10.4f")
    return reproduced


def deliverable(model, rows, when):
    """Did the extra spend buy anything? Same task, so the answer should be no."""
    ok = sum(1 for r in rows if r["passed"])
    print(f"    {prof.SHORT[model]:11} {when:8} {ok}/{len(rows)} passed, "
          f"{sum(1 for r in rows if r['confounded'])}/{len(rows)} confounded")


def spread(model, grid, probe):
    cold, _ = cold_reps(grid, probe)
    pools = [("09-08 only", grid), ("pooled", grid + probe)]
    if cold:
        pools.append(("pooled warm", grid + [r for r in probe if r not in cold]))
    for label, rows in pools:
        c = costs(rows, model)
        print(f"  {prof.SHORT[model]:11} {label:11} n={len(c):<3} mean ${statistics.fmean(c):.4f}  "
              f"sd ${statistics.stdev(c):.4f}  CV {statistics.stdev(c)/statistics.fmean(c):.2f}  "
              f"min ${min(c):.4f}  max ${max(c):.4f}")
    sd_g = statistics.stdev(costs(grid, model))
    for label, rows in pools[1:]:
        sd_p = statistics.stdev(costs(rows, model))
        # Required n scales with sigma^2, so an understated SD understates the reps needed by its
        # SQUARE. That is why "~8 reps/cell" was not merely a bit optimistic. Where a cold rep is
        # present, the `pooled warm` line is the honest one: a first-rep cache miss is a property
        # of run order, not of the cell, so budgeting reps against it would be budgeting against
        # an artefact we could instead just discard.
        print(f"  {'':11} -> sigma vs {label:11} understated x{sd_p / sd_g:.2f}  "
              f"=> reps needed understated x{(sd_p / sd_g) ** 2:.1f}")


def run_cell(task, by):
    print("\n" + "=" * 100)
    print(f"{task} / {ARM.upper()}".center(100))
    print("=" * 100)
    print(f"probe files : {PROBES[task][S46]}\n              {PROBES[task][S5]}")
    print("              (excluded from the manifest on purpose -- read by name here)")

    g46, g5 = clean(by[(task, ARM, S46)]), clean(by[(task, ARM, S5)])
    p46, p5 = probe_rows(task, S46), probe_rows(task, S5)

    print("\nIS sonnet-5 CHEAPER THAN sonnet-4-6 HERE?  three readings of one question")
    reading("09-08 grid (published)", g46, g5)
    reading("09-09 probe", p46, p5)
    reading("pooled", g46 + p46, g5 + p5)

    print("\n\nDID EACH MODEL REPRODUCE?  (sonnet-4-6 is the control -- same rig, same session pair)")
    ok46 = session_test(S46, g46, p46)
    ok5 = session_test(S5, g5, p5)

    print("\n\nDID THE EXTRA SPEND BUY A BETTER DELIVERABLE?")
    for model, grid, probe in ((S46, g46, p46), (S5, g5, p5)):
        deliverable(model, grid, "09-08")
        deliverable(model, probe, "09-09")

    print("\n\nSPREAD -- per-rep cost, scenario B. The 09-08 row is the sigma a power figure for")
    print("this cell would be computed from; pooled is what a second session revealed it to be.")
    spread(S46, g46, p46)
    spread(S5, g5, p5)
    return {"task": task, S46: ok46, S5: ok5}


def verdict(results):
    """The cross-cell reading. One cell cannot separate an alias change from a fat tail; two can."""
    print("\n" + "=" * 100)
    print("ACROSS CELLS -- did the WORKLOAD reproduce?".center(100))
    print("=" * 100)
    print(f"  {'cell':26} {'sonnet-4-6 (control)':22} sonnet-5")
    for r in results:
        w = lambda ok: "reproduced" if ok else "DID NOT reproduce"      # noqa: E731
        print(f"  {r['task']:26} {w(r[S46]):22} {w(r[S5])}")
    if len(results) < 2:
        print("\n  Only one cell probed -- cannot separate a gateway-side alias change from a")
        print("  cell-specific fat tail. Probe a second cell to do that.")
        return
    drifted = [r["task"] for r in results if not r[S5]]
    if len(drifted) == len(results):
        print("\n  sonnet-5's workload moved in EVERY probed cell => consistent with a gateway-side")
        print("  change in what the alias resolves to. Treat every sonnet-5 figure as session-bound.")
    elif drifted:
        held = [r["task"] for r in results if r[S5]]
        print(f"\n  sonnet-5's workload moved in {', '.join(drifted)} and held in "
              f"{', '.join(held)}")
        print("  => the drift is CELL-SPECIFIC. A gateway-wide substitution would have moved every")
        print("  cell and it did not: the cell that held reproduced to within 0.1% on every volume")
        print("  measure. So the sonnet-5 alias was serving the same thing in both sessions, and")
        print("  what varies is that one task's sensitivity to it -- a fat tail n=5 did not sample.")
        print("  This does NOT license extrapolating stability to the 18 unprobed cells; it says")
        print("  the failure mode is per-cell, so each cell needs its own probe to be trusted.")
    else:
        print("\n  Both models reproduced everywhere probed -- nothing to explain in these cells.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", action="append", choices=sorted(PROBES),
                    help="cell to check (repeatable; default all probed cells)")
    args = ap.parse_args()
    tasks = args.task or list(PROBES)

    by, provenance, problems = prof.load(use_manifest=True)
    print("CROSS-SESSION STABILITY PROBE".center(100))
    print(f"grid provenance : {provenance}")
    if problems:
        print("!! MEMBERSHIP PROBLEM -- the grid half of this is not the published data:")
        for p in problems:
            print(f"   {p}")

    verdict([run_cell(t, by) for t in tasks])


if __name__ == "__main__":
    main()
