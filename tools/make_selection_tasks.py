#!/usr/bin/env python3
"""Phase-3 task set: skill SELECTION.

A different benchmark from the compliance arms. Here every candidate skill is available,
the prompt never names one, and the verdict is "did the right skill fire" -- read from the
transcript, which DOES see model-selected skills (an explicit /skill-name would not appear
there at all).

Two design points that make this a benchmark rather than a demo:

  * A negative case is mandatory. Measuring only true positives would reward a model that
    fires a skill on everything. `select-none` is an ordinary Python bugfix where the right
    behaviour is to invoke NO skill.
  * Difficulty is graded. `select-spreadsheet` / `select-deck` name the artifact outright
    and should be easy; `select-implicit-sheet` describes the need without ever saying
    "spreadsheet", which is where selection actually gets tested.
"""
import json
import pathlib
import shutil
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent / "tasks"

# A real choice, not a formality: four plausible document skills, all installed.
CANDIDATES = ["xlsx", "docx", "pptx", "pdf"]
TOOLS = ["Bash(node*)", "Bash(npm*)", "Bash(python*)", "Bash(soffice*)",
         "Bash(ls*)", "Bash(cat*)"]

TASKS = {
    # ---- easy: the artifact is named outright -------------------------------------
    "select-spreadsheet": {
        "expected": "xlsx",
        "prompt": """
            Put together a spreadsheet called `headcount.xlsx` listing our four teams —
            Platform 12 people, Product 9, Data 5, Design 3 — with a total row.
            """,
    },
    "select-deck": {
        "expected": "pptx",
        "prompt": """
            Build me a short slide deck `kickoff.pptx` — three slides introducing a project
            called Northstar: what it is, why now, and the first milestone.
            """,
    },
    # ---- harder: the need is described, the artifact is not named -----------------
    "select-implicit-sheet": {
        "expected": "xlsx",
        "prompt": """
            I have last month's order data — 340 rows with customer, region, product and
            amount. Finance wants to be able to sort it, filter by region and total up the
            amounts themselves rather than getting a static summary from me.

            Give them something they can do that in. Make up plausible sample rows.
            """,
    },
    # ---- negative: the right answer is to invoke nothing --------------------------
    "select-none": {
        "expected": None,
        "prompt": """
            The pytest suite in this directory fails. Fix the bug in the source so that all
            tests pass. Do not modify any test_*.py file — the tests are correct.
            """,
        "workspace": {
            "shipping.py": '''\
def band_for_weight(grams):
    """Return the shipping band for a parcel weight in grams.

    Bands: up to 500g -> "small", up to 2000g -> "medium", above -> "large".
    """
    if grams <= 500:
        return "small"
    # BUG: boundary is wrong, 2000g should still be medium.
    if grams < 2000:
        return "medium"
    return "large"
''',
            "test_shipping.py": '''\
from shipping import band_for_weight


def test_small():
    assert band_for_weight(500) == "small"


def test_medium_lower():
    assert band_for_weight(501) == "medium"


def test_medium_upper_boundary():
    assert band_for_weight(2000) == "medium"


def test_large():
    assert band_for_weight(2001) == "large"
''',
        },
    },
}


def main():
    for name, spec in TASKS.items():
        d = ROOT / name
        if d.exists():
            shutil.rmtree(d)
        (d / "workspace").mkdir(parents=True)
        (d / "prompt.md").write_text(textwrap.dedent(spec["prompt"]).strip() + "\n")
        files = spec.get("workspace")
        if files:
            for fn, content in files.items():
                (d / "workspace" / fn).write_text(content)
        else:
            (d / "workspace" / "README.txt").write_text(
                "Working directory for this task. Produce the deliverable here.\n")
        (d / "meta.json").write_text(json.dumps({
            "mode": "selection",
            "expected_skill": spec["expected"],
            "candidate_skills": CANDIDATES,
            "allowed_tools_extra": TOOLS,
        }, indent=2) + "\n")
        print(f"  built {name:24} expect={spec['expected'] or '<no skill>'}")


if __name__ == "__main__":
    main()
