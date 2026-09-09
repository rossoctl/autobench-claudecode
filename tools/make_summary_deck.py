#!/usr/bin/env python3
"""Build the summary deck from the evaluation's facts.

Generated rather than hand-made so it stays in sync with results/EVALUATION.md and can be
regenerated when numbers change. Every figure here is also in that document.

Uses python-pptx directly. Applies the size-hierarchy and left-alignment rules the harness
itself measures: display 40pt, slide titles 30pt, body 14-16pt, body never centred.
"""
import datetime as dt
import pathlib

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

OUT = pathlib.Path(__file__).resolve().parent.parent / "results" / "autobench-claudecode-summary.pptx"

INK = RGBColor(0x1E, 0x27, 0x61)      # navy, dominant
ICE = RGBColor(0xCA, 0xDC, 0xFC)      # supporting
PAPER = RGBColor(0xFA, 0xF9, 0xF5)
BODY = RGBColor(0x2B, 0x2B, 0x2B)
MUTED = RGBColor(0x6B, 0x6B, 0x6B)
GOOD = RGBColor(0x2C, 0x5F, 0x2D)
WARN = RGBColor(0xB8, 0x50, 0x42)
FONT = "Arial"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
DARK_SLIDES = set()   # 1-based indices with a dark background


def bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def tb(slide, text, l, t, w, h, size, *, color=BODY, bold=False, align=PP_ALIGN.LEFT,
       font=FONT, spacing=None, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = font
        r.font.color.rgb = color
    return box


CURRENT = {"sec": None}


def section(num, name):
    """Declare the section that subsequent slides belong to."""
    CURRENT["sec"] = (num, name)


def slide_title(slide, title, kicker=None):
    """Kicker + title + accent rule.

    At 30pt across 11.9in roughly 52 characters fit on one line. A longer title wraps and
    the accent rule then strikes through the second line, so the rule is pushed down.
    """
    sec = CURRENT["sec"]
    prefix = f"{sec[0]} · {sec[1].upper()}" if sec else ""
    line = (f"{prefix}  ·  {kicker.upper()}" if (prefix and kicker)
            else (prefix or (kicker or "").upper()))
    if line:
        tb(slide, line, 0.7, 0.45, 11.9, 0.3, 11, color=MUTED, bold=True)
    tb(slide, title, 0.7, 0.75, 11.9, 0.8, 30, color=INK, bold=True)
    accent_y = 1.62 if len(title) <= 52 else 2.08
    ln = slide.shapes.add_shape(1, Inches(0.7), Inches(accent_y), Inches(1.1), Inches(0.05))
    ln.fill.solid(); ln.fill.fore_color.rgb = ICE; ln.line.fill.background()
    ln.shadow.inherit = False


def table(slide, rows, l, t, w, col_w, size=13, header=True, highlight=None):
    """rows: list of lists. highlight: {(r,c): RGBColor}"""
    nrows, ncols = len(rows), len(rows[0])
    shp = slide.shapes.add_table(nrows, ncols, Inches(l), Inches(t), Inches(w),
                                 Inches(0.34 * nrows)).table
    for j, cw in enumerate(col_w):
        shp.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        shp.rows[i].height = Inches(0.32)
        for j, val in enumerate(row):
            c = shp.cell(i, j)
            c.text = str(val)
            c.margin_left = c.margin_right = Inches(0.07)
            c.margin_top = c.margin_bottom = Inches(0.02)
            c.fill.solid()
            c.fill.fore_color.rgb = INK if (header and i == 0) else (
                PAPER if i % 2 else RGBColor(0xFF, 0xFF, 0xFF))
            p = c.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.RIGHT
            for r in p.runs:
                r.font.size = Pt(size)
                r.font.name = FONT
                r.font.bold = (header and i == 0)
                r.font.color.rgb = (RGBColor(0xFF, 0xFF, 0xFF) if header and i == 0
                                    else (highlight or {}).get((i, j), BODY))
    return shp


def box(slide, text, l, t, w, h, *, fill=RGBColor(0xFF, 0xFF, 0xFF), edge=INK,
        size=12, bold=False, color=BODY):
    s = slide.shapes.add_shape(5, Inches(l), Inches(t), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = fill
    s.line.color.rgb = edge; s.line.width = Pt(1.25)
    s.shadow.inherit = False
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.name = FONT; r.font.bold = bold
        r.font.color.rgb = color
    return s


def arrow(slide, x1, y1, x2, y2, *, color=INK, label=None):
    c = slide.shapes.add_connector(2, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color; c.line.width = Pt(1.75)
    if label:
        w = min(1.5, max(0.55, abs(x2 - x1) - 0.06)) if abs(x2 - x1) > 0.2 else 1.2
        tb(slide, label, (x1 + x2) / 2 - w / 2, (y1 + y2) / 2 - 0.3, w, 0.25, 10,
           color=MUTED, align=PP_ALIGN.CENTER)
    return c


# ─────────────────────────────────────────────────────────── 1. title
s = prs.slides.add_slide(BLANK); bg(s, INK); DARK_SLIDES.add(len(prs.slides._sldIdLst))
tb(s, "Benchmarking Claude Code", 0.9, 2.1, 11.5, 1.1, 46, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
tb(s, "Cost, skill effect and model selection — measured, priced, and where it\nsurprised us",
   0.9, 3.4, 11.0, 1.0, 20, color=ICE)
tb(s, "193 recorded repetitions  ·  4 models  ·  internal LiteLLM",
   0.9, 5.75, 11.0, 0.4, 13, color=RGBColor(0x9A, 0xB0, 0xD8))
tb(s, f"Last modified {dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
   0.9, 6.2, 11.0, 0.35, 12, color=RGBColor(0x7A, 0x8F, 0xC0))

# ─────────────────────────────────────────────────────────── 2. table of contents
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Contents", "table of contents")
# Two columns; section numbers match the kickers on each slide.
SECTIONS = [
    ("1 · Setup and method", [
        ("3", "What a benchmark is made of"),
        ("4", "What is being measured"),
        ("5", "Terms in use"),
        ("6", "Benchmarking setup — architecture"),
        ("7", "Why this shape — rationale"),
        ("8", "How a task earns its place"),
    ]),
    ("2 · Pricing", [
        ("9", "Model pricing — internal LiteLLM rate card"),
    ]),
    ("3 · Findings", [
        ("10", "A prediction of ours that was falsified"),
        ("11", "Two factors drive token cost"),
        ("12", "Money reverses the token conclusion"),
        ("13", "Token-efficiency is not cost-efficiency"),
        ("14", "Skill cost is a property of skill × model"),
        ("15", "Skill selection is reliable"),
    ]),
    ("4 · Conclusion", [
        ("16", "Model selection recommendation"),
        ("17", "Limitations, stated plainly"),
    ]),
]
COLS = [(0.7, SECTIONS[:2]), (6.9, SECTIONS[2:])]
for x, groups in COLS:
    y = 2.05
    for sec_name, items in groups:
        tb(s, sec_name.upper(), x, y, 5.4, 0.3, 12, color=INK, bold=True)
        y += 0.4
        for num, label in items:
            tb(s, num, x, y, 0.5, 0.3, 14, color=ICE, bold=True, align=PP_ALIGN.RIGHT)
            tb(s, label, x + 0.7, y, 4.9, 0.3, 14, color=BODY)
            y += 0.38
        y += 0.3
tb(s, "Every figure in this deck also appears in results/EVALUATION.md, which carries the full detail\n"
      "and the reproduction steps.", 0.7, 6.4, 11.9, 0.6, 12, color=MUTED)

section(1, "Setup and method")

# ─────────────────────────────────────────── 3. anatomy of a benchmark
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "What a benchmark is made of", "anatomy")
tb(s, "Six parts. Drop any one and you have a demo, a load generator, or a number nobody can defend.",
   0.7, 1.95, 11.9, 0.3, 15, color=INK)

PARTS = [
    ("TASKS",
     "A defined unit of work, reproducible from a\nfixed definition into a fresh workspace.",
     "tasks/<id>/prompt.md + workspace/"),
    ("PROGRAMMATIC EVALUATOR",
     "A verdict that is a command's exit code, not a\nmodel's opinion. This is what makes it a benchmark.",
     "hidden verdict/ → pytest -q"),
    ("CONTROLS",
     "An arm that isolates the one variable under\nstudy, so an effect can be attributed to it.",
     "off / on / select arms"),
    ("REPETITION",
     "The subject is non-deterministic, so one run is\nan anecdote. Report medians and spread.",
     "n per cell, CV reported"),
    ("ATTRIBUTION",
     "Evidence of what ACTUALLY ran, so a result from\nsomething other than the thing tested is caught.",
     "stream-json transcript → confounds"),
    ("OBSERVABILITY",
     "What it cost: tokens by cache tier, latency, the\nreal model served. Measured, not estimated.",
     "Cortex supplies this"),
]
for i, (name, why, how) in enumerate(PARTS):
    col, row = i % 3, i // 3
    lx = 0.7 + col * 4.05
    ly = 2.45 + row * 2.0
    is_obs = name == "OBSERVABILITY"
    box(s, "", lx, ly, 3.8, 1.8, fill=(ICE if is_obs else RGBColor(0xFF, 0xFF, 0xFF)))
    tb(s, name, lx + 0.2, ly + 0.13, 3.4, 0.3, 12, color=INK, bold=True)
    tb(s, why, lx + 0.2, ly + 0.55, 3.4, 0.75, 11, color=BODY)
    tb(s, how, lx + 0.2, ly + 1.42, 3.4, 0.3, 10.5, color=MUTED, bold=True)

box(s, "Cortex is a COMPONENT of the harness — it supplies the observability data. It is not the benchmark, and it\n"
      "cannot score anything: it sees bytes on the wire, never whether the work was correct.",
    0.7, 6.5, 11.2, 0.68, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True)

# ─────────────────────────────────────────────────────────── 4. what this is
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "What is being measured", "scope")
tb(s, "The subject under test is the Claude Code agent itself — not a model in isolation.",
   0.7, 1.95, 11.9, 0.4, 16, color=INK)
rows = [["", ""],
        ["Agent under test", "Claude Code CLI 2.1.257, headless (claude -p)"],
        ["Task", "one prompt + a fresh workspace; 1 repetition = 1 invocation"],
        ["Verdict", "a command's exit code — pytest -q. No LLM judge."],
        ["Measured on the wire", "tokens + cache tiers via Cortex forward proxy"],
        ["Skill measured", "xlsx (2 discriminating tasks) + a no-skill control"],
        ["Models priced", "haiku-4-5, sonnet-4-6, sonnet-5, opus-5"]]
rows[0] = ["dimension", "value"]
table(s, rows, 0.7, 2.5, 11.9, [3.0, 8.9], size=14)
tb(s, "No LLM judge is the load-bearing choice: without a programmatic verdict this is a\n"
      "load generator, not a benchmark.", 0.7, 5.6, 11.9, 0.7, 14, color=WARN, bold=True)

# ─────────────────────────────────────────────────────────── 4. terms
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Terms in use", "vocabulary")
tb(s, "These were conflated early in the work; they are kept strictly separate.",
   0.7, 1.95, 11.9, 0.3, 14, color=MUTED)
rows = [["term", "meaning"],
        ["Harness", "the whole apparatus: tasks + driver + verdict + Cortex"],
        ["Arm", "off = skill unavailable (control) · on = skill invoked · select = none named"],
        ["Cell", "one (task × arm × model), measured over n repetitions — e.g. xlsx-fin-colors / ON / sonnet-5, n=5"],
        ["Task / repetition", "ONE headless `claude -p` invocation in a fresh workspace"],
        ["LLM call", "ONE /v1/chat/completions on the wire. A task makes SEVERAL — 5 to 24 here"],
        ["Compliance task", "ordinary request; hidden verdict checks a skill convention was followed"],
        ["Selection task", "names no skill; verdict is whether the model chose the right one"],
        ["Confound", "a repetition whose measurement is untrustworthy — reported, never averaged"],
        ["Token-efficiency", "tokens consumed per SOLVED task — what the context window and rate limits see"],
        ["Cost-efficiency", "dollars per SOLVED task — token-efficiency weighted by that model's unit price"],
        ["Cost per solved task", "median ÷ pass rate, so a model is charged for its failures"]]
table(s, rows, 0.7, 2.4, 11.9, [2.6, 9.3], size=11.5)
tb(s, "‘workload-harness’ (hyphenated) is a proper noun for an unrelated upstream project — never used here as a common noun.",
   0.7, 5.35, 11.9, 0.3, 12, color=MUTED)

# ─────────────────────────────────────────────────────────── 5. setup diagram
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Benchmarking setup", "architecture")
box(s, "harness.py\ndriver · run lock", 0.7, 2.0, 2.3, 0.95, fill=INK,
    color=RGBColor(0xFF, 0xFF, 0xFF), bold=True, size=13)
box(s, "fresh workspace\ncopied per repetition", 0.7, 3.25, 2.3, 0.8, fill=RGBColor(0xFF, 0xFF, 0xFF), size=11)
box(s, "hidden verdict/\ninstalled AFTER exit", 0.7, 4.35, 2.3, 0.8, fill=RGBColor(0xFF, 0xFF, 0xFF), size=11)
box(s, "claude -p\nheadless child\nstream-json", 3.75, 2.0, 2.4, 1.35, fill=ICE, size=13, bold=True)
box(s, "clean child env\nHTTPS_PROXY · NODE_EXTRA_CA_CERTS\nCLAUDE_CONFIG_DIR · --model",
    3.4, 3.65, 3.1, 1.0, fill=RGBColor(0xFF, 0xFF, 0xFF), size=10)
box(s, "Cortex (local service)\nforward proxy + tls_bridge\ndecrypts, then inference-parser",
    7.0, 2.0, 2.7, 1.35, fill=ICE, size=11, bold=True)
box(s, "Server-Sent Events stream\nGET /v1/events → disk\n(store is in-memory, 30-min TTL)",
    7.0, 3.65, 2.7, 0.85, fill=RGBColor(0xFF, 0xFF, 0xFF), size=9.5)
box(s, "LiteLLM\ngateway", 10.5, 2.0, 1.9, 0.95, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True)
box(s, "model", 10.5, 3.3, 1.9, 0.6, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12)
arrow(s, 3.0, 2.47, 3.75, 2.47, label="spawn")
# the left-hand boxes are steps the driver performs; connect them or they read as floating
arrow(s, 1.85, 2.95, 1.85, 3.25)
arrow(s, 1.85, 4.05, 1.85, 4.35)
arrow(s, 6.15, 2.67, 7.0, 2.67, label="CONNECT")
arrow(s, 9.7, 2.47, 10.5, 2.47, label="HTTPS")
arrow(s, 11.45, 2.95, 11.45, 3.3)
arrow(s, 4.95, 3.35, 4.95, 3.65)
arrow(s, 8.35, 3.35, 8.35, 3.65)
box(s, "one NDJSON row per repetition   ·   whitelisted fields only, never raw prompts",
    0.7, 5.55, 11.7, 0.55, fill=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True, color=INK)
tb(s, "Three measurement sources, because none can answer another’s question: the verdict says whether it worked, Cortex says what\n"
      "it cost, the transcript says which tools and skills actually ran.\n"
      "Transport: HTTPS_PROXY is named “https” but its value is http://127.0.0.1:47600 — the hop to the local Cortex service is plaintext\n"
      "HTTP CONNECT on loopback. tls_bridge then terminates TLS with its own CA (hence NODE_EXTRA_CA_CERTS) so the request can be\n"
      "parsed, and Cortex makes the real HTTPS connection outbound to the gateway.",
   0.7, 6.15, 12.2, 1.0, 11.5, color=MUTED, spacing=1)

# ─────────────────────────────────────────────────────────── 6. rationale
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Why this shape", "rationale")
rows = [["decision", "rationale — each one was measured, not assumed"],
        ["Per-invocation isolation", "operator settings.json never touched; one Cortex sees ALL machine traffic, so global wiring would let interactive typing pollute a run"],
        ["Forward proxy + tls_bridge", "the reverse role records events but leaves plugins=[] — no tokens. Only forward+bridge dispatches the parser"],
        ["CLAUDE_CONFIG_DIR, not HOME", "HOME is not the skill lookup root; four curated-HOME arms reported an identical 60 slash commands"],
        ["Pin --model, verify on wire", "the model actually used came from an ambient env var disagreeing with settings.json"],
        ["Exclusive run lock", "Cortex correlates by TIME WINDOW on a shared proxy, so overlapping runs interleave — observed, then made impossible"],
        ["Whitelisted artefacts", "Cortex events carry full prompts and completions on an unauthenticated API"]]
table(s, rows, 0.7, 2.0, 11.9, [3.2, 8.7], size=12)

# ─────────────────────────────────────────────────────────── 7. task admission
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "How a task earns its place", "methodology")
tb(s, "9 of the first 11 tasks written were discarded. A discarded task is a result.",
   0.7, 1.95, 11.9, 0.35, 16, color=WARN, bold=True)
box(s, "RULE 1 — tamper-proof, not merely green\n\n"
      "Pass requires exit 0 AND every test file\nbyte-identical to what shipped.\n\n"
      "Deleting the test, or rewriting it to assert\nthe bug, also makes pytest green.",
    0.7, 2.5, 5.6, 1.9, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12)
box(s, "RULE 2 — pre-screen on the OFF arm\n\n"
      "A task the agent already passes WITHOUT\nthe skill is not measuring the skill.\n\n"
      "Hidden verdicts: a visible test is a spec —\nthe agent reads it and both arms pass.",
    6.75, 2.5, 5.6, 1.9, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12)
tb(s, "The reusable heuristic", 0.7, 4.6, 11.9, 0.3, 15, color=INK, bold=True)
rows = [["rule kind", "example", "outcome"],
        ["Arbitrary / house-specific", "xlsx: blue text = hardcoded input", "DISCRIMINATES"],
        ["Objectively better practice", "docx: real bullets · pptx: size hierarchy", "passes unaided"],
        ["Path-dependent", "docx rules correct footguns in the library the skill itself mandates", "cannot discriminate"]]
table(s, rows, 0.7, 5.0, 11.9, [3.1, 6.4, 2.4], size=12,
      highlight={(1, 2): GOOD, (2, 2): WARN, (3, 2): WARN})

section(2, "Pricing")

# ─────────────────────────────────────────────────── 9. pricing
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Model pricing — internal LiteLLM", "rate card")
rows = [["benchmarked alias", "gateway entry", "input $/1M", "output $/1M", "vs sonnet-5"],
        ["claude-haiku-4-5-20251001", "aws/claude-haiku-4-5", "0.76", "3.80", "0.50×"],
        ["claude-sonnet-4-6", "aws/claude-sonnet-4-6", "2.28", "11.40", "1.50×"],
        ["claude-sonnet-5", "aws/claude-sonnet-5", "1.52", "7.60", "1.00×"],
        ["claude-opus-5", "aws/claude-opus-5", "3.80", "19.00", "2.50×"]]
table(s, rows, 0.7, 2.0, 11.9, [3.7, 3.2, 1.7, 1.8, 1.5], size=14,
      highlight={(3, 2): GOOD, (3, 3): GOOD, (4, 4): WARN})
tb(s, "Transcribed by hand from the gateway model pages on 2026-09-09. That page needs interactive internal web\n"
      "authorization and fills itself by script, so no automated pull is possible or attempted.",
   0.7, 3.75, 11.9, 0.55, 12, color=MUTED)
tb(s, "sonnet-5 is priced at 2/3 of sonnet-4-6 — the single most consequential fact in the analysis.",
   0.7, 4.35, 11.9, 0.35, 16, color=GOOD, bold=True)
tb(s, "The cache caveat", 0.7, 4.85, 11.9, 0.3, 15, color=INK, bold=True)
tb(s, "The gateway publishes only Input and Output rates, but 81–97% of our prompt tokens are CACHE READS.\n"
      "  Scenario A — no discount: every prompt token at the Input rate (upper bound)\n"
      "  Scenario B — standard Anthropic/Bedrock convention: cacheRead ×0.10, cacheWrite ×1.25\n"
      "B lands ~4–5× below A. Which the gateway actually bills is UNVERIFIED.\n"
      "The model ranking is identical under both, so the recommendation does not depend on resolving it.",
   0.7, 5.2, 11.9, 1.5, 12.5, color=BODY, spacing=2)

section(3, "Findings")

# ────────────────────────────────────── 10. finding: falsified
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "A prediction of ours that was falsified", "finding 1 · pass rate")
tb(s, "We argued a compliance task cannot rank models: the OFF arm is pinned at 0 by the pre-screen and the ON\n"
      "arm at 100 because the skill states the answer. That held only for the two mid-tier models we had tested.",
   0.7, 1.95, 11.9, 0.7, 14, color=BODY)
rows = [["model", "xlsx-fin-colors  OFF → ON", "xlsx-fin-font-clean  OFF → ON"],
        ["haiku-4-5", "0.00 → 1.00", "0.00 → 0.40   ← fails even when TOLD"],
        ["sonnet-4-6", "0.00 → 1.00", "0.00 → 1.00"],
        ["sonnet-5", "0.00 → 1.00", "0.00 → 1.00"],
        ["opus-5", "0.20 → 1.00   ← knows it UNAIDED", "0.00 → 1.00"]]
table(s, rows, 0.7, 2.85, 11.9, [2.4, 4.8, 4.7], size=14,
      highlight={(1, 2): WARN, (4, 1): GOOD})
box(s, "“The measure is saturated” is a claim about the models you happened to test —\nnot a claim about the task.",
    0.7, 4.9, 11.7, 0.95, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=16, bold=True)

# ─────────────────────────────────────────────────────────── 10. finding: decomposition
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Two factors drive token cost", "finding 2 · decomposition")
box(s, "tokens per task   =   tokens per LLM CALL   ×   LLM calls per task\n"
      "                              (a MODEL property)              (a TASK property)",
    0.7, 1.88, 11.7, 0.78, fill=RGBColor(0xFF, 0xFF, 0xFF), size=15, bold=True, color=INK)
tb(s, "Factor 1 — tokens per LLM call: ratio vs sonnet-4-6, across five structurally different cells",
   0.7, 2.8, 11.9, 0.3, 14, color=MUTED)
rows = [["model", "range", "spread", "reading"],
        ["haiku-4-5", "0.97 – 1.05", "0.07", "≈ same context per LLM call"],
        ["sonnet-5", "1.19 – 1.30", "0.11", "≈1.23× more per LLM call"],
        ["opus-5", "0.89 – 0.97", "0.08", "≈0.90× — leaner per LLM call"]]
table(s, rows, 0.7, 3.2, 11.9, [2.4, 2.6, 1.7, 5.2], size=14, highlight={(3, 3): GOOD})
tb(s, "Factor 2 — LLM calls per task: NOT constant. 0.40–1.00× for haiku, 0.83–2.00× for opus-5, by task.",
   0.7, 4.7, 11.9, 0.35, 15, color=WARN, bold=True)
box(s, "One TASK is one `claude -p` run and makes SEVERAL LLM calls (5–24 observed), each re-sending the\n"
      "growing conversation. A model has a stable appetite per LLM call — how many calls the job needs is a\n"
      "separate matter. A raw token total multiplies the two and hides both.",
    0.7, 5.12, 11.7, 0.95, fill=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True, color=INK)
tb(s, "Cache reads are 81–97% of prompt tokens in every cell — highest on sonnet-5 and opus-5. Reporting\n"
      "“input tokens” alone for this workload is meaningless.", 0.7, 6.15, 11.9, 0.6, 13, color=MUTED)

# ─────────────────────────────────────────────────────────── 11. finding: money
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Money reverses the token conclusion", "finding 3 · cost per solved task")
tb(s, "$ per SOLVED task (scenario B). Cost per solved = median tokens ÷ pass rate, so failures are charged.",
   0.7, 1.9, 11.9, 0.3, 14, color=MUTED)
rows = [["task", "haiku-4-5", "sonnet-4-6", "sonnet-5", "opus-5"],
        ["xlsx-fin-colors (ON)", "0.0386", "0.1590", "0.1678", "0.2719"],
        ["xlsx-fin-font-clean (ON)", "0.1075", "0.1873", "0.1332", "0.2486"],
        ["cortex-pyfix-001 (no skill)", "0.0313", "0.0837", "0.0588", "0.1030"]]
table(s, rows, 0.7, 2.35, 11.9, [3.9, 2.0, 2.0, 2.0, 2.0], size=14,
      highlight={(1, 1): GOOD, (2, 1): GOOD, (3, 1): GOOD,
                 (1, 4): WARN, (2, 4): WARN, (3, 4): WARN})
box(s, "opus-5 used the FEWEST tokens on two of three cells —\nand is the MOST EXPENSIVE on all three.",
    0.7, 4.05, 5.6, 0.9, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=14, bold=True)
box(s, "sonnet-5 uses MORE tokens than sonnet-4-6\nyet costs LESS, at 2/3 the unit price.",
    6.75, 4.05, 5.6, 0.9, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=14, bold=True)
tb(s, "Same cells under scenario A (no cache discount) — ordering identical throughout, so the conclusion does not\n"
      "depend on the unverified cache assumption:", 0.7, 5.1, 11.9, 0.55, 13, color=MUTED)
rows_a = [["task", "haiku-4-5", "sonnet-4-6", "sonnet-5", "opus-5"],
          ["xlsx-fin-colors", "0.1409", "0.5916", "0.9080", "1.1625"],
          ["xlsx-fin-font-clean", "0.3364", "0.8462", "0.7035", "1.1259"],
          ["cortex-pyfix-001", "0.1597", "0.4567", "0.3113", "0.5649"]]
table(s, rows_a, 0.7, 5.7, 11.9, [3.9, 2.0, 2.0, 2.0, 2.0], size=12,
      highlight={(1, 1): GOOD, (2, 1): GOOD, (3, 1): GOOD,
                 (1, 4): WARN, (2, 4): WARN, (3, 4): WARN})
tb(s, "haiku's 0.1075 already charges it for a 0.40 pass rate — it is cheapest even after paying for its failures.",
   0.7, 3.7, 11.9, 0.3, 12, color=WARN)

# ──────────────────────── 13. token-efficiency vs cost-efficiency
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Token-efficiency is not cost-efficiency", "finding 4 · two different questions")
rows = [["", "token-efficiency", "cost-efficiency"],
        ["measures", "tokens per SOLVED task", "dollars per SOLVED task"],
        ["binding when", "context window, rate limits, latency", "you are paying the bill"],
        ["driven by", "how much context and how many calls", "the same, weighted by unit price"]]
table(s, rows, 0.7, 1.95, 11.9, [2.3, 4.8, 4.8], size=13)
tb(s, "They diverge because unit price spans 5× (haiku $0.76 → opus-5 $3.80 per 1M input), which swamps the\n"
      "~2× spread in token counts. On cortex-pyfix-001 the two rankings are EXACTLY INVERTED:",
   0.7, 3.5, 11.9, 0.55, 13, color=BODY)
rows2 = [["model", "tokens/solved task", "rank", "$/solved task", "rank"],
         ["opus-5", "144,834", "1st", "0.1030", "4th"],
         ["sonnet-4-6", "196,634", "2nd", "0.0842", "3rd"],
         ["sonnet-5", "200,732", "3rd", "0.0588", "2nd"],
         ["haiku-4-5", "204,034", "4th", "0.0313", "1st"]]
table(s, rows2, 0.7, 4.15, 11.9, [3.1, 2.6, 1.6, 2.6, 1.6], size=13,
      highlight={(1, 2): GOOD, (1, 4): WARN, (4, 2): WARN, (4, 4): GOOD})
box(s, "opus-5 is the MOST token-efficient and the LEAST cost-efficient model tested.\n"
      "Quoting one number and calling it “efficiency” picks the answer by accident.",
    0.7, 5.95, 11.2, 0.8, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=14, bold=True)

# ─────────────────────────────────────────────────────────── 12. finding: skill overhead
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Skill cost is a property of skill × model", "finding 5 · overhead")
tb(s, "skill-on ÷ skill-off, same skill (xlsx), same task, same model. Tokens AND dollars — they differ,\n"
      "because the input/output/cache mix shifts between arms even at a fixed unit price.",
   0.7, 1.9, 11.9, 0.55, 13, color=MUTED)
rows = [["task / measure", "haiku-4-5", "sonnet-4-6", "sonnet-5", "opus-5"],
        ["xlsx-fin-colors — tokens", "2.88×", "1.50×", "2.01×", "0.93×"],
        ["xlsx-fin-colors — dollars", "1.97×", "1.33×", "1.88×", "1.06×"],
        ["xlsx-fin-font-clean — tokens", "2.37×", "2.08×", "1.56×", "1.01×"],
        ["xlsx-fin-font-clean — dollars", "2.24×", "1.71×", "1.41×", "1.08×"]]
table(s, rows, 0.7, 2.6, 11.9, [3.9, 2.0, 2.0, 2.0, 2.0], size=13,
      highlight={(1, 1): WARN, (2, 1): WARN, (3, 1): WARN, (4, 1): WARN,
                 (1, 4): GOOD, (2, 4): GOOD, (3, 4): GOOD, (4, 4): GOOD})
tb(s, "“What does this skill cost?” has no single answer.", 0.7, 4.4, 11.9, 0.35, 17, color=INK, bold=True)
tb(s, "On opus-5 the skill adds only 6–8% in dollars; on haiku it roughly doubles the bill. Opus-5 barely notices it\n"
      "because it already works ~2× the calls WITHOUT the skill (10 vs 8 on colors), so the guidance replaces\n"
      "exploration rather than adding to it. That is why its token ratio can dip below 1.0.\n\n"
      "Caveat: this rests on ONE skill. Whether the effect belongs to opus-5 or to xlsx is currently\n"
      "indistinguishable — three more tasks on docx / pptx / pdf would separate them.",
   0.7, 4.85, 11.9, 1.8, 13, color=BODY, spacing=3)

# ─────────────────────────────────────────────────────────── 13. selection
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Skill selection is reliable", "finding 6 · selection")
tb(s, "All four candidate skills present, prompt names none, verdict read from the transcript.\n"
      "sonnet-4-6, n=3 per task — 12/12 correct, 0 confounded.",
   0.7, 1.95, 11.9, 0.6, 15, color=BODY)
rows = [["task", "cue strength", "expected", "fired"],
        ["select-spreadsheet", "names the artifact", "xlsx", "xlsx ×3"],
        ["select-deck", "names the artifact", "pptx", "pptx ×3"],
        ["select-implicit-sheet", "never says “spreadsheet”", "xlsx", "xlsx ×3"],
        ["select-none", "plain bugfix", "nothing", "nothing ×3"]]
table(s, rows, 0.7, 2.75, 11.9, [3.4, 3.6, 2.4, 2.5], size=14,
      highlight={(3, 3): GOOD, (4, 3): GOOD})
tb(s, "A negative case is mandatory: measuring only true positives rewards a model that fires a skill on\n"
      "everything. Consequence — these four are now too easy to discriminate; extending needs ambiguous prompts.",
   0.7, 4.5, 11.9, 0.7, 13, color=MUTED)
box(s, "Only here is the transcript authoritative: a MODEL-SELECTED skill is a real Skill tool call,\n"
      "whereas an explicit /skill-name is expanded client-side and never appears in the transcript at all.",
    0.7, 5.35, 11.7, 0.95, fill=RGBColor(0xFF, 0xFF, 0xFF), size=13, color=INK)

section(4, "Conclusion")

# ─────────────────────────── 14. recommendation
s = prs.slides.add_slide(BLANK); bg(s, INK); DARK_SLIDES.add(len(prs.slides._sldIdLst))
tb(s, "4 · CONCLUSION  ·  RECOMMENDATION", 0.7, 0.42, 11.9, 0.3, 11, color=ICE, bold=True)
tb(s, "Model selection recommendation", 0.7, 0.75, 11.9, 0.7, 30,
   color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
tb(s, "on the benchmark evidence, for skill-driven document work", 0.7, 1.35, 11.9, 0.35, 14, color=ICE)
box(s, "ADOPT AS DEFAULT\n\nclaude-sonnet-5\n\n100% pass on every task, and cheaper\n"
      "than sonnet-4-6 in 2 of 3 cells — 29%\non font-clean, 30% on the canary —\n"
      "despite using MORE tokens.\n2/3 unit price absorbs 1.23×/call.",
    0.7, 2.0, 3.7, 2.85, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12, color=BODY)
box(s, "USE WHERE RETRIES ARE OK\n\nclaude-haiku-4-5\n\nCheapest in every cell by 2–4×\nand fastest (14–39s vs 59–78s).\n"
      "But passed the harder task only\n40% of the time WITH the skill.\nNot for first-attempt correctness.",
    4.8, 2.0, 3.7, 2.85, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12, color=BODY)
box(s, "NOT INDICATED HERE\n\nclaude-opus-5\n\nMost expensive in all three cells\n(1.6–2.1× sonnet-5), no pass-rate\n"
      "advantage. Genuinely the most\ntoken-efficient and the only model\nto solve a task unaided — may earn\nits premium on harder work.",
    8.9, 2.0, 3.7, 2.85, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12, color=BODY)
tb(s, "Confidence: the pass-rate and cost orderings hold across BOTH pricing scenarios, and tokens/call holds across five\n"
      "independent cells. Absolute dollar figures are indicative — n=5, and cache billing is unverified.",
   0.7, 5.1, 11.9, 0.7, 13, color=ICE)

# ─────────────────────────────────────────────────────────── 15. limitations
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Limitations, stated plainly", "what would change the conclusion")
rows = [["limitation", "consequence"],
        ["One skill (xlsx)", "every skill-specific conclusion is xlsx-specific; “free on opus-5” may be an xlsx property"],
        ["n = 5 per cell, some CV to 0.85", "tokens/call constants are solid (5 cells agree); individual dollar figures are indicative"],
        ["Cache billing unverified", "largest single uncertainty — 4–5× on ABSOLUTE cost, but changes no ranking"],
        ["Two tasks, one narrow genre", "financial-spreadsheet formatting. Not a general coding benchmark"],
        ["aws/ vs bare alias pricing", "assumed identical; unprovable with a non-admin key"],
        ["Wall-clock not load-controlled", "gateway-dependent; treat as indicative only"]]
table(s, rows, 0.7, 2.0, 11.9, [3.9, 8.0], size=13)
tb(s, "If the gateway does NOT discount cache reads, absolute costs rise ~4–5× and cache-heavy agentic use becomes far\n"
      "more expensive in aggregate — the ranking survives, but budget planning changes materially. If harder tasks were\n"
      "added, haiku’s reliability gap would likely widen and opus-5 might start earning its premium.",
   0.7, 4.5, 11.9, 1.0, 13, color=BODY)
tb(s, "Full detail, every figure and the reproduction steps: results/EVALUATION.md",
   0.7, 6.2, 11.9, 0.3, 13, color=INK, bold=True)

# ── page numbers on every slide. Stamped last so it survives any reordering, and it
# reads the real slide count rather than a hardcoded total.
for idx, sl in enumerate(prs.slides, 1):
    dark = idx in DARK_SLIDES
    tb(sl, str(idx), 12.1, 6.95, 0.5, 0.3, 11,
       color=(RGBColor(0x9A, 0xB0, 0xD8) if dark else MUTED), align=PP_ALIGN.RIGHT)

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"  wrote {OUT}  ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
