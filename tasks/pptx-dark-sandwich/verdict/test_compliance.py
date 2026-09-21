"""The "sandwich": dark title and closing slides, light content slides.

THE RULE. pptx/SKILL.md, in the design section: "Dark/light contrast: Dark backgrounds for
title + conclusion slides, light for content ("sandwich" structure)." Arbitrary -- a deck that
is light throughout is not wrong -- yet completely mechanical, which is what makes it a
compliance rule worth measuring rather than a matter of taste.

The skill offers an alternative in the same sentence ("Or commit to dark throughout for a
premium feel"), so ONLY the sandwich is scored here and an all-dark deck is a failure of this
task, not of the skill. That is a property of the task, stated so nobody later reads a 0/3 as
"the model ignored the skill".

WHY THE BACKGROUND IS RESOLVED AND NOT READ. `slide.background.fill.type` is BACKGROUND (i.e.
"inherited") for every slide of a stock python-pptx deck, and a pptxgenjs deck may instead ship
a full-bleed rectangle at the back of z-order. Both are what a viewer calls the background, so
the resolution order is: the slide's own fill, then a >= 95%-area shape behind everything else,
then the layout, then the master, then white -- which is what PowerPoint shows when nothing
declares a background at all. Theme colours are resolved through the master's clrMap into the
theme's clrScheme, because a deck that sets its title slide to BACKGROUND_2 has still set it.

NOT modelled: lumMod/lumOff tints, gradients and picture fills. A gradient or image background
reports no single colour and is reported as unresolved rather than guessed at.
"""
import pathlib
import xml.etree.ElementTree as ET

from pptx import Presentation
from pptx.dml.color import MSO_THEME_COLOR
from pptx.enum.dml import MSO_FILL
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

DARK_MAX = 0.45     # perceived luminance at or below this reads as a dark slide
LIGHT_MIN = 0.55    # at or above this, a light one. Between the two, neither.
FULL_BLEED = 0.95   # fraction of the slide a shape must cover to BE the background
WHITE = (255, 255, 255)

# MSO_THEME_COLOR -> the key the master's clrMap is indexed by.
THEME_KEYS = {
    MSO_THEME_COLOR.BACKGROUND_1: "bg1", MSO_THEME_COLOR.TEXT_1: "tx1",
    MSO_THEME_COLOR.BACKGROUND_2: "bg2", MSO_THEME_COLOR.TEXT_2: "tx2",
    MSO_THEME_COLOR.ACCENT_1: "accent1", MSO_THEME_COLOR.ACCENT_2: "accent2",
    MSO_THEME_COLOR.ACCENT_3: "accent3", MSO_THEME_COLOR.ACCENT_4: "accent4",
    MSO_THEME_COLOR.ACCENT_5: "accent5", MSO_THEME_COLOR.ACCENT_6: "accent6",
    MSO_THEME_COLOR.HYPERLINK: "hlink", MSO_THEME_COLOR.FOLLOWED_HYPERLINK: "folHlink",
    MSO_THEME_COLOR.DARK_1: "dk1", MSO_THEME_COLOR.LIGHT_1: "lt1",
    MSO_THEME_COLOR.DARK_2: "dk2", MSO_THEME_COLOR.LIGHT_2: "lt2",
}


def _deck():
    here = pathlib.Path(__file__).parent
    found = [p for p in here.rglob("*.pptx") if not p.name.startswith("~$")
             and "node_modules" not in p.parts]
    assert found, f"no .pptx produced under {here}"
    found.sort(key=lambda p: len(p.parts))
    return Presentation(found[0])


def _hex_rgb(value):
    s = str(value)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)) if len(s) == 6 else None


def _theme_rgb(master, key):
    """clrMap key (bg1, accent1, ...) -> RGB, via the master's own theme part.

    The theme is an opaque `Part` in python-pptx -- blob only, no element tree -- so it is
    parsed here rather than walked.
    """
    clr_map = master.element.find(qn("p:clrMap"))
    slot = clr_map.get(key) if clr_map is not None else key      # bg1 -> lt1, tx1 -> dk1, ...
    try:
        theme = master.part.part_related_by(RT.THEME)
    except KeyError:
        return None
    root = ET.fromstring(theme.blob)
    el = root.find(f"{A}themeElements/{A}clrScheme/{A}{slot}")
    if el is None:
        return None
    for child in el:
        # <a:srgbClr val="1F4E79"/> or <a:sysClr val="window" lastClr="FFFFFF"/>
        got = _hex_rgb(child.get("lastClr") or child.get("val") or "")
        if got:
            return got
    return None


def _fill_rgb(fill, master):
    """RGB of a SOLID fill, theme colours resolved. None for anything else."""
    try:
        if fill.type != MSO_FILL.SOLID:
            return None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    color = fill.fore_color
    try:
        if color.theme_color in THEME_KEYS:
            return _theme_rgb(master, THEME_KEYS[color.theme_color])
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    try:
        return _hex_rgb(color.rgb)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _backdrop_shape_rgb(slide, deck, master):
    """The fill of a full-bleed shape at the back of z-order -- how pptxgenjs and most HTML
    conversions express a background. Only the BACKMOST such shape can be the background."""
    area = deck.slide_width * deck.slide_height
    for sh in slide.shapes:                      # shapes[0] is furthest back
        if None in (sh.width, sh.height):
            continue
        if abs(sh.width) * abs(sh.height) < FULL_BLEED * area:
            continue
        got = _fill_rgb(getattr(sh, "fill", None), master) if hasattr(sh, "fill") else None
        return got                               # backmost full-bleed shape decides, or nothing
    return None


def _background_rgb(slide, deck):
    master = slide.slide_layout.slide_master
    for candidate in (_fill_rgb(slide.background.fill, master),
                      _backdrop_shape_rgb(slide, deck, master),
                      _fill_rgb(slide.slide_layout.background.fill, master),
                      _fill_rgb(master.background.fill, master)):
        if candidate:
            return candidate
    return WHITE          # nothing declares one: PowerPoint renders white, and so does a viewer


def _luminance(rgb):
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _text(sh):
    return (sh.text_frame.text or "").strip() if sh.has_text_frame else ""


def _slide_luminances():
    deck = _deck()
    return [(i, _background_rgb(s, deck), _luminance(_background_rgb(s, deck)))
            for i, s in enumerate(deck.slides, 1)]


# ------------------------------------------------------------------ structure guard

def test_deck_has_the_briefed_slides():
    """The sandwich is a claim about first/middle/last, so it says nothing until the deck has a
    first, a middle and a last -- and a two-slide deck would pass the dark half vacuously."""
    deck = _deck()
    n = len(deck.slides)
    assert n >= 4, f"a sandwich needs a title, content and a closing slide; got {n} slides"
    empty = [i for i, s in enumerate(deck.slides, 1)
             if not any(_text(sh) for sh in s.shapes)]
    assert not empty, f"slides with no text at all: {empty}"
    blob = " ".join(_text(sh) for s in deck.slides for sh in s.shapes).lower()
    for token in ("security", "privilege"):
        assert token in blob, f"the brief's content is missing: {token!r} not in the deck"


# ------------------------------------------------------------------ the rule

def test_title_and_closing_slides_are_dark():
    """Skill rule: "Dark backgrounds for title + conclusion slides"."""
    lums = _slide_luminances()
    ends = [lums[0], lums[-1]]
    bad = [(i, "#%02X%02X%02X" % rgb, round(lum, 2)) for i, rgb, lum in ends if lum > DARK_MAX]
    assert not bad, (
        f"the title and closing slides are not dark (perceived luminance > {DARK_MAX}): {bad}. "
        f"All slides: {[(i, round(l, 2)) for i, _, l in lums]}")


def test_content_slides_are_light():
    """The other half of the sandwich: without it an all-dark deck would score as compliant,
    and the skill offers all-dark as a DIFFERENT choice."""
    lums = _slide_luminances()
    middle = lums[1:-1]
    assert middle, "no content slides between the title and the close"
    bad = [(i, "#%02X%02X%02X" % rgb, round(lum, 2)) for i, rgb, lum in middle
           if lum < LIGHT_MIN]
    assert not bad, (
        f"content slides are not light (perceived luminance < {LIGHT_MIN}): {bad}. A deck that "
        f"is dark throughout is the skill's OTHER option, not this sandwich.")
