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

BULLET_CHARS = ("\u2022", "\u00b7", "\u25cf", "\u25aa", "\u2043", "-\t")


def test_no_literal_bullet_characters_in_text():
    """Skill rule: never manually insert bullet characters."""
    doc = _doc()
    offenders = [p.text[:60] for p in _paras(doc)
                 if any(ch in p.text for ch in BULLET_CHARS)]
    assert not offenders, f"literal bullet characters typed into text: {offenders}"


def test_list_items_use_real_numbering():
    """Skill rule: use a numbering config (LevelFormat.BULLET), which lands as <w:numPr>."""
    doc = _doc()
    paras = _paras(doc)
    numbered = [p for p in paras if "numPr" in _xml(p)]
    styled = [p for p in paras
              if (p.style is not None and "list" in (p.style.name or "").lower())]
    assert numbered or styled, (
        "no paragraph carries real list numbering (<w:numPr>) or a List style; "
        f"styles seen: {sorted({p.style.name for p in paras if p.style})}")


def test_all_five_items_present():
    doc = _doc()
    blob = "\n".join(p.text.lower() for p in _paras(doc))
    for token in ("laptop", "sso", "buddy", "handbook", "ship"):
        assert token in blob, f"list item {token!r} missing from the document"
