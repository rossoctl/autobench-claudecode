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
    assert only in PROFESSIONAL, \
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
    assert len(formulas) >= 2, \
        f"expected the saving and the ratio to be formulas; found {len(formulas)}"
