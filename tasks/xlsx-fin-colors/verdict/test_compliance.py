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
