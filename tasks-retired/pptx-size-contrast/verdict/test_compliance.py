import pathlib
import statistics

import pytest
from pptx import Presentation
from pptx.enum.text import PP_ALIGN


def _deck():
    here = pathlib.Path(__file__).parent
    found = [p for p in here.rglob("*.pptx") if not p.name.startswith("~$")]
    assert found, f"no .pptx produced under {here}"
    found.sort(key=lambda p: len(p.parts))
    return Presentation(found[0])


# Deliberately placeholder-INDEPENDENT. slide.shapes.title is None whenever the deck is
# built from blank layouts with plain text boxes, which is what the skill's pptxgenjs path
# actually does -- an earlier version of these tests keyed off shapes.title and therefore
# failed a deck with textbook 58pt/34pt/16pt hierarchy. Measure the rule (is there a size
# hierarchy? is body text left-aligned?), never the mechanism used to build it.
def _runs(slide):
    """(size_pt, alignment, text) for every sized run on the slide."""
    out = []
    for sh in slide.shapes:
        if not (sh.has_text_frame and (sh.text_frame.text or "").strip()):
            continue
        for para in sh.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size is not None:
                    out.append((run.font.size.pt, para.alignment, run.text))
    return out


def _all_runs(deck):
    return [r for s in deck.slides for r in _runs(s)]

def test_has_display_sized_text():
    """Skill rule: titles need 36pt+ to stand out from 14-16pt body."""
    runs = _all_runs(_deck())
    assert runs, "no run in the deck has an explicit font size"
    biggest = max(r[0] for r in runs)
    assert biggest >= 36, f"largest text in the deck is {biggest}pt; the skill wants 36pt+"


def test_has_a_real_size_hierarchy():
    """Contrast, not just one big number: the bulk of the text must be much smaller."""
    runs = _all_runs(_deck())
    sizes = sorted(r[0] for r in runs)
    biggest, median = sizes[-1], statistics.median(sizes)
    assert biggest - median >= 16, (
        f"insufficient size contrast: largest {biggest}pt vs median {median}pt "
        f"(all sizes: {sizes})")


def test_three_slides():
    n = len(_deck().slides)
    assert n == 3, f"expected 3 slides, got {n}"
