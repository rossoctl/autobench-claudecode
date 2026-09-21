"""Arial 12pt body and black heading text -- scored library-independently.

THE RULE. docx/SKILL.md, in the "Styles (Override Built-in Headings)" section: "Use Arial as
the default font (universally supported). Keep titles black for readability." It is the one
checkable docx convention that is NOT a docx-js footgun correction, which is what makes it
measurable on either library -- and why the same task can later be run against a variant that
hoists the rule out of the JavaScript snippet it is currently buried in.

WHY THE XML AND NOT THE python-docx API. `style.font.name` returns None when the style defers
to the theme, which is the normal case, so the convenient API cannot tell "unset" from
"inherited Cambria". Effective formatting is resolved here the way Word resolves it: run rPr ->
paragraph style chain (basedOn) -> docDefaults -> theme. Both libraries are then scored by one
rule rather than by two approximations of it.

MEASURED DEFAULTS, both non-compliant, which is what makes the task a discriminator:
  python-docx  body = theme minorHAnsi, and its bundled theme's minor latin face is Cambria,
               at w:sz 22 = 11pt; Heading 1 = 365F91, Heading 2 = 4F81BD, Title = 17365D
  docx-js      <w:docDefaults><w:rPrDefault/></w:docDefaults> and no theme part at all, so
               nothing declares a default font and the effective face is whatever Word
               happens to use -- which is not Arial either
"""
import pathlib
import xml.etree.ElementTree as ET
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

BODY_FONT = "arial"
BODY_HALF_POINTS = 24          # 12pt, as the skill's own snippet writes it
BLACK = {"000000", "auto"}     # w:val="auto" IS automatic-black in Word
HEADING_PREFIXES = ("heading", "title", "subtitle")


def _zip():
    here = pathlib.Path(__file__).parent
    found = [p for p in here.rglob("*.docx") if not p.name.startswith("~$")
             and "node_modules" not in p.parts]
    assert found, f"no .docx produced under {here}"
    found.sort(key=lambda p: len(p.parts))
    return zipfile.ZipFile(found[0])


def _part(z, name):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _theme(z):
    """major/minor latin faces, or {} when the document ships no theme part."""
    for name in z.namelist():
        if name.startswith("word/theme/"):
            t = _part(z, name)
            out = {}
            for kind in ("major", "minor"):
                el = t.find(f".//{A}{kind}Font/{A}latin") if t is not None else None
                if el is not None and el.get("typeface"):
                    out[kind] = el.get("typeface")
            return out
    return {}


def _styles(z):
    """styleId -> (name, basedOn, rPr element). The chain Word walks for inheritance."""
    root, out = _part(z, "word/styles.xml"), {}
    if root is None:
        return out
    for st in root.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        nm = st.find(f"{W}name")
        based = st.find(f"{W}basedOn")
        out[sid] = (nm.get(f"{W}val") if nm is not None else sid,
                    based.get(f"{W}val") if based is not None else None,
                    st.find(f"{W}rPr"))
    return out


def _default_pstyle(z):
    """The paragraph style used when a <w:p> carries no <w:pStyle> -- normally "Normal".

    Not a detail: python-docx writes body paragraphs with NO pStyle, so a document that sets
    Arial on the Normal style would look unstyled if the chain started at docDefaults, and a
    compliant artifact would be scored as a failure. That is the pptx-size-contrast defect in
    a different costume.
    """
    root = _part(z, "word/styles.xml")
    for st in (root.findall(f"{W}style") if root is not None else []):
        if st.get(f"{W}type") == "paragraph" and st.get(f"{W}default") in ("1", "true", "on"):
            return st.get(f"{W}styleId")
    return "Normal"


def _doc_default_rpr(z):
    root = _part(z, "word/styles.xml")
    return root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr") if root is not None else None


def _chain(p, styles, z):
    """Every rPr that can supply a property for this paragraph's runs, nearest first."""
    out = []
    ppr = p.find(f"{W}pPr")
    rpr_in_ppr = ppr.find(f"{W}rPr") if ppr is not None else None
    if rpr_in_ppr is not None:
        out.append(rpr_in_ppr)
    sid = None
    if ppr is not None:
        ps = ppr.find(f"{W}pStyle")
        sid = ps.get(f"{W}val") if ps is not None else None
    sid = sid or _default_pstyle(z)
    seen = set()
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        _, based, rpr = styles[sid]
        if rpr is not None:
            out.append(rpr)
        sid = based
    dd = _doc_default_rpr(z)
    if dd is not None:
        out.append(dd)
    return out


def _font(rprs, theme):
    for rpr in rprs:
        f = rpr.find(f"{W}rFonts")
        if f is None:
            continue
        if f.get(f"{W}ascii"):
            return f.get(f"{W}ascii")
        th = f.get(f"{W}asciiTheme")
        if th:
            # minorHAnsi -> the theme's minor latin face; majorHAnsi -> its major one.
            return theme.get("minor" if th.startswith("minor") else "major")
    return None


def _size(rprs):
    for rpr in rprs:
        s = rpr.find(f"{W}sz")
        if s is not None and s.get(f"{W}val"):
            return int(float(s.get(f"{W}val")))
    return None


def _color(rprs):
    for rpr in rprs:
        c = rpr.find(f"{W}color")
        if c is not None and c.get(f"{W}val"):
            return c.get(f"{W}val").lower()
    # Nothing in the chain sets a colour: Word renders automatic, i.e. black. Compliant.
    return "auto"


def _paragraphs(z):
    """(style_name, text, effective rPr chain) per non-empty paragraph."""
    doc, styles, theme = _part(z, "word/document.xml"), _styles(z), _theme(z)
    out = []
    for p in doc.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        if not text.strip():
            continue
        ppr = p.find(f"{W}pPr")
        ps = ppr.find(f"{W}pStyle") if ppr is not None else None
        sid = ps.get(f"{W}val") if ps is not None else None
        name = styles.get(sid, (sid or "Normal", None, None))[0] or ""
        runs = [r.find(f"{W}rPr") for r in p.findall(f"{W}r")]
        out.append((name, text, [x for x in runs if x is not None],
                    _chain(p, styles, z), theme))
    return out


def _is_heading(style_name):
    return str(style_name).strip().lower().startswith(HEADING_PREFIXES)


def _effective(run_rprs, chain, theme, what):
    """Run-level first, then the paragraph/style/docDefaults chain -- as Word resolves it."""
    rprs = run_rprs + chain
    return {"font": lambda: _font(rprs, theme),
            "size": lambda: _size(rprs),
            "color": lambda: _color(rprs)}[what]()


# ------------------------------------------------------------------ structure guard

def test_document_has_a_title_and_headings():
    """Without this the two rules below could pass vacuously on a document with no headings at
    all -- a verdict that passes an empty artifact measures nothing."""
    paras = _paragraphs(_zip())
    headings = [t for n, t, *_ in paras if _is_heading(n)]
    assert len(headings) >= 2, (
        f"expected a title and at least one section heading; styled headings found: {headings} "
        f"(styles seen: {sorted({n for n, *_ in paras})})")
    blob = " ".join(t.lower() for _, t, *_ in paras)
    for token in ("retention", "q3"):
        assert token in blob, f"the brief's content is missing: {token!r} not in the document"


# ------------------------------------------------------------------ the two rules

def test_body_text_is_arial_12pt():
    """Skill rule: "Use Arial as the default font (universally supported)", 12pt."""
    bad = []
    for name, text, runs, chain, theme in _paragraphs(_zip()):
        if _is_heading(name):
            continue
        for run in (runs or [None]):
            rr = [run] if run is not None else []
            font = _effective(rr, chain, theme, "font")
            size = _effective(rr, chain, theme, "size")
            if (font or "").lower() != BODY_FONT or size != BODY_HALF_POINTS:
                bad.append((text[:40], font, f"{(size or 0) / 2:g}pt"))
    assert not bad, (
        f"body text is not Arial 12pt (effective, resolved through style -> docDefaults -> "
        f"theme): {bad[:4]}")


def test_heading_text_is_black():
    """Skill rule: "Keep titles black for readability." Resolved, so an inherited built-in
    heading colour (python-docx Heading 1 = 365F91) counts as a violation, which is the point:
    black is not what either library gives you by default."""
    bad = []
    for name, text, runs, chain, theme in _paragraphs(_zip()):
        if not _is_heading(name):
            continue
        for run in (runs or [None]):
            rr = [run] if run is not None else []
            col = _effective(rr, chain, theme, "color")
            if col not in BLACK:
                bad.append((name, text[:40], col))
    assert not bad, f"heading text is not black: {bad[:4]}"
