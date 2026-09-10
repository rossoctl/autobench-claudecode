#!/usr/bin/env python3
"""Did the xlsx-fin-font-clean/ON cell reproduce ~23h later? Recomputes 7.3.2 of EVALUATION.md.

BACKGROUND. The 2026-09-08 grid put `xlsx-fin-font-clean`/ON at n=5 per model and made
`sonnet-5` look 33.5% cheaper than `sonnet-4-6` at p=0.056 -- marginal, and the report
predicted ~8 reps/cell would settle it. On 2026-09-09 we bought 3 more reps per sonnet to
do exactly that. They did not settle it; they falsified the premise that the cell is stable
enough to accumulate reps across sessions, so this script exists to make that falsification
reproducible instead of anecdotal.

WHAT IT COMPARES. Three readings of the same question, plus the control that makes the
result interpretable:

  reading 1  the 09-08 grid alone (5 v 5)     -- what is published
  reading 2  the 09-09 probe alone (3 v 3)    -- same task, arm, skill, harness, proxy, alias
  reading 3  both sessions pooled (8 v 8)     -- the "~8 reps" the report promised

  session test   for EACH model separately, 09-08 reps vs 09-09 reps. This is the load-bearing
                 comparison: `sonnet-4-6` is the control. If both models drifted, suspect the
                 rig. If only one did, the rig held and the drift is in that model's path.

READ THE FLOORS. A 3v3 permutation test enumerates C(6,3)=20 splits, and because the groups
are the same size the observed split's complement always ties it, so the smallest two-sided p
is 2/20 = 0.100 -- a 3v3 comparison CANNOT reach 0.05 no matter how cleanly the groups
separate. The per-model session test is 5v3, where there is no complement inside C(8,3)=56,
so its floor is 1/56 = 0.018. Both floors are hit below: "p=0.100" and "p=0.018" here mean
complete separation at the design's limit, not a measured probability, which is why the floor
is printed beside every p.

The probe files are DELIBERATELY EXCLUDED from results/profile-manifest.json (see the reason
recorded there), so this script reads them by name rather than through the manifest. Pooling
them into the grid would make one cell a two-session mixture while every other `sonnet-5`
cell stays pure 09-08, which is precisely the like-for-like property the cost comparisons in
7.3-7.6 rest on.
"""
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import profile as prof                                        # noqa: E402
from cost_significance import clean, method1, perm_test, rep_cost   # noqa: E402

TASK, ARM = "xlsx-fin-font-clean", "on"
S46, S5 = "claude-sonnet-4-6", "claude-sonnet-5"
# The two runs bought on 2026-09-09, ~23h after the grid. Named, not globbed: a glob would
# quietly absorb any future ad-hoc rep and this comparison is about a specific pair of runs.
PROBE = {
    S46: "xlsx-fin-font-clean-on-claude-sonnet-4-6-20260909212425.ndjson",
    S5: "xlsx-fin-font-clean-on-claude-sonnet-5-20260909212902.ndjson",
}
# Two independent sources per row: llm_calls comes off the wire (Cortex), tool_calls out of
# the transcript. If they move together, a wire-counting artefact is ruled out.
MEASURES = [("llm_calls", "LLM calls"), ("tool_calls", "tool calls"),
            ("total_tokens", "tokens"), ("wall_seconds", "wall s")]


def probe_rows(model):
    return clean(json.loads(ln) for ln in prof.rows_of(ROOT / "out" / "runs" / PROBE[model]))


def costs(rows, model, scenario="B"):
    return [rep_cost(r, model, scenario) for r in rows]


def gap(label, value):
    word = "cheaper" if value > 0 else "DEARER "
    return f"{label} {abs(value):>6.1%} {word}"


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
          f"p={p:.3f} (floor {1 if len(c5) != len(c46) else 2}/{splits}={floor:.3f})")


def session_test(model, grid, probe):
    print(f"\n  {prof.SHORT[model]}: 09-08 grid (n={len(grid)}) vs 09-09 probe (n={len(probe)})")
    for key, name in MEASURES:
        g = [r[key] for r in grid]
        q = [r[key] for r in probe]
        mg, mq = statistics.fmean(g), statistics.fmean(q)
        p, splits, floor = perm_test(q, g)
        ratio = mq / mg if mg else float("nan")
        print(f"    {name:11} 09-08 {mg:>10.1f}   09-09 {mq:>10.1f}   "
              f"x{ratio:>5.2f}   p={p:.3f} (floor 1/{splits}={floor:.3f})")
    cb = [rep_cost(r, model, "B") for r in grid], [rep_cost(r, model, "B") for r in probe]
    p, splits, floor = perm_test(cb[1], cb[0])
    ratio = statistics.fmean(cb[1]) / statistics.fmean(cb[0])
    print(f"    {'cost $ (B)':11} 09-08 {statistics.fmean(cb[0]):>10.4f}   "
          f"09-09 {statistics.fmean(cb[1]):>10.4f}   x{ratio:>5.2f}   "
          f"p={p:.3f} (floor 1/{splits}={floor:.3f})")


def deliverable(model, rows, when):
    """Did the extra spend buy anything? Same task, so the answer should be no."""
    ok = sum(1 for r in rows if r["passed"])
    print(f"    {prof.SHORT[model]:11} {when:8} {ok}/{len(rows)} passed, "
          f"{sum(1 for r in rows if r['confounded'])}/{len(rows)} confounded")


def main():
    by, provenance, problems = prof.load(use_manifest=True)
    print("=" * 100)
    print("CROSS-SESSION STABILITY PROBE -- xlsx-fin-font-clean / ON".center(100))
    print("=" * 100)
    print(f"grid provenance : {provenance}")
    if problems:
        print("!! MEMBERSHIP PROBLEM -- the grid half of this is not the published data:")
        for p in problems:
            print(f"   {p}")
    print(f"probe files     : {PROBE[S46]}\n                  {PROBE[S5]}")
    print("                  (excluded from the manifest on purpose -- read by name here)")

    g46, g5 = clean(by[(TASK, ARM, S46)]), clean(by[(TASK, ARM, S5)])
    p46, p5 = probe_rows(S46), probe_rows(S5)

    print("\n\nIS sonnet-5 CHEAPER THAN sonnet-4-6 HERE?  three readings of one question")
    reading("09-08 grid (published)", g46, g5)
    reading("09-09 probe", p46, p5)
    reading("pooled", g46 + p46, g5 + p5)
    print("\n  The sign flips between sessions and the pooled reading is a tie. Adding reps did")
    print("  not sharpen this cell; it revealed the cell is not stationary across sessions.")

    print("\n\nDID EACH MODEL REPRODUCE?  (sonnet-4-6 is the control -- same rig, same session pair)")
    session_test(S46, g46, p46)
    session_test(S5, g5, p5)

    print("\n\nDID THE EXTRA SPEND BUY A BETTER DELIVERABLE?")
    for model, grid, probe in ((S46, g46, p46), (S5, g5, p5)):
        deliverable(model, grid, "09-08")
        deliverable(model, probe, "09-09")

    print("\n\nSPREAD -- per-rep cost, scenario B. The 09-08 row is the sigma the power figure in")
    print("7.3.1 was computed from; the pooled row is what a second session revealed it to be.")
    for model, grid, probe in ((S46, g46, p46), (S5, g5, p5)):
        for label, rows in (("09-08 only", grid), ("pooled", grid + probe)):
            c = costs(rows, model)
            print(f"  {prof.SHORT[model]:11} {label:11} n={len(c):<3} mean ${statistics.fmean(c):.4f}  "
                  f"sd ${statistics.stdev(c):.4f}  CV {statistics.stdev(c)/statistics.fmean(c):.2f}  "
                  f"min ${min(c):.4f}  max ${max(c):.4f}")
        sd_g = statistics.stdev(costs(grid, model))
        sd_p = statistics.stdev(costs(grid + probe, model))
        # Required n scales with sigma^2, so an understated SD understates the reps needed by its
        # SQUARE. That is why "~8 reps/cell" was not merely a bit optimistic.
        print(f"  {'':11} {'-> sigma':11} understated x{sd_p / sd_g:.2f}  "
              f"=> reps needed understated x{(sd_p / sd_g) ** 2:.1f}")


if __name__ == "__main__":
    main()
