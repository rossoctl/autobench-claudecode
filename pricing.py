#!/usr/bin/env python3
"""Monetary cost for the profile cells, from the internal LiteLLM rate card.

WHERE THE RATES COME FROM (corrected 2026-09-23). This module used to state that no rate card
could be fetched -- the numbers are published on `/ui/?page=models`, which needs an interactive
web-authorization flow and renders client-side, so they were transcribed from screenshots. That
was true of the UI and wrong about the API: the gateway serves
`GET /public/litellm_model_cost_map` (on the host in `ANTHROPIC_BASE_URL`, which this public repo
does not carry) with **no credential at all**, carrying input, output,
cacheRead and cacheCreation rates for every model. `prices.json` is a pinned snapshot of the
rows we price; refresh it with `tools/fetch_prices.py`, which is also the drift check.

WHOSE GATEWAY THIS IS. Not ours and not Red Hat's: it is **IBM Research's ETE** deployment of
LiteLLM -- an enterprise organization's internal gateway that we are a tenant of. That matters
twice over. Its rate card is an enterprise arrangement rather than a public price, so this repo
does not publish the discount (below). And its model set, its margins and its availability can
all change without notice from our side, which is why the card is pinned and staleness-checked
rather than assumed constant.

WHAT THE MAP IS vs WHAT WE PAY. The map publishes the UPSTREAM provider's list rates. The
gateway bills **less than list** -- uniformly, across every benchmarked model and both
directions. The exact discount is deliberately **not stated anywhere in this repo**: it is a
term of somebody else's enterprise deployment, not a finding of ours, and no analysis here
needs it named. Nothing is lost by that, because the code never uses a stored factor: each
model's billed rates are the hand-transcribed card, and a cache tier is scaled by THAT model's
own billed/list ratio, computed at read time. Uniformity is therefore a property the code
CHECKS on every load, not a magic number it trusts.

  Be aware, though, that this repo carries both cards -- the billed one (PRICES, below, needed
  for every published figure to stay recomputable) and the listed one (prices.json) -- so the
  ratio is computable by anyone holding both. Not stating it is a decision about what this repo
  advertises, not a claim that it is unrecoverable.

Why the discount cannot simply be read: `/config/cost_margin_config` and
`/config/cost_discount_config` exist on this deployment, but a virtual key scoped to
`['llm_api_routes']` gets 403 on both. So even the uniformity is inferred from agreement between
two cards. PRICES stays hand-transcribed for exactly that reason -- it is the independent
witness, and tests/test_pricing.py fails if the two ever stop agreeing.

TWO SCENARIOS, because a cache tier's rate is not the same as how the gateway BILLS it:

  A  no-cache-discount   every prompt token billed at the Input rate. Upper bound.
  B  standard cache      cacheRead x0.10, cacheWrite x1.25, uncached x1.00.

Scenario B's multipliers used to be an assumption about the published Anthropic convention.
They are now a reading: the cost map states cacheRead and cacheCreation rates outright, and for
all four models they are exactly 0.10x and 1.25x the input rate. What remains unverified is
whether this gateway APPLIES them -- `/spend/calculate` and `/cost/estimate` would answer that
and are both 403 for our key. Cache reads are 81-97% of prompt tokens in every cell, so B lands
roughly 4-5x below A: treat A as the worst case and B as the likely case, and confirm against a
real invoice before quoting either as fact.

Caveat on names: the price pages are titled `aws/claude-*`, while the benchmark pinned the bare
aliases (`claude-sonnet-5`). Both route, and Cortex confirmed the bare alias is what was served,
but whether the bare alias bills at the `aws/` rate is assumed rather than shown. Note also that
`/v1/models` on 2026-09-23 lists `claude-sonnet-4-6` and `claude-haiku-4-5-20251001` bare but
offers `claude-sonnet-5` and `claude-opus-5` only under `aws/`, so the served set drifts.
"""
import datetime as dt
import json
import pathlib

SOURCE = ("hand-transcribed gateway rate card, cross-checked against the upstream cost map "
          "pinned in prices.json (IBM Research ETE LiteLLM)")
SOURCE_DATE = "2026-09-09"          # when PRICES was transcribed from the gateway UI
STALE_AFTER_DAYS = 90

# The gateway's own published rate, $ per 1M tokens, transcribed by hand from
# `/ui/?page=models` on SOURCE_DATE. KEPT DELIBERATELY: this is the only independent witness to
# what the gateway charges, and the whole derivation below is checked against it. Every
# published figure in results/ was computed from these numbers.
PRICES = {
    "claude-haiku-4-5-20251001": {"in": 0.76, "out": 3.80,
                                  "ui": "aws/claude-haiku-4-5",
                                  "backing": "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"},
    "claude-sonnet-4-6":         {"in": 2.28, "out": 11.40,
                                  "ui": "aws/claude-sonnet-4-6",
                                  "backing": "bedrock/us.anthropic.claude-sonnet-4-6"},
    "claude-sonnet-5":           {"in": 1.52, "out": 7.60,
                                  "ui": "aws/claude-sonnet-5",
                                  "backing": "bedrock/us.anthropic.claude-sonnet-5"},
    "claude-opus-5":             {"in": 3.80, "out": 19.00,
                                  "ui": "aws/claude-opus-5",
                                  "backing": "bedrock/us.anthropic.claude-opus-5"},
}

CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25
M = 1_000_000

SNAPSHOT = pathlib.Path(__file__).resolve().parent / "prices.json"


def discount_ratio(model, listed):
    """This model's billed/list ratio, from the two cards -- computed, never stored.

    Returns None unless the input and output ratios agree to four decimals. A model billed at
    one ratio on input and another on output is not a discount any more, and scaling its cache
    tiers by either number would be arithmetic with no meaning behind it.
    """
    li, lo = (listed.get("input_cost_per_token") or 0), (listed.get("output_cost_per_token") or 0)
    if not li or not lo:
        return None
    hand = PRICES[model]
    r_in = hand["in"] / (li * M)
    r_out = hand["out"] / (lo * M)
    # Rounded to 8 places only to strip float noise (3.00/2.28 lands on 0.7599999999999999).
    # Far finer than any rate card, and a 1e-9 wobble rounds away in the 6-place dollar figures.
    return round(r_in, 8) if round(r_in, 4) == round(r_out, 4) else None


def _load_snapshot():
    """Billed per-1M rates per tier, from prices.json. None when it is absent.

    Absence is not an error: the hand card is sufficient to price everything, and a checkout
    without the snapshot must still reproduce published figures.

    A model whose two ratios disagree is DROPPED rather than guessed at: `rates()` then falls
    back to the multiplier convention for it, which is the pre-snapshot behaviour and therefore
    still reproduces every published figure.
    """
    if not SNAPSHOT.exists():
        return None
    snap = json.loads(SNAPSHOT.read_text())
    rates, skipped = {}, []
    for m, e in snap["models"].items():
        if m not in PRICES:
            continue
        ratio = discount_ratio(m, e)
        if ratio is None:
            skipped.append(m)
            continue

        def billed(v, _r=ratio):
            return None if v is None else round(v * M * _r, 6)

        rates[m] = {
            "in": billed(e["input_cost_per_token"]),
            "out": billed(e["output_cost_per_token"]),
            "cache_read": billed(e.get("cache_read_input_token_cost")),
            "cache_write": billed(e.get("cache_creation_input_token_cost")),
        }
    return {"fetched": snap.get("fetched"), "source": snap.get("source"),
            "rates": rates, "skipped": skipped}


SNAP = _load_snapshot()


def rates(model):
    """Billed $/1M by tier. The snapshot supplies cache tiers; the hand card supplies in/out.

    in/out come from PRICES on purpose. They are what every published figure was computed
    from, and the snapshot is checked against them rather than trusted over them -- so a
    refresh that moved a rate shows up as a test failure, not as quietly different money.
    """
    p = PRICES[model]
    snap = (SNAP or {}).get("rates", {}).get(model, {})
    return {
        "in": p["in"],
        "out": p["out"],
        "cache_read": snap.get("cache_read", p["in"] * CACHE_READ_MULT),
        "cache_write": snap.get("cache_write", p["in"] * CACHE_WRITE_MULT),
    }


def cost(model, *, uncached, cache_read, cache_write, output, scenario="B"):
    """Dollars for one run's token counts."""
    r = rates(model)
    if scenario == "A":
        prompt_cost = (uncached + cache_read + cache_write) * r["in"] / M
    else:
        prompt_cost = (uncached * r["in"]
                       + cache_read * r["cache_read"]
                       + cache_write * r["cache_write"]) / M
    return prompt_cost + output * r["out"] / M


def table():
    return [(m, p["ui"], p["in"], p["out"], p["out"] / p["in"])
            for m, p in PRICES.items()]


def stale_days(today=None):
    """Days since the rate card was last confirmed against the gateway.

    Dates from the snapshot when there is one (a refresh IS a confirmation) and from
    SOURCE_DATE otherwise. A rate card nobody has looked at in a quarter is the quiet way a
    cost figure becomes fiction, and nothing else in the rig would notice.
    """
    when = (SNAP or {}).get("fetched") or SOURCE_DATE
    return ((today or dt.date.today()) - dt.date.fromisoformat(when)).days


def staleness_warning(today=None):
    d = stale_days(today)
    if d <= STALE_AFTER_DAYS:
        return None
    return (f"rate card last confirmed {d} days ago (limit {STALE_AFTER_DAYS}) -- run "
            f"tools/fetch_prices.py --check before quoting any dollar figure")


if __name__ == "__main__":
    print(f"{'benchmarked alias':28} {'gateway entry':24} {'in $/1M':>8} {'out $/1M':>9} {'out:in':>7}")
    for m, ui, i, o, r in table():
        print(f"{m:28} {ui:24} {i:>8.2f} {o:>9.2f} {r:>6.1f}x")
    print(f"\n  source : {SOURCE}")
    if SNAP:
        print(f"  snapshot: prices.json fetched {SNAP['fetched']} from the gateway at "
              f"$ANTHROPIC_BASE_URL{SNAP['source']}")
        print(f"  billing : the snapshot lists the UPSTREAM provider's rates; this gateway (IBM "
              f"Research ETE) bills\n"
              f"            BELOW them, by the same proportion for every model and both "
              f"directions.\n"
              f"            The proportion is not stated here -- it is a term of an enterprise "
              f"deployment,\n"
              f"            and nothing computed below needs it named. Cache tiers are scaled by "
              f"each\n"
              f"            model's own billed/list ratio, checked for agreement at load.")
        if SNAP.get("skipped"):
            print(f"  ⚠️  ratios disagree for {SNAP['skipped']} -- those fall back to the "
                  f"x{CACHE_READ_MULT}/x{CACHE_WRITE_MULT} convention")
        print(f"\n  {'model':28} {'cacheRead':>10} {'cacheWrite':>11}   (billed $/1M)")
        for m in sorted(SNAP["rates"]):
            r = rates(m)
            print(f"  {m:28} {r['cache_read']:>10.4f} {r['cache_write']:>11.4f}")
        print(f"\n  Cache tiers are READ FROM THE MAP, not assumed: they come to "
              f"x{CACHE_READ_MULT} and x{CACHE_WRITE_MULT} of input for all four models.")
    else:
        print(f"  dated  : {SOURCE_DATE} (hand-transcribed; prices.json absent, so scenario B "
              f"falls back to the x{CACHE_READ_MULT}/x{CACHE_WRITE_MULT} convention)")
    print(f"  confirmed {stale_days()} days ago")
    w = staleness_warning()
    if w:
        print(f"  ⚠️  {w}")
