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
    assert not hardcoded, \
        f"growth rate hardcoded into formulas at {hardcoded} instead of referencing a cell"


def test_projection_formulas_reference_other_cells():
    ws = _book().active
    formulas = [c for c in _cells(ws) if _is_formula(c)]
    referencing = [c for c in formulas if any(ch.isdigit() for ch in c.value)
                   and any(ch.isalpha() for ch in c.value)]
    assert referencing, f"formulas do not reference cells: {[c.value for c in formulas]}"
