"""US Letter on the docx-js path -- the same rule as the retired docx-us-letter task,
now measured on the library the rule actually governs.

That task was discarded because the unaided agent reaches for python-docx, whose default
template IS US Letter (7772400 x 10058400 EMU), so the assertion could not discriminate at any
number of repetitions. Forcing docx-js restores the discriminator: a default docx-js document
measures 11906 x 16838 twips, i.e. A4. Measured, not assumed, against docx@9.7.1.
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
