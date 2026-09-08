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

def test_currency_cells_use_thousands_currency_format():
    ws = _book().active
    fmts = _fmts(ws)
    assert any("$" in f and "#,##0" in f for f in fmts), \
        f"no currency cell formatted like $#,##0; formats seen: {sorted(set(fmts))}"


def test_percentage_uses_one_decimal():
    ws = _book().active
    pct = [f for f in _fmts(ws) if "%" in f]
    assert pct, f"no percent-formatted cell; formats seen: {sorted(set(_fmts(ws)))}"
    assert any("0.0%" in f for f in pct), \
        f"margin should default to 0.0% (one decimal); percent formats: {pct}"


def test_multiple_formatted_with_x_suffix():
    ws = _book().active
    fmts = _fmts(ws)
    assert any("x" in f.lower() and "0.0" in f for f in fmts), \
        f"EV/EBITDA multiple should be formatted 0.0x; formats seen: {sorted(set(fmts))}"
