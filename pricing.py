#!/usr/bin/env python3
"""Monetary cost for the profile cells, from the internal LiteLLM price list.

Prices transcribed from the gateway's own model pages
(`/ui/?page=models`, 2026-09-09). The gateway's `/model/info` endpoint returns 403 for a
non-admin key, so these could not be pulled programmatically and are hand-entered.

TWO SCENARIOS, because the gateway publishes only Input and Output rates:

  A  no-cache-discount   every prompt token billed at the Input rate. Upper bound.
  B  standard cache      cacheRead x0.10, cacheWrite x1.25, uncached x1.00 -- the
                         published Anthropic/Bedrock convention.

Which one the gateway actually bills is UNVERIFIED, and it matters enormously: cache reads
are 81-97% of prompt tokens in every cell, so B lands roughly 5-8x below A. Treat A as the
worst case and B as the likely case, and confirm against a real invoice before quoting
either as fact.

Caveat on names: the price pages are titled `aws/claude-*`, while the benchmark pinned the
bare aliases (`claude-sonnet-5`). Both route, and Cortex confirmed the bare alias is what
was served, but whether the bare alias bills at the same rate as the `aws/` entry could not
be verified with a non-admin key. Same-underlying-model is assumed.
"""

PRICE_ROUTES = ("/v2/model/info", "/model/info", "/model_group/info")


def fetch_live(base=None, token=None):
    """Try to pull the rate card from the gateway. Returns {} when not permitted.

    Wired even though it currently fails: the benchmark credential is a LiteLLM VIRTUAL
    key restricted to `llm_api_routes`, so every management route returns

        403 {"detail": "Virtual key is not allowed to call this route.
             Only allowed to call routes: ['llm_api_routes']"}

    Pricing needs an admin/master key or a UI session. The UI page itself embeds no
    prices -- it is a client-side app that fetches from these same routes. Supply an
    admin key as LITELLM_ADMIN_KEY and this takes over from the transcribed table below.
    """
    import json as _json
    import os as _os
    import ssl as _ssl
    import urllib.error as _err
    import urllib.request as _req
    base = (base or _os.environ.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
    token = token or _os.environ.get("LITELLM_ADMIN_KEY") or _os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not (base and token):
        return {}
    ctx = _ssl.create_default_context()
    for route in PRICE_ROUTES:
        r = _req.Request(base + route, headers={"Authorization": "Bearer " + token})
        try:
            with _req.urlopen(r, timeout=25, context=ctx) as resp:
                rows = _json.loads(resp.read()).get("data", [])
        except (_err.HTTPError, Exception):
            continue
        out = {}
        for e in rows:
            name = e.get("model_name") or e.get("model_group")
            info = e.get("model_info") or {}
            ic, oc = info.get("input_cost_per_token"), info.get("output_cost_per_token")
            if name and ic is not None and oc is not None:
                out[name] = {"in": ic * 1e6, "out": oc * 1e6, "source": f"live {route}"}
        if out:
            return out
    return {}


# $ per 1M tokens. SOURCE: transcribed from the gateway's own model pages
# (/ui/?page=models) on 2026-09-09, because fetch_live() above is refused for this key.
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


def cost(model, *, uncached, cache_read, cache_write, output, scenario="B"):
    """Dollars for one run's token counts."""
    p = PRICES[model]
    if scenario == "A":
        prompt_cost = (uncached + cache_read + cache_write) * p["in"] / M
    else:
        prompt_cost = (uncached * 1.0
                       + cache_read * CACHE_READ_MULT
                       + cache_write * CACHE_WRITE_MULT) * p["in"] / M
    return prompt_cost + output * p["out"] / M


def table():
    rows = []
    for m, p in PRICES.items():
        rows.append((m, p["ui"], p["in"], p["out"], p["out"] / p["in"]))
    return rows


if __name__ == "__main__":
    live = fetch_live()
    print(f"{'benchmarked alias':28} {'gateway entry':24} {'in $/1M':>8} {'out $/1M':>9} {'out:in':>7}")
    for m, ui, i, o, r in table():
        print(f"{m:28} {ui:24} {i:>8.2f} {o:>9.2f} {r:>6.1f}x")
    print()
    if not live:
        print("  source: TRANSCRIBED from the gateway UI (2026-09-09).")
        print("  live fetch refused: the benchmark key is a LiteLLM virtual key limited to")
        print("  llm_api_routes; /v2/model/info and friends return 403. Set LITELLM_ADMIN_KEY")
        print("  to pull the rate card directly instead.")
    else:
        print("  source: LIVE from the gateway. Reconciling against the transcribed table:")
        for m, p in PRICES.items():
            for key in (m, p["ui"]):
                if key in live:
                    d_in = abs(live[key]["in"] - p["in"])
                    d_out = abs(live[key]["out"] - p["out"])
                    flag = "OK" if (d_in < 0.005 and d_out < 0.005) else "MISMATCH"
                    print(f"    {key:26} live {live[key]['in']:.2f}/{live[key]['out']:.2f}  "
                          f"transcribed {p['in']:.2f}/{p['out']:.2f}  {flag}")
                    break
    print(f"\n  Cache multipliers in scenario B: read x{CACHE_READ_MULT}, "
          f"write x{CACHE_WRITE_MULT} (unverified for this gateway)")
