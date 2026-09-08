#!/usr/bin/env python3
"""Generate the Phase-1 xlsx task set.

Design rules applied to every task:
  * The PROMPT is an ordinary request and never names a convention. If it said "use blue
    for inputs", the skill-OFF arm would simply comply and the discriminator would die.
  * The VERDICT lives in verdict/ (hidden -- installed only after the agent exits) and
    asserts the conventions the xlsx SKILL.md mandates, i.e. knowledge the model is
    unlikely to volunteer unaided.
  * Assertions are written to be FAIR: openpyxl reports default/unstyled as None, so we
    assert "is blue" positively but only "is NOT blue" negatively, never "== black".
"""
import json
import pathlib
import shutil
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent / "tasks"
SKILL = "xlsx"
# Distinctive phrase from xlsx/SKILL.md, used to confirm on the wire that the skill
# text was actually injected (an explicit /skill-name leaves no tool_use).
MARKER = "Blue text (RGB: 0,0,255)"

HELPERS = '''
import glob
import pathlib

import openpyxl
import pytest


def _book(data_only=False):
    """Load the single .xlsx the agent produced. Fails loudly if absent/ambiguous."""
    here = pathlib.Path(__file__).parent
    found = [p for p in here.glob("*.xlsx") if not p.name.startswith("~$")]
    assert found, f"no .xlsx produced in {here}"
    assert len(found) == 1, f"expected exactly one .xlsx, got {[p.name for p in found]}"
    return openpyxl.load_workbook(found[0], data_only=data_only)


def _cells(ws):
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                yield c


def _is_blue(cell):
    col = getattr(cell.font, "color", None)
    rgb = getattr(col, "rgb", None)
    return isinstance(rgb, str) and rgb.upper().endswith("0000FF")


def _is_formula(cell):
    return isinstance(cell.value, str) and cell.value.startswith("=")


def _fmts(ws):
    return [c.number_format for c in _cells(ws)]
'''

TASKS = {}

# ---------------------------------------------------------------- 1. colour coding
TASKS["xlsx-fin-colors"] = {
    "prompt": """
        Build me a spreadsheet called `model.xlsx` with a three-year revenue projection.

        Start from FY2024 revenue of 12,400,000 and grow it at 8% a year to give FY2025,
        FY2026 and FY2027. Put the starting revenue and the growth rate somewhere sensible
        as inputs I can change, and have the projected years calculate from them.

        Label everything clearly enough that a colleague could follow it.
        """,
    "files": {},
    "test": '''
def test_hardcoded_inputs_are_blue():
    """The skill mandates blue font for hardcoded inputs the user will change."""
    ws = _book().active
    numeric_inputs = [c for c in _cells(ws)
                      if not _is_formula(c) and isinstance(c.value, (int, float))]
    assert numeric_inputs, "no numeric input cells found"
    blue = [c for c in numeric_inputs if _is_blue(c)]
    assert blue, ("no hardcoded numeric input is blue; "
                  f"inputs found at {[c.coordinate for c in numeric_inputs]}")


def test_formulas_are_not_blue():
    """Blue is reserved for inputs; formulas must not be blue."""
    ws = _book().active
    formulas = [c for c in _cells(ws) if _is_formula(c)]
    assert formulas, "no formula cells found -- projection appears hardcoded"
    offenders = [c.coordinate for c in formulas if _is_blue(c)]
    assert not offenders, f"formula cells wrongly coloured blue: {offenders}"
''',
}

# ---------------------------------------------------------------- 2. number formats
TASKS["xlsx-fin-numfmt"] = {
    "prompt": """
        Create `model.xlsx` summarising a valuation for a company called Northwind.

        It should show enterprise value of 480,000,000, EBITDA of 60,000,000, the implied
        EV/EBITDA multiple, revenue of 250,000,000 and the EBITDA margin. Compute the
        multiple and the margin rather than typing them in.

        Make it presentable enough to drop into a deck.
        """,
    "files": {},
    "test": '''
def test_currency_cells_use_thousands_currency_format():
    ws = _book().active
    fmts = _fmts(ws)
    assert any("$" in f and "#,##0" in f for f in fmts), \\
        f"no currency cell formatted like $#,##0; formats seen: {sorted(set(fmts))}"


def test_percentage_uses_one_decimal():
    ws = _book().active
    pct = [f for f in _fmts(ws) if "%" in f]
    assert pct, f"no percent-formatted cell; formats seen: {sorted(set(_fmts(ws)))}"
    assert any("0.0%" in f for f in pct), \\
        f"margin should default to 0.0% (one decimal); percent formats: {pct}"


def test_multiple_formatted_with_x_suffix():
    ws = _book().active
    fmts = _fmts(ws)
    assert any("x" in f.lower() and "0.0" in f for f in fmts), \\
        f"EV/EBITDA multiple should be formatted 0.0x; formats seen: {sorted(set(fmts))}"
''',
}

# ---------------------------------------------------------------- 3. zeros/negatives
TASKS["xlsx-fin-zeros-negs"] = {
    "prompt": """
        Produce `model.xlsx` with a small quarterly free-cash-flow table for FY2025.

        The four quarters are -1,250,000 then 0 then 3,400,000 then -800,000, and add a
        full-year total that sums them. Include a row above it for quarterly capex of
        900,000, 0, 1,100,000 and 0.

        It is going in front of the CFO, so make the presentation clean.
        """,
    "files": {},
    "test": '''
def test_negatives_shown_in_parentheses():
    """Skill rule: negative numbers use parentheses, not a minus sign."""
    ws = _book().active
    fmts = _fmts(ws)
    assert any("(" in f and ")" in f for f in fmts), \\
        f"no number format renders negatives in parentheses; formats: {sorted(set(fmts))}"


def test_zeros_render_as_dash():
    """Skill rule: zeros display as '-' via number formatting."""
    ws = _book().active
    zero_cells = [c for c in _cells(ws) if c.value == 0]
    assert zero_cells, "no zero-valued cells found"
    dashed = [c for c in zero_cells
              if c.number_format.count(";") >= 2 and '"-"' in c.number_format
              or c.number_format.endswith(';-') or ';"-"' in c.number_format
              or c.number_format.count(";") >= 2 and c.number_format.split(";")[2].strip() in ('-', '"-"')]
    assert dashed, ("zero cells should format as '-'; formats at "
                    f"{[(c.coordinate, c.number_format) for c in zero_cells]}")
''',
}

# ---------------------------------------------------------------- 4. assumption refs
TASKS["xlsx-fin-assumption-refs"] = {
    "prompt": """
        Make `model.xlsx` projecting headcount cost for FY2025 through FY2028.

        FY2024 cost is 4,800,000 and it rises 6.5% each year. Each projected year should
        follow from the previous one.

        Keep it simple and readable.
        """,
    "files": {},
    "test": '''
def test_growth_is_a_cell_reference_not_a_literal():
    """Skill rule: use =B5*(1+$B$6), never =B5*1.065."""
    ws = _book().active
    formulas = [c for c in _cells(ws) if _is_formula(c)]
    assert formulas, "no formulas found -- projection appears hardcoded"
    growth = [c for c in formulas if "*" in c.value or "+" in c.value]
    assert growth, f"no arithmetic formula found; formulas: {[c.value for c in formulas]}"
    hardcoded = [c.coordinate for c in growth
                 if "1.065" in c.value.replace(" ", "")
                 or "0.065" in c.value.replace(" ", "")
                 or "6.5%" in c.value]
    assert not hardcoded, \\
        f"growth rate hardcoded into formulas at {hardcoded} instead of referencing a cell"


def test_projection_formulas_reference_other_cells():
    ws = _book().active
    formulas = [c for c in _cells(ws) if _is_formula(c)]
    referencing = [c for c in formulas if any(ch.isdigit() for ch in c.value)
                   and any(ch.isalpha() for ch in c.value)]
    assert referencing, f"formulas do not reference cells: {[c.value for c in formulas]}"
''',
}

# ---------------------------------------------------------------- 5. font + errors
TASKS["xlsx-fin-font-clean"] = {
    "prompt": """
        Build `model.xlsx` with a two-scenario opex summary.

        Base case opex is 7,200,000 and the upside case is 6,150,000; show the absolute
        saving and the saving as a share of the base case, both calculated. Give the sheet
        a title row.

        Make it look like something a finance team would circulate.
        """,
    "files": {},
    "test": '''
PROFESSIONAL = {"arial", "times new roman", "helvetica", "calibri light", "garamond"}


def test_uses_a_professional_font_consistently():
    """Skill rule: a consistent professional font (e.g. Arial, Times New Roman).
    Calibri is Excel's unstyled default and is what you get by not deciding."""
    ws = _book().active
    names = {(c.font.name or "").strip().lower() for c in _cells(ws)}
    names.discard("")
    assert names, "no fonts set on any cell"
    assert len(names) == 1, f"font is not consistent across cells: {sorted(names)}"
    only = next(iter(names))
    assert only in PROFESSIONAL, \\
        f"font {only!r} is not one of the professional fonts {sorted(PROFESSIONAL)}"


def test_no_formula_error_literals():
    """Skill rule: zero formula errors delivered."""
    for data_only in (False, True):
        ws = _book(data_only=data_only).active
        bad = [(c.coordinate, c.value) for c in _cells(ws)
               if isinstance(c.value, str)
               and any(e in c.value for e in
                       ("#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?"))]
        assert not bad, f"formula errors present: {bad}"


def test_savings_are_calculated_not_typed():
    ws = _book().active
    formulas = [c for c in _cells(ws) if _is_formula(c)]
    assert len(formulas) >= 2, \\
        f"expected the saving and the ratio to be formulas; found {len(formulas)}"
''',
}


def main():
    for name, spec in TASKS.items():
        d = ROOT / name
        if d.exists():
            shutil.rmtree(d)
        (d / "workspace").mkdir(parents=True)
        (d / "verdict").mkdir(parents=True)
        (d / "prompt.md").write_text(textwrap.dedent(spec["prompt"]).strip() + "\n")
        for fn, content in spec["files"].items():
            (d / "workspace" / fn).write_text(content)
        # keep the workspace non-empty so copytree has something to do
        (d / "workspace" / "README.txt").write_text(
            "Working directory for this task. Produce the requested spreadsheet here.\n")
        (d / "verdict" / "test_compliance.py").write_text(
            HELPERS.lstrip() + "\n" + textwrap.dedent(spec["test"]).strip() + "\n")
        (d / "meta.json").write_text(json.dumps(
            {"skill": SKILL, "skill_marker": MARKER}, indent=2) + "\n")
        print(f"  built {name}")


if __name__ == "__main__":
    main()
