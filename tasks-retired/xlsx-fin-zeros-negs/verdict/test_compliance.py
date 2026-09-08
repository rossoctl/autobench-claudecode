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

def test_negatives_shown_in_parentheses():
    """Skill rule: negative numbers use parentheses, not a minus sign."""
    ws = _book().active
    fmts = _fmts(ws)
    assert any("(" in f and ")" in f for f in fmts), \
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
