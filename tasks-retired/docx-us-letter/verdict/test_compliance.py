import pathlib

import pytest
from docx import Document
from docx.shared import Twips


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

LETTER_W, LETTER_H = 12240, 15840  # US Letter in DXA/twips, per the skill


def test_page_size_is_us_letter_not_a4():
    """Skill rule: docx-js defaults to A4; set US Letter (12240 x 15840 DXA) explicitly."""
    doc = _doc()
    sec = doc.sections[0]
    w = sec.page_width.twips if sec.page_width is not None else None
    h = sec.page_height.twips if sec.page_height is not None else None
    assert (w, h) == (LETTER_W, LETTER_H), (
        f"page is {w}x{h} DXA, expected US Letter {LETTER_W}x{LETTER_H} "
        "(A4 would be 11906x16838)")


def test_memo_addressed_and_dated():
    doc = _doc()
    blob = "\n".join(p.text.lower() for p in _paras(doc))
    assert "all staff" in blob, "memo is not addressed to All Staff"
    assert "july" in blob, "memo does not mention July"
