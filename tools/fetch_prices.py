#!/usr/bin/env python3
"""Refresh prices.json from the gateway's own cost map -- the rate card, pinned.

WHY THIS EXISTS NOW. pricing.py used to say a rate card could not be fetched: the rates are
published on `/ui/?page=models`, which needs an interactive web-authorization flow and renders
client-side, so the numbers were transcribed from screenshots. That conclusion was drawn from
the UI alone and was wrong about the API. This gateway serves
`GET /public/litellm_model_cost_map` -- **no credential at all** -- carrying every model's
input, output, cacheRead and cacheCreation rates.

WHOSE GATEWAY, AND WHY THE DISCOUNT IS NOT IN HERE. The deployment is **IBM Research's ETE**
LiteLLM -- an enterprise organization's internal gateway we are a tenant of, not a Red Hat
service. The map states the UPSTREAM provider's list rates; the gateway bills BELOW them, by the
same proportion for every benchmarked model and both directions. That proportion is a term of
somebody else's enterprise arrangement, so **this tool never writes it into the snapshot** and no
constant in the repo holds it. It is still CHECKED on every run -- the ratios must agree with
each other and with the hand-transcribed card in pricing.PRICES, or the snapshot is refused --
because a silently changed arrangement is exactly the failure this file exists to catch. (The
gateway would state it at `/config/cost_margin_config`; that route is 403 for a virtual key
scoped to `['llm_api_routes']`, which is what a benchmark credential is.)

⚠️ THE ENDPOINT IS NOT BYTE-STABLE. Four consecutive fetches returned three distinct payload
sizes (2,282,349 / 2,282,533 / 2,285,678 bytes) seconds apart -- almost certainly replicas with
independently refreshed caches. So a digest of the DOCUMENT is not an instrument: it would
report drift on every check. The per-model fields we price are stable across those same
fetches, so the snapshot pins FIELDS FOR NAMED MODELS and the drift check compares those.

THE GATEWAY HOST IS NOT IN THIS REPO. It comes from `ANTHROPIC_BASE_URL`, the same place
`harness.TARGET_HOST` gets it, and the snapshot records the *path* plus a digest of the host
rather than the host itself. This repo is public and the gateway is an internal name; the rates it
serves are upstream list prices, which are public anyway, so nothing is lost by not naming it.

WHY A PINNED SNAPSHOT AND NOT A LIVE LOOKUP. A published cost figure has to be recomputable
years later, and a run must not change its own numbers by being re-analysed on a day the
upstream map moved. Same reason skills/MANIFEST.json and requirements.lock exist: the rate card
is apparatus. Run this deliberately, commit the diff, and re-check any published figure.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import ssl
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pricing

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "prices.json"

COST_MAP = "/public/litellm_model_cost_map"


def gateway():
    """The gateway base URL, from the environment. Never committed -- see the docstring."""
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    if not base:
        raise SystemExit("ANTHROPIC_BASE_URL is unset -- it is where the gateway host comes from "
                         "(the same source as harness.TARGET_HOST); this repo does not carry it")
    return base


def host_digest(url):
    """sha256 of the host, first 8 hex. Enough to notice a snapshot pinned from a DIFFERENT
    gateway -- which would silently be a different rate card -- without naming it here."""
    host = urllib.parse.urlsplit(url).netloc
    return hashlib.sha256(host.encode()).hexdigest()[:8]


# Fields kept per model. Cache rates are included because scenario B used to assume the
# published Anthropic convention (read x0.10, write x1.25); the map states both outright, so
# the assumption is now a reading. `max_input_tokens` is not priced -- it is here because a
# context-window change is the other way a rate card silently stops describing a model.
FIELDS = ("input_cost_per_token", "output_cost_per_token",
          "cache_read_input_token_cost", "cache_creation_input_token_cost",
          "max_input_tokens", "litellm_provider")


def fetch_map(url=None, timeout=60):
    """The cost map, unauthenticated. No credential is sent, so none can leak."""
    url = url or gateway() + COST_MAP
    with urllib.request.urlopen(url, timeout=timeout,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read())


def extract(cost_map, models):
    out = {}
    missing = []
    for m in models:
        e = cost_map.get(m)
        if not e:
            missing.append(m)
            continue
        out[m] = {f: e.get(f) for f in FIELDS}
    return out, missing


def ratios_agree(listed, ui_rates):
    """Do all billed/list ratios agree to 4 decimals? Returns (agree, count, spread).

    The ratios themselves are computed and discarded -- deliberately. What the caller needs is
    the yes/no: a spread means the gateway is no longer applying one proportion, and every cost
    figure derived on the assumption that it does becomes an average of two things. `spread` is
    reported as a COUNT of distinct values so a failure message can be actionable without
    printing the arrangement.
    """
    ratios = []
    for m, ui in ui_rates.items():
        e = listed.get(m)
        if not e:
            continue
        for direction, key in (("in", "input_cost_per_token"),
                               ("out", "output_cost_per_token")):
            per_m = (e.get(key) or 0) * 1_000_000
            if per_m:
                ratios.append(round(ui[direction] / per_m, 4))
    distinct = set(ratios)
    return len(distinct) == 1, len(ratios), len(distinct)


def build(cost_map, models, ui_rates, url):
    listed, missing = extract(cost_map, models)
    if missing:
        raise SystemExit(f"cost map has no entry for {missing} -- refusing to write a partial "
                         f"snapshot; a model that vanished from the map is a finding, not a "
                         f"field to drop")
    agree, n, distinct = ratios_agree(listed, ui_rates)
    if not agree:
        raise SystemExit(
            f"the billed/list proportion is NOT uniform any more: {distinct} distinct values "
            f"across {n} model-directions.\nThe gateway's arrangement has changed shape -- "
            f"re-read its model pages, update pricing.PRICES, and re-check every published cost "
            f"figure before trusting one. (Run with --show-ratios if you need the numbers on "
            f"screen; they are never written to disk.)")
    return {
        "_comment": "Generated by tools/fetch_prices.py -- do not hand-edit. These are the "
                    "UPSTREAM provider's list rates, not what we are billed: the gateway bills "
                    "less. pricing.PRICES holds the billed card; the proportion between them is "
                    "deliberately recorded nowhere.",
        "source": COST_MAP,
        "source_kind": "litellm cost map served by the gateway at ANTHROPIC_BASE_URL, "
                       "unauthenticated. The host is deliberately not recorded -- this repo is "
                       "public and the gateway is an internal name; source_host_sha256_8 is enough to "
                       "catch a snapshot pinned from a different gateway.",
        "source_host_sha256_8": host_digest(url),
        "fetched": dt.date.today().isoformat(),
        "billing": "The gateway (IBM Research ETE LiteLLM, an enterprise deployment we are a "
                   "tenant of) bills BELOW these list rates, by the same proportion for every "
                   "model and both directions -- checked on every refresh, recorded here as a "
                   "yes/no only. /config/cost_margin_config would state the proportion and is "
                   "403 for a virtual key scoped to ['llm_api_routes'].",
        "billed_proportion_uniform": agree,
        "billed_model_directions_checked": n,
        "models": listed,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--show-ratios", action="store_true",
                    help="print the billed/list ratios to the terminal (never to disk) -- for "
                         "diagnosing a non-uniform arrangement")
    ap.add_argument("--check", action="store_true",
                    help="compare the live map against prices.json and exit 1 on drift; "
                         "writes nothing")
    a = ap.parse_args()

    models = sorted(pricing.PRICES)
    ui_rates = {m: {"in": p["in"], "out": p["out"]} for m, p in pricing.PRICES.items()}

    url = gateway() + COST_MAP
    cost_map = fetch_map(url)
    fresh = build(cost_map, models, ui_rates, url)

    if a.show_ratios:
        print("billed/list ratios (terminal only -- not written to prices.json):")
        for m in models:
            print(f"  {m:28} {pricing.discount_ratio(m, fresh['models'][m])}")

    if a.check:
        if not SNAPSHOT.exists():
            print("prices.json missing -- run without --check to create it")
            return 1
        old = json.loads(SNAPSHOT.read_text())
        drift = {m: (old["models"].get(m), fresh["models"][m])
                 for m in fresh["models"] if old["models"].get(m) != fresh["models"][m]}
        moved_host = old.get("source_host_sha256_8") != fresh["source_host_sha256_8"]
        uniformity_changed = (old.get("billed_proportion_uniform")
                              != fresh["billed_proportion_uniform"])
        if drift or uniformity_changed or moved_host:
            print(f"DRIFT against {SNAPSHOT.name} (pinned {old.get('fetched')}):")
            for m, (was, now) in drift.items():
                print(f"  {m}\n    pinned {was}\n    live   {now}")
            if uniformity_changed:
                print(f"  billed proportion uniform: pinned "
                      f"{old.get('billed_proportion_uniform')} live "
                      f"{fresh['billed_proportion_uniform']} -- the gateway's arrangement "
                      f"changed shape; --show-ratios to see how")
            if moved_host:
                print(f"  gateway host: pinned sha256:{old.get('source_host_sha256_8')} "
                      f"live sha256:{fresh['source_host_sha256_8']} -- a DIFFERENT gateway, so "
                      f"this is a different rate card, not drift in one")
            return 1
        print(f"prices.json matches the live cost map ({len(fresh['models'])} models, "
              f"billed proportion still uniform across "
              f"{fresh['billed_model_directions_checked']} model-directions, pinned "
              f"{old.get('fetched')})")
        return 0

    SNAPSHOT.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}  ({len(fresh['models'])} models; billed "
          f"proportion uniform across {fresh['billed_model_directions_checked']} "
          f"model-directions)")
    for m, e in sorted(fresh["models"].items()):
        i = e["input_cost_per_token"] * 1e6
        o = e["output_cost_per_token"] * 1e6
        hand = pricing.PRICES[m]
        print(f"  {m:28} upstream list {i:6.2f}/{o:6.2f}  ->  we are billed "
              f"{hand['in']:6.2f}/{hand['out']:6.2f}  per 1M")
    print("\nRe-run any published cost figure if a rate moved: the snapshot is apparatus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
