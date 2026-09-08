#!/usr/bin/env python3
"""Phase-2 task set: docx and pptx compliance tasks.
NOTE on the pptx verdicts: an earlier version keyed off `slide.shapes.title`, which is
None whenever a deck is built from blank layouts with plain text boxes -- exactly what the
skill's pptxgenjs path does. That version failed a deck with textbook 58/34/16pt hierarchy,
i.e. it measured the MECHANISM (placeholders) rather than the RULE. The shipped verdicts in
tasks/*/verdict/ are placeholder-independent; regenerate with care.


Same rules as the xlsx set: the prompt is an ordinary request that never names a
convention, and the verdict is hidden in verdict/ so the agent cannot read the spec and
comply. Every assertion targets a rule the skill states explicitly, so a failure means
"did not follow the skill" rather than "wrote a bad document".

docx declares Bash(node*)/Bash(npm*): the skill mandates docx-js, and without those the
agent falls back to python-docx and we would measure the fallback instead of the skill.
"""
import json
import pathlib
import shutil
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent / "tasks"

DOCX_HELPERS = '''
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
'''

PPTX_HELPERS = '''
import pathlib

import pytest
from pptx import Presentation
from pptx.util import Pt


def _deck():
    here = pathlib.Path(__file__).parent
    found = [p for p in here.rglob("*.pptx") if not p.name.startswith("~$")]
    assert found, f"no .pptx produced under {here}"
    found.sort(key=lambda p: len(p.parts))
    return Presentation(found[0])


def _text_frames(slide):
    for sh in slide.shapes:
        if sh.has_text_frame and (sh.text_frame.text or "").strip():
            yield sh


def _sizes(shape):
    out = []
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            if run.font.size is not None:
                out.append(run.font.size.pt)
    return out
'''

TASKS = {}

# ----------------------------------------------------------------- docx: bullets
TASKS["docx-native-bullets"] = {
    "skill": "docx",
    "marker": "Never use unicode bullets",
    "tools": ["Bash(node*)", "Bash(npm*)", "Bash(soffice*)", "Bash(ls*)", "Bash(cat*)"],
    "helpers": DOCX_HELPERS,
    "prompt": """
        Write me a Word document called `onboarding.docx` for new joiners.

        It needs a short intro paragraph and then a list of the five things to do in
        week one: get a laptop, set up SSO, meet your buddy, read the team handbook,
        and ship a small change.

        Keep it to one page.
        """,
    "test": '''
BULLET_CHARS = ("\\u2022", "\\u00b7", "\\u25cf", "\\u25aa", "\\u2043", "-\\t")


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
    blob = "\\n".join(p.text.lower() for p in _paras(doc))
    for token in ("laptop", "sso", "buddy", "handbook", "ship"):
        assert token in blob, f"list item {token!r} missing from the document"
''',
}

# ----------------------------------------------------------------- docx: page size
TASKS["docx-us-letter"] = {
    "skill": "docx",
    "marker": "Set page size explicitly",
    "tools": ["Bash(node*)", "Bash(npm*)", "Bash(soffice*)", "Bash(ls*)", "Bash(cat*)"],
    "helpers": DOCX_HELPERS,
    "prompt": """
        Produce a Word document `memo.docx` — a one-page internal memo announcing that
        the office will be closed on 4 July.

        Address it to All Staff from the Facilities team, and mention that the building
        reopens the next working day.

        This is for our US offices and will be printed.
        """,
    "test": '''
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
    blob = "\\n".join(p.text.lower() for p in _paras(doc))
    assert "all staff" in blob, "memo is not addressed to All Staff"
    assert "july" in blob, "memo does not mention July"
''',
}

# ----------------------------------------------------------------- docx: table width
TASKS["docx-table-dxa"] = {
    "skill": "docx",
    "marker": "WidthType.PERCENTAGE",
    "tools": ["Bash(node*)", "Bash(npm*)", "Bash(soffice*)", "Bash(ls*)", "Bash(cat*)"],
    "helpers": DOCX_HELPERS,
    "prompt": """
        Create `rates.docx` containing a table of our support tiers.

        Three tiers — Bronze, Silver, Gold — with columns for tier name, monthly price
        (49, 149, 499 dollars) and response time (48 hours, 8 hours, 1 hour). Give the
        table a header row.

        Colleagues will open this in Google Docs as well as Word.
        """,
    "test": '''
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
    assert 'w:type="pct"' not in xml, \\
        "table width uses PERCENTAGE (w:type=\\"pct\\"), which the skill forbids"
    assert 'w:type="dxa"' in xml, \\
        f"table width is not set in DXA; no w:type=\\"dxa\\" found in tblPr/tblGrid"


def test_all_tiers_present():
    doc = _doc()
    blob = _xml(doc.tables[0]).lower()
    for tier in ("bronze", "silver", "gold"):
        assert tier in blob, f"tier {tier!r} missing from the table"
''',
}

# ----------------------------------------------------------------- pptx: size contrast
TASKS["pptx-size-contrast"] = {
    "skill": "pptx",
    "marker": "size contrast",
    "tools": ["Bash(node*)", "Bash(npm*)", "Bash(python*)",
               "Bash(soffice*)", "Bash(ls*)", "Bash(cat*)"],
    "helpers": PPTX_HELPERS,
    "prompt": """
        Build a three-slide deck `quarter.pptx` for an internal update.

        Slide one is the title: "Q3 Engineering Update". Slide two covers what shipped —
        the new billing flow, single sign-on, and a 40% cut in p95 latency. Slide three
        is what is next: mobile parity and an audit log.

        It gets shown on a projector in a big room.
        """,
    "test": '''
def test_titles_are_large_enough():
    """Skill rule: titles need 36pt+ to stand out from 14-16pt body."""
    deck = _deck()
    title_sizes = []
    for slide in deck.slides:
        if slide.shapes.title is not None and (slide.shapes.title.text or "").strip():
            title_sizes += _sizes(slide.shapes.title)
    assert title_sizes, "no explicit font size set on any slide title"
    assert max(title_sizes) >= 36, \\
        f"largest title is {max(title_sizes)}pt; the skill requires 36pt+"


def test_body_is_smaller_than_titles():
    deck = _deck()
    titles, bodies = [], []
    for slide in deck.slides:
        title = slide.shapes.title
        for sh in _text_frames(slide):
            (titles if sh is title else bodies).extend(_sizes(sh))
    assert titles and bodies, \\
        f"need both title and body sizes; got titles={titles} bodies={bodies}"
    assert max(titles) - max(bodies) >= 12, \\
        f"insufficient size contrast: titles {max(titles)}pt vs body {max(bodies)}pt"


def test_three_slides():
    assert len(_deck().slides) == 3, f"expected 3 slides, got {len(_deck().slides)}"
''',
}

# ----------------------------------------------------------------- pptx: alignment
TASKS["pptx-body-left-aligned"] = {
    "skill": "pptx",
    "marker": "Don't center body text",
    "tools": ["Bash(node*)", "Bash(npm*)", "Bash(python*)",
               "Bash(soffice*)", "Bash(ls*)", "Bash(cat*)"],
    "helpers": PPTX_HELPERS,
    "prompt": """
        Make a two-slide deck `risks.pptx`.

        Slide one: "Top Delivery Risks". Slide two lists the three risks with a sentence
        each — vendor SLA expiring in November, one remaining single-maintainer service,
        and migration work competing with the roadmap.

        Straightforward and readable.
        """,
    "test": '''
from pptx.enum.text import PP_ALIGN


def test_body_paragraphs_are_not_centered():
    """Skill rule: left-align paragraphs and lists; center only titles."""
    deck = _deck()
    centered = []
    for i, slide in enumerate(deck.slides, 1):
        title = slide.shapes.title
        for sh in _text_frames(slide):
            if sh is title:
                continue
            for para in sh.text_frame.paragraphs:
                if not (para.text or "").strip():
                    continue
                if para.alignment == PP_ALIGN.CENTER:
                    centered.append((i, para.text[:40]))
    assert not centered, f"body text centered on {centered}"


def test_risks_all_present():
    deck = _deck()
    blob = " ".join(sh.text_frame.text.lower()
                    for s in deck.slides for sh in _text_frames(s))
    for token in ("sla", "maintainer", "migration"):
        assert token in blob, f"risk {token!r} missing from the deck"
''',
}

# ----------------------------------------------------------------- pptx: not text-only
TASKS["pptx-not-text-only"] = {
    "skill": "pptx",
    "marker": "Don't create text-only slides",
    "tools": ["Bash(soffice*)", "Bash(ls*)", "Bash(cat*)", "Bash(python*)"],
    "helpers": PPTX_HELPERS,
    "prompt": """
        Put together a two-slide deck `adoption.pptx` showing that weekly active users
        grew 1,200 -> 1,850 -> 2,600 -> 3,400 over the last four quarters.

        Slide one is a title slide, slide two should get the growth across.

        It is for a leadership review.
        """,
    "test": '''
from pptx.enum.shapes import MSO_SHAPE_TYPE

VISUAL = {MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.TABLE,
          MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.FREEFORM, MSO_SHAPE_TYPE.GROUP}


def test_content_slide_is_not_text_only():
    """Skill rule: don't create text-only slides -- add charts/images/visual elements."""
    deck = _deck()
    per_slide = []
    for i, slide in enumerate(deck.slides, 1):
        visuals = [sh for sh in slide.shapes
                   if sh.shape_type in VISUAL or getattr(sh, "has_chart", False)]
        per_slide.append((i, len(visuals)))
    assert any(n > 0 for _, n in per_slide), \\
        f"every slide is text-only; visual shape counts per slide: {per_slide}"


def test_growth_numbers_present():
    deck = _deck()
    blob = " ".join(sh.text_frame.text for s in deck.slides for sh in _text_frames(s))
    blob = blob.replace(",", "")
    hits = [n for n in ("1200", "1850", "2600", "3400") if n in blob]
    assert len(hits) >= 2, f"growth figures largely missing; found {hits}"
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
        (d / "workspace" / "README.txt").write_text(
            "Working directory for this task. Produce the requested document here.\n")
        (d / "verdict" / "test_compliance.py").write_text(
            spec["helpers"].lstrip() + "\n" + textwrap.dedent(spec["test"]).strip() + "\n")
        (d / "meta.json").write_text(json.dumps({
            "skill": spec["skill"],
            "skill_marker": spec["marker"],
            "allowed_tools_extra": spec["tools"],
        }, indent=2) + "\n")
        print(f"  built {name:26} skill={spec['skill']}")


if __name__ == "__main__":
    main()
