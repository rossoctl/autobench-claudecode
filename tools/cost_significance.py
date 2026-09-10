#!/usr/bin/env python3
"""Which cost differences in the profile are actually established, and which are noise.

Every dollar figure published in results/EVALUATION.md is a MEDIAN over n repetitions, and
the per-repetition spread is wide (cost CV runs 0.05-0.42 depending on the cell). A median
gap is therefore not automatically a finding, and three of them stated in one sentence read
as three independent confirmations when they may be one confirmation and two coin flips.
This script exists so that claim is recomputed from the frozen manifest rather than typed
from memory -- the published dollars column was once stale for a day because it was typed
once and never recomputed after an exclusion changed the inputs.

TWO ESTIMATORS, and they are not interchangeable:

  method 1  per-column medians (uncached / cacheRead / cacheWrite / output), THEN price.
            This is what every published figure uses -- it is the median token profile of
            the cell, priced. It has no per-repetition spread, so it cannot be tested.
  method 2  price each repetition, THEN take statistics. Needed for SDs, effect sizes and
            permutation tests. Its point estimate differs from method 1's, because the
            median of a sum is not the sum of the medians.

Both are printed side by side so the difference is visible rather than surprising.

THE TEST is an exact two-sided permutation test on per-repetition scenario-B cost: pool the
two cells' repetitions, enumerate every way to split them back into groups of the original
sizes, and count how often |difference of means| is at least what was observed. Exact, so
no normality assumption -- which matters at n=5, where nothing is asymptotic.

READ THE FLOOR. With 5 vs 5 there are only C(10,5)=252 distinct splits, so the smallest
attainable two-sided p is 2/252 = 0.008. A p of 0.008 at n=5 means COMPLETE SEPARATION of
the two groups, not large-sample certainty; it is the design's floor, not a strong Bayes
factor. The floor is printed next to every p so it cannot be read out of context. It is
2/total only when the groups are the same size -- see perm_test for the unequal case.

`reps for 80% power` inverts the usual two-sample formula at alpha=0.05:
    n per group = 2 (z_0.975 + z_0.80)^2 sigma^2 / delta^2 ~= 15.6977 sigma^2 / delta^2
using the observed pooled SD and difference. It answers "if this effect is real at the size
observed, how many repetitions per cell would it take to see it 80% of the time" -- and it
is itself an estimate from the same small sample, so treat a value near the current n as
"borderline", not as a promise.
"""
import argparse
import itertools
import math
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pricing            # noqa: E402
import profile as prof    # noqa: E402

TIERS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "completion_tokens")
# The three cells every published cost table uses: both xlsx tasks in the ON arm, plus the
# no-skill canary as a reference point.
CELLS = [("xlsx-fin-colors", "on"), ("xlsx-fin-font-clean", "on"), ("cortex-pyfix-001", "on")]
# Z for alpha=0.05 two-sided and 80% power.
POWER_K = 2 * (1.959964 + 0.841621) ** 2      # 15.6977


def clean(rs):
    return [r for r in rs if not r["confounded"]]


def rep_cost(r, model, scenario):
    return pricing.cost(model, uncached=r["input_tokens"], cache_read=r["cache_read_tokens"],
                        cache_write=r["cache_write_tokens"], output=r["completion_tokens"],
                        scenario=scenario)


def method1(rs, model, scenario):
    """Per-column medians, then price -- the published estimator."""
    m = {k: statistics.median(r[k] for r in rs) for k in TIERS}
    return pricing.cost(model, uncached=m["input_tokens"], cache_read=m["cache_read_tokens"],
                        cache_write=m["cache_write_tokens"], output=m["completion_tokens"],
                        scenario=scenario)


def pass_rate(rs):
    return sum(1 for r in rs if r["passed"]) / len(rs)


def per_solved(value, rate):
    return value / rate if rate else float("nan")


def perm_test(a, b):
    """Exact two-sided permutation test on the difference of means.

    Enumerates all C(n_a+n_b, n_a) splits when that is tractable and says so; the counts
    here (up to a few hundred thousand) are.

    The third return value is the FLOOR -- the smallest p this design can produce -- and it
    depends on whether the groups are the same size. With n_a == n_b the observed split's
    complement reproduces the same |difference of means|, so at least 2 of the splits always
    hit and the floor is 2/total. With n_a != n_b there is no complement inside the
    enumeration, so a single split can be the only hit and the floor is 1/total. Getting this
    wrong makes an unequal comparison look as though it had beaten its own limit: at 5 v 3,
    2/56 = 0.036 but p = 0.018 is attainable and means complete separation.
    """
    obs = abs(statistics.fmean(a) - statistics.fmean(b))
    pool = list(a) + list(b)
    n, na = len(pool), len(a)
    total = math.comb(n, na)
    hits = 0
    idx = range(n)
    for combo in itertools.combinations(idx, na):
        s = set(combo)
        g1 = [pool[i] for i in idx if i in s]
        g2 = [pool[i] for i in idx if i not in s]
        if abs(statistics.fmean(g1) - statistics.fmean(g2)) >= obs - 1e-15:
            hits += 1
    return hits / total, total, (2 if na == len(b) else 1) / total


def cohen_d(a, b):
    na, nb = len(a), len(b)
    sa, sb = statistics.stdev(a), statistics.stdev(b)
    pooled = math.sqrt(((na - 1) * sa ** 2 + (nb - 1) * sb ** 2) / (na + nb - 2))
    return (statistics.fmean(a) - statistics.fmean(b)) / pooled if pooled else float("nan")


def reps_for_power(a, b):
    na, nb = len(a), len(b)
    sa, sb = statistics.stdev(a), statistics.stdev(b)
    pooled = math.sqrt(((na - 1) * sa ** 2 + (nb - 1) * sb ** 2) / (na + nb - 2))
    delta = abs(statistics.fmean(a) - statistics.fmean(b))
    if not delta:
        return float("inf")
    return math.ceil(POWER_K * pooled ** 2 / delta ** 2)


def compare(by, task, arm, m1, m2, scenario="B"):
    """One head-to-head, on per-repetition cost. Returns a dict or None."""
    a, b = clean(by.get((task, arm, m1), [])), clean(by.get((task, arm, m2), []))
    if len(a) < 2 or len(b) < 2:
        return None
    ca = [rep_cost(r, m1, scenario) for r in a]
    cb = [rep_cost(r, m2, scenario) for r in b]
    p, splits, floor = perm_test(ca, cb)
    mean_a, mean_b = statistics.fmean(ca), statistics.fmean(cb)
    # Two savings, deliberately both printed. `pub` is the gap between the PUBLISHED method-1
    # figures -- what a reader of EVALUATION.md can verify by dividing two numbers in the
    # table. `mean` is the gap the test actually operates on. They differ (e.g. 33.5% vs 26.0%
    # on font-clean) because a median token profile priced is not the mean of priced reps, and
    # quoting one beside the other's p-value without saying so is how tables go stale.
    r1a, r1b = method1(a, m1, scenario), method1(b, m2, scenario)
    return {"n": (len(ca), len(cb)), "mean": (mean_a, mean_b),
            "cv": (statistics.stdev(ca) / mean_a, statistics.stdev(cb) / mean_b),
            "saving": (mean_b - mean_a) / mean_b, "saving_pub": (r1b - r1a) / r1b,
            "d": cohen_d(ca, cb), "p": p, "splits": splits, "floor": floor,
            "need": reps_for_power(ca, cb)}


def verdict(r, n_have):
    if r["p"] <= 0.05:
        return "ESTABLISHED" if r["need"] <= n_have else "significant but underpowered"
    # Deliberately not "would settle it": that phrasing was published once, acted on, and turned
    # out to be false because the cell was not stationary. The figure is conditional, so say so.
    if r["need"] <= n_have * 2:
        return f"marginal -- ~{r['need']} reps/cell IF stationary (see note below)"
    return f"NO EVIDENCE either way -- would need ~{r['need']} reps/cell if stationary"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="unpinned glob instead of the frozen manifest (labels itself)")
    args = ap.parse_args()

    by, provenance, problems = prof.load(use_manifest=not args.all)
    print("=" * 96)
    print("COST SIGNIFICANCE".center(96))
    print("=" * 96)
    print(f"provenance : {provenance}")
    if problems:
        print("\n!! MEMBERSHIP PROBLEM -- these are NOT the published numbers:")
        for p in problems:
            print(f"   {p}")

    print("\n\nCOST PER SOLVED TASK -- both estimators, both scenarios ($)")
    print("  method 1 = per-column medians then price (PUBLISHED).  method 2 = price each rep, then median.")
    print(f"\n{'cell':34} {'model':11} {'n':>3} {'pass':>5} "
          f"{'B m1':>8} {'B m2':>8} {'A m1':>8} {'A m2':>8}")
    for task, arm in CELLS:
        for model in prof.MODELS:
            rs = clean(by.get((task, arm, model), []))
            if not rs:
                continue
            rate = pass_rate(rs)
            cells = []
            for sc in ("B", "A"):
                cells.append(per_solved(method1(rs, model, sc), rate))
                cells.append(per_solved(
                    statistics.median(rep_cost(r, model, sc) for r in rs), rate))
            b1, b2, a1, a2 = cells
            print(f"{task + '/' + arm:34} {prof.SHORT[model]:11} {len(rs):>3} {rate:>5.2f} "
                  f"{b1:>8.4f} {b2:>8.4f} {a1:>8.4f} {a2:>8.4f}")

    print("\n\nHEAD-TO-HEAD, exact permutation test on per-rep cost")
    pairs = [("claude-sonnet-5", "claude-sonnet-4-6", "is sonnet-5 cheaper than sonnet-4-6?"),
             ("claude-haiku-4-5-20251001", "claude-sonnet-4-6", "is haiku cheapest?"),
             ("claude-opus-5", "claude-sonnet-5", "is opus-5 dearest?")]
    for m1, m2, question in pairs:
        print(f"\n{question}   ({prof.SHORT[m1]} vs {prof.SHORT[m2]})")
        print(f"  {'cell':30} {'sc':>2} {'n':>7} {'gap m1':>7} {'gap mean':>8} {'d':>7} "
              f"{'p':>7} {'floor':>7} {'80%':>6}  verdict")
        for task, arm in CELLS:
            for sc in ("B", "A"):
                r = compare(by, task, arm, m1, m2, sc)
                if not r:
                    continue
                n_have = min(r["n"])
                print(f"  {task:30} {sc:>2} {str(r['n'][0]) + 'v' + str(r['n'][1]):>7} "
                      f"{r['saving_pub']:>6.1%} {r['saving']:>8.1%} {r['d']:>7.2f} "
                      f"{r['p']:>7.3f} {r['floor']:>7.3f} {r['need']:>6}  "
                      f"{verdict(r, n_have)}")

    print("\nfloor = smallest two-sided p this design can produce: 2/splits for equal group sizes,")
    print("1/splits when they differ. A p equal to the floor means the two groups separate")
    print("completely; it is not a large-sample result.")
    print("\n'80%' inverts the power formula on THIS sample's SD and assumes the cell is stationary.")
    print("For xlsx-fin-font-clean that assumption was tested on 2026-09-09 and FAILED -- the ~8")
    print("reps/cell it prescribes were bought and the gap did not settle, it changed sign. Run")
    print("tools/stability_probe.py before trusting any number in that column.")


if __name__ == "__main__":
    main()
