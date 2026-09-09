"""Unit tests for the confound detector in `harness.analyse_transcript`.

WHY THIS FILE EXISTS. The subagent detector matched a tool named `Task`, but this Claude
Code build names the subagent tool `Agent`. It therefore never fired, five repetitions that
spawned downstream work were scored clean, and a published skill-overhead figure of "18x"
was really 3.0x once the contaminated reps were dropped. The code was fixed on 2026-09-09
-- and the project memory recorded it as "unit-tested against each", which was not true.
The fix landed; the test did not. This file is that test.

A detector that has never fired is indistinguishable from a broken one, so every name gets
a synthetic POSITIVE, and the clean transcript gets a NEGATIVE that must stay quiet.

The load-bearing test is `test_every_declared_tool_name_has_a_case`: it fails if someone
adds a name to `SUBAGENT_TOOLS` or `BACKGROUND_TOOLS` without adding a case here. That is
the specific failure this file is designed to make impossible to repeat.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness
from harness import analyse_transcript

# Names that must land in the `subagents` bucket: work happening in its own agent loop.
SUBAGENT_CASES = {"Agent", "Task"}
# Names that must land in the `background` bucket: not a spawn, but evidence of async work
# whose LLM calls land in our measurement window without belonging to the main loop.
BACKGROUND_CASES = {"TaskOutput", "TaskStop"}


def synth(*content_blocks):
    """A minimal stream-json transcript carrying the given assistant content blocks."""
    lines = [json.dumps({"type": "system", "subtype": "init", "slash_commands": []})]
    for cb in content_blocks:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [cb]}}))
    lines.append(json.dumps({"type": "result", "subtype": "success", "is_error": False}))
    return "\n".join(lines)


def tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


# --------------------------------------------------------------- the negative

def test_clean_transcript_flags_nothing():
    """The case that must stay quiet. Without this, an always-firing detector passes."""
    tr = analyse_transcript(synth(tool("Edit", file_path="x.py"),
                                  tool("Read", file_path="y.py"),
                                  tool("Bash", command="pytest -q")))
    assert tr["subagents"] == []
    assert tr["background"] == []
    assert tr["skills"] == []
    assert tr["tools"] == ["Edit", "Read", "Bash"]


def test_empty_transcript_is_not_an_error():
    tr = analyse_transcript("")
    assert tr["subagents"] == [] and tr["background"] == [] and tr["tools"] == []


def test_non_json_lines_are_skipped():
    """Real stdout carries banner/warning lines; they must not crash the parser."""
    noisy = "some warning\n" + synth(tool("Agent", subagent_type="Explore")) + "\ntrailing"
    assert analyse_transcript(noisy)["subagents"] == ["Explore"]


# ------------------------------------------------------- subagents (the bug)

@pytest.mark.parametrize("name", sorted(SUBAGENT_CASES))
def test_subagent_tool_is_detected(name):
    """`Agent` is the name that was blind for this detector's whole life."""
    tr = analyse_transcript(synth(tool(name, subagent_type="general-purpose")))
    assert tr["subagents"] == ["general-purpose"], f"{name} not seen as a subagent"
    assert tr["background"] == [], f"{name} must not be counted as background work"


@pytest.mark.parametrize("name", sorted(SUBAGENT_CASES))
def test_subagent_without_a_type_falls_back_to_the_tool_name(name):
    """A spawn with no `subagent_type` must still be reported, not silently dropped."""
    assert analyse_transcript(synth(tool(name)))["subagents"] == [name]


def test_two_subagents_are_both_recorded():
    tr = analyse_transcript(synth(tool("Agent", subagent_type="Explore"),
                                  tool("Task", subagent_type="Plan")))
    assert tr["subagents"] == ["Explore", "Plan"]


# ---------------------------------------------------- background async work

@pytest.mark.parametrize("name", sorted(BACKGROUND_CASES))
def test_background_tool_is_detected_and_not_mistaken_for_a_spawn(name):
    tr = analyse_transcript(synth(tool(name, task_id="abc123")))
    assert tr["background"] == [name], f"{name} not seen as background work"
    assert tr["subagents"] == [], f"{name} is not a spawn and must not be one"


# ------------------------------------------------------------------- skills

def test_skill_invocation_is_detected_with_its_name():
    tr = analyse_transcript(synth(tool("Skill", skill="brand-guidelines")))
    assert tr["skill_names"] == ["brand-guidelines"]
    assert tr["subagents"] == [] and tr["background"] == []


def test_slash_command_name_is_normalised():
    """SlashCommand carries `command`, often with a leading slash and arguments."""
    tr = analyse_transcript(synth(tool("SlashCommand", command="/xlsx make a sheet")))
    assert tr["skill_names"] == ["xlsx"]


def test_skill_and_subagent_together():
    tr = analyse_transcript(synth(tool("Skill", skill="pdf"),
                                  tool("Agent", subagent_type="general-purpose")))
    assert tr["skill_names"] == ["pdf"]
    assert tr["subagents"] == ["general-purpose"]


def test_assistant_turns_are_counted():
    tr = analyse_transcript(synth(tool("Edit", file_path="a"), tool("Edit", file_path="b")))
    assert tr["assistant_turns"] == 2


# ------------------------------------------------- the anti-regression guard

def test_every_declared_tool_name_has_a_case():
    """Adding a name to the harness constants without a test here must FAIL.

    This is the test that would have caught the original bug's real cause: the constant was
    corrected but nothing asserted the corrected value was exercised. Keep it.
    """
    declared = set(harness.SUBAGENT_TOOLS) | set(harness.BACKGROUND_TOOLS)
    covered = SUBAGENT_CASES | BACKGROUND_CASES
    assert declared == covered, (
        f"untested tool names: {sorted(declared - covered)}; "
        f"stale cases: {sorted(covered - declared)}")


def test_subagent_and_background_buckets_are_disjoint():
    assert not (set(harness.SUBAGENT_TOOLS) & set(harness.BACKGROUND_TOOLS))
