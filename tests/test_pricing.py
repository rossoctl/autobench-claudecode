"""Tests for the rate card -- the money, pinned to two independent sources.

WHY THIS FILE EXISTS. Every dollar figure in results/ was computed from `pricing.PRICES`, which
was transcribed by hand from the gateway UI. `prices.json` pins the UPSTREAM provider's list
rates from the gateway's own cost map, and the billed card is those scaled by each model's own
billed/list ratio -- computed at load, stored nowhere. Two paths to one number is only an
improvement if they are held against each other: if a refresh moved a rate, the published figures
are stale and that must surface as a test failure rather than as quietly different money.

The proportion between the two cards is a term of an enterprise deployment (IBM Research's ETE
LiteLLM, which we are a tenant of), so no test asserts its value -- only that it is uniform and
that it reproduces the billed card.

The regression pin below matters more than it looks. `cost()` was rewritten from
"multiply input by a cache multiplier" to "read a cache tier's own rate", which is arithmetically
identical ONLY while the map keeps stating x0.10 and x1.25. Pinning a known vector means the day
that stops being true, the suite says so instead of the next report reading differently.
"""
import datetime as dt
import inspect
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pricing

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "prices.json"

# One real repetition's token counts (xlsx-fin-colors, claude-opus-5, ON arm) and the dollars
# the published grid was built with. Frozen deliberately -- see the module docstring.
PINNED_VECTOR = dict(uncached=43, cache_read=191157, cache_write=11246, output=1709)
PINNED_B = 0.15869256
PINNED_A = 0.80176580


def snapshot():
    if not SNAPSHOT.exists():
        pytest.skip("prices.json absent -- run tools/fetch_prices.py")
    return json.loads(SNAPSHOT.read_text())


def test_the_snapshot_scales_to_the_hand_transcribed_card_exactly():
    """list rate x the model's own ratio must equal what the gateway UI showed, to the cent.

    This is the whole justification for automating the pull: the two sources agree, so the
    cheap one can be refreshed without re-reading screenshots. Disagreement means either the
    billing arrangement moved or a model was repriced -- both invalidate published figures.
    """
    snap = snapshot()
    for model, hand in pricing.PRICES.items():
        e = snap["models"][model]
        ratio = pricing.discount_ratio(model, e)
        assert ratio is not None, f"{model}: input and output ratios disagree"
        for direction, key in (("in", "input_cost_per_token"), ("out", "output_cost_per_token")):
            derived = round(e[key] * 1_000_000 * ratio, 6)
            assert derived == hand[direction], (
                f"{model} {direction}: scaled list rate = {derived}, "
                f"hand-transcribed card says {hand[direction]}")


def test_the_billed_proportion_is_uniform_across_models_and_directions():
    """One proportion is the claim; eight independent ratios are the evidence for it.

    If one model ever prices differently, the proportion stops being a property of the gateway
    and becomes an average -- at which point no cost figure scaled by it means anything. The
    assertion is on UNIFORMITY, not on the value: the value is somebody else's contract term,
    and pinning it in a test would publish it just as effectively as printing it.
    """
    snap = snapshot()
    ratios = set()
    for model, hand in pricing.PRICES.items():
        e = snap["models"][model]
        ratios.add(round(hand["in"] / (e["input_cost_per_token"] * 1_000_000), 4))
        ratios.add(round(hand["out"] / (e["output_cost_per_token"] * 1_000_000), 4))
    assert len(ratios) == 1, f"{len(ratios)} distinct ratios -- not one arrangement any more"
    assert snap["billed_proportion_uniform"] is True
    assert snap["billed_model_directions_checked"] == 2 * len(pricing.PRICES)


def test_cache_tiers_are_read_from_the_map_not_assumed():
    """The x0.10 / x1.25 convention is now a reading, and the test says which.

    It stays asserted because scenario B's arithmetic depends on it: the moment the map states
    a different cacheRead ratio, every B figure in results/ is wrong by that difference.
    """
    snap = snapshot()
    for model, e in snap["models"].items():
        i = e["input_cost_per_token"]
        assert e["cache_read_input_token_cost"] == pytest.approx(i * pricing.CACHE_READ_MULT)
        assert e["cache_creation_input_token_cost"] == pytest.approx(i * pricing.CACHE_WRITE_MULT)


def test_cost_matches_the_figures_the_published_grid_was_built_with():
    for scenario, expected in (("B", PINNED_B), ("A", PINNED_A)):
        got = pricing.cost("claude-opus-5", scenario=scenario, **PINNED_VECTOR)
        assert got == pytest.approx(expected, abs=1e-8), f"scenario {scenario}"


def test_cost_without_the_snapshot_still_reproduces_the_same_dollars(monkeypatch):
    """A checkout with no prices.json must price a run identically.

    The snapshot is a convenience for refreshing, not a dependency: results have to be
    recomputable from the repo alone, and a consumer who cannot reach the gateway still needs
    the cost column.
    """
    monkeypatch.setattr(pricing, "SNAP", None)
    got = pricing.cost("claude-opus-5", scenario="B", **PINNED_VECTOR)
    assert got == pytest.approx(PINNED_B, abs=1e-8)


def test_snapshot_records_its_provenance_and_stores_no_billing_proportion():
    """Provenance is part of the datum, and so is the deliberate absence.

    `billing` exists so nobody later reads these rates as what we pay -- they are the upstream
    provider's list. No numeric proportion is stored, by design: it is a term of an enterprise
    deployment, and a generated file is the easiest place for one to end up published.
    """
    snap = snapshot()
    assert snap["source"].endswith("/public/litellm_model_cost_map")
    assert "ETE" in snap["billing"]
    for banned in ("margin", "margin_ratios_observed", "billed_proportion"):
        assert banned not in snap, f"{banned} is back in the snapshot"
    # ...and no module constant holds it either. `rates()` scales by a ratio computed from the
    # two cards at load time; a constant would be the same disclosure with extra steps, and it
    # would also silently outlive a change in the arrangement.
    assert not hasattr(pricing, "MARGIN"), "a stored proportion constant is back in pricing.py"
    assert dt.date.fromisoformat(snap["fetched"]) <= dt.date.today()
    assert set(snap["models"]) == set(pricing.PRICES)


def test_the_fetch_path_sends_no_credential():
    """The cost map is unauthenticated, and the tool must stay that way.

    A credential on this path would be both unnecessary and a new place for one to leak --
    and it would quietly couple price refreshes to whoever's key is in the environment.
    """
    src = inspect.getsource(sys.modules[__name__])       # keep the import local to this test
    fetch = (ROOT / "tools" / "fetch_prices.py").read_text()
    body = fetch.split("def fetch_map", 1)[1].split("\ndef ", 1)[0]
    for bad in ("Authorization", "ANTHROPIC_AUTH_TOKEN", "api_key", "Bearer"):
        assert bad not in body, f"fetch_map references {bad}"
    assert "/public/litellm_model_cost_map" in fetch
    assert src  # the source guard itself resolved


def test_neither_the_tool_nor_the_snapshot_names_the_gateway_host():
    """The host comes from ANTHROPIC_BASE_URL, like harness.TARGET_HOST. This repo is public.

    The rates are upstream list prices and public anyway, so recording the internal hostname
    would disclose something for no analytical gain. A digest is kept instead, which is enough
    to catch a snapshot pinned against a DIFFERENT gateway -- a different rate card, not drift.
    """
    snap = snapshot()
    assert snap["source"] == "/public/litellm_model_cost_map"      # a path, not a URL
    assert len(snap["source_host_sha256_8"]) == 8
    blob = json.dumps(snap) + (ROOT / "tools" / "fetch_prices.py").read_text()
    for marker in ("vpc-int", "res.ibm.com", "://"):
        assert marker not in blob, f"gateway host leaked into the repo via {marker!r}"


def test_staleness_warns_only_past_the_limit():
    fetched = dt.date.fromisoformat((pricing.SNAP or {}).get("fetched") or pricing.SOURCE_DATE)
    assert pricing.staleness_warning(today=fetched) is None
    assert pricing.staleness_warning(
        today=fetched + dt.timedelta(days=pricing.STALE_AFTER_DAYS)) is None
    late = fetched + dt.timedelta(days=pricing.STALE_AFTER_DAYS + 1)
    w = pricing.staleness_warning(today=late)
    assert w and "fetch_prices" in w
    assert pricing.stale_days(today=late) == pricing.STALE_AFTER_DAYS + 1
