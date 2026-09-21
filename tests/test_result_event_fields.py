"""Tests for the CLI `result` event -- the row's only proxy-independent instrument.

WHY THIS FILE EXISTS. `analyse_transcript` parsed the result event from the very first
version and `run_rep` then kept exactly one field out of it (`assistant_turns`), dropping the
timing and usage numbers on the floor. Nothing failed; the rows simply had no latency column,
so every timing question got answered with `wall_seconds` -- which follows machine load
(x1.34-1.81 for two models doing provably identical work) and therefore cannot answer it. So
these tests pin the fields to the ROW, not merely to the parser: the parser was never the
part that broke.

They also pin the WHITELIST. The result event carries `result`, the final assistant text, and
`modelUsage`, a nested per-model blob. `out/` is gitignored precisely because prompts must not
reach an artifact; a field that arrives with a future CLI upgrade must not ride along with
them.
"""
import inspect
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

# Shaped like a real result event, including the parts that must NOT be persisted.
RESULT = {
    "type": "result",
    "subtype": "success",
    "duration_ms": 61234,
    "duration_api_ms": 48120,
    "ttft_ms": 3120,
    "ttft_stream_ms": 2980,
    "time_to_request_ms": 640,
    "num_turns": 9,
    "total_cost_usd": 0.0415,
    "usage": {
        "input_tokens": 11,
        "cache_creation_input_tokens": 2864,
        "cache_read_input_tokens": 190_112,
        "output_tokens": 6021,
        # Nested sub-objects appear and disappear across CLI versions.
        "cache_creation": {"ephemeral_5m_input_tokens": 2864},
        "server_tool_use": {"web_search_requests": 0},
    },
    "result": "I created model.xlsx with the blue-for-inputs convention applied.",
    "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 11, "costUSD": 0.0415}},
}

ALLOWED_KEYS = {f"cli_{k}" for k in harness.RESULT_KEEP} | {"cli_usage"}


def test_timing_is_extracted():
    f = harness.result_fields(RESULT)
    assert f["cli_duration_api_ms"] == 48120
    assert f["cli_duration_ms"] == 61234
    assert f["cli_ttft_ms"] == 3120
    assert f["cli_num_turns"] == 9
    # Name is mechanically `cli_` + the CLI's own field name, so a row column can always be
    # traced back to the event it came from.
    assert f["cli_total_cost_usd"] == 0.0415


def test_api_time_is_distinguishable_from_wall_time():
    """The whole point of the field: it excludes local tool execution.

    If a future refactor made `cli_duration_api_ms` an alias for the wall clock, the latency
    column would silently become the diagnostic it was meant to replace.
    """
    f = harness.result_fields(RESULT)
    assert f["cli_duration_api_ms"] < f["cli_duration_ms"]


def test_missing_result_yields_None_not_zero():
    """A timed-out or killed repetition reports no result event at all.

    Every key must still be present -- a column that appears only sometimes turns a missing
    measurement into a missing row -- and every value must be None, because a 0 ms latency
    would average in as the fastest repetition in the cell.
    """
    for empty in (None, {}):
        f = harness.result_fields(empty)
        assert set(f) == ALLOWED_KEYS
        assert set(f.values()) == {None}


def test_no_content_and_no_unlisted_field_survives():
    f = harness.result_fields(RESULT)
    assert set(f) == ALLOWED_KEYS, "an unlisted result field reached the row"
    blob = json.dumps(f)
    assert "blue-for-inputs" not in blob, "the final assistant text reached the row"
    assert "modelUsage" not in blob and "costUSD" not in blob


def test_usage_keeps_counts_and_drops_nested_objects():
    usage = harness.result_fields(RESULT)["cli_usage"]
    assert usage == {"input_tokens": 11, "cache_creation_input_tokens": 2864,
                     "cache_read_input_tokens": 190_112, "output_tokens": 6021}
    assert all(isinstance(v, int) for v in usage.values())


def test_parser_to_fields_round_trip():
    """The path that actually runs: stream-json text -> analyse_transcript -> result_fields."""
    stdout = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant",
                    "message": {"content": [{"type": "text", "text": "working"}]}}),
        json.dumps(RESULT),
    ])
    tr = harness.analyse_transcript(stdout)
    assert tr["result"] is not None
    assert harness.result_fields(tr["result"])["cli_duration_api_ms"] == 48120


def test_run_rep_persists_them():
    """The guard for the defect itself: parsing them and then not keeping them.

    `analyse_transcript` returned the result event for weeks while `run_rep` used one field of
    it. A source-level check is the only kind that catches that, because no runtime assertion
    fires when a row is merely missing a column.
    """
    src = inspect.getsource(harness.run_rep)
    assert "result_fields(tr" in src, (
        "run_rep no longer persists the CLI result event's timing -- the row's only "
        "proxy-independent measurement")
