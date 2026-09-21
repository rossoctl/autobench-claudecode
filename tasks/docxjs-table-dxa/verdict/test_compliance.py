"""Table width in DXA on the docx-js path -- the same rule as the retired
docx-table-dxa task, now measured on the library the rule actually governs.

python-docx autofits and the assertion passed for free. A docx-js table with no explicit width
emits <w:tblW w:type="auto" w:w="100"/> -- neither pct nor dxa -- so the rule bites. Measured
against docx@9.7.1.
"""

import pathlib

from docx import Document


def _doc():
    here = pathlib.Path(__file__).parent
    found = [p for p in here.rglob("*.docx") if not p.name.startswith("~$")
             and "node_modules" not in p.parts]
    assert found, f"no .docx produced under {here}"
    found.sort(key=lambda p: len(p.parts))
    return Document(found[0])


def _paras(doc):
    return [p for p in doc.paragraphs if (p.text or "").strip()]


def _xml(el):
    return el._element.xml

def test_table_exists_with_expected_shape():
    doc = _doc()
    assert doc.tables, "no table in the document"
    t = doc.tables[0]
    assert len(t.rows) >= 4, f"expected a header plus three tiers, got {len(t.rows)} rows"
    assert len(t.columns) >= 3, f"expected three columns, got {len(t.columns)}"


def test_table_width_uses_dxa_not_percentage():
    """Skill rule: always set table width with DXA; PERCENTAGE breaks in Google Docs."""
    doc = _doc()
    xml = _xml(doc.tables[0])
    assert 'w:type="pct"' not in xml, \
        "table width uses PERCENTAGE (w:type=\"pct\"), which the skill forbids"
    assert 'w:type="dxa"' in xml, \
        f"table width is not set in DXA; no w:type=\"dxa\" found in tblPr/tblGrid"


def test_all_tiers_present():
    doc = _doc()
    blob = _xml(doc.tables[0]).lower()
    for tier in ("bronze", "silver", "gold"):
        assert tier in blob, f"tier {tier!r} missing from the table"
