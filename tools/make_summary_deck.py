#!/usr/bin/env python3
"""Build the summary deck from the evaluation's facts.

Generated rather than hand-made so it stays in sync with results/EVALUATION.md and can be
regenerated when numbers change. Every figure here is also in that document.

Uses python-pptx directly. Applies the size-hierarchy and left-alignment rules the harness
itself measures: display 40pt, slide titles 30pt, body 14-16pt, body never centred.
"""
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


def slide_title(slide, title, kicker=None):
    if kicker:
        tb(slide, kicker.upper(), 0.7, 0.45, 11.9, 0.3, 11, color=MUTED, bold=True)
    tb(slide, title, 0.7, 0.75, 11.9, 0.8, 30, color=INK, bold=True)
    ln = slide.shapes.add_shape(1, Inches(0.7), Inches(1.62), Inches(1.1), Inches(0.05))
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
        tb(slide, label, (x1 + x2) / 2 - 0.75, (y1 + y2) / 2 - 0.28, 1.6, 0.25, 10,
           color=MUTED, align=PP_ALIGN.CENTER)
    return c


# ─────────────────────────────────────────────────────────── 1. title
s = prs.slides.add_slide(BLANK); bg(s, INK)
tb(s, "Benchmarking Claude Code", 0.9, 2.1, 11.5, 1.1, 46, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
tb(s, "Cost, skill effect and model selection — measured, priced, and where it\nsurprised us",
   0.9, 3.4, 11.0, 1.0, 20, color=ICE)
tb(s, "193 recorded repetitions  ·  4 models  ·  internal LiteLLM  ·  2026-09-09",
   0.9, 5.9, 11.0, 0.4, 13, color=RGBColor(0x9A, 0xB0, 0xD8))

# ─────────────────────────────────────────────────────────── 2. what this is
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

# ─────────────────────────────────────────────────────────── 3. terms
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Terms in use", "vocabulary")
tb(s, "These were conflated early in the work; they are kept strictly separate.",
   0.7, 1.95, 11.9, 0.3, 14, color=MUTED)
rows = [["term", "meaning"],
        ["Harness", "the whole apparatus: tasks + driver + verdict + Cortex"],
        ["Arm", "off = skill unavailable (control) · on = skill invoked · select = none named"],
        ["Cell", "one (task × arm × model), measured over n repetitions"],
        ["Compliance task", "ordinary request; hidden verdict checks a skill convention was followed"],
        ["Selection task", "names no skill; verdict is whether the model chose the right one"],
        ["Confound", "a repetition whose measurement is untrustworthy — reported, never averaged"],
        ["Cost per solved task", "median tokens ÷ pass rate — charges a model for its failures"]]
table(s, rows, 0.7, 2.45, 11.9, [2.6, 9.3], size=13)
tb(s, "‘workload-harness’ (hyphenated) is a proper noun for an unrelated upstream project — never used here as a common noun.",
   0.7, 5.35, 11.9, 0.3, 12, color=MUTED)

# ─────────────────────────────────────────────────────────── 4. setup diagram
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Benchmarking setup", "architecture")
box(s, "harness.py\ndriver · run lock", 0.7, 2.0, 2.3, 0.95, fill=INK,
    color=RGBColor(0xFF, 0xFF, 0xFF), bold=True, size=13)
box(s, "fresh workspace\ncopied per repetition", 0.7, 3.25, 2.3, 0.8, fill=RGBColor(0xFF, 0xFF, 0xFF), size=11)
box(s, "hidden verdict/\ninstalled AFTER exit", 0.7, 4.35, 2.3, 0.8, fill=RGBColor(0xFF, 0xFF, 0xFF), size=11)
box(s, "claude -p\nheadless child\nstream-json", 3.75, 2.0, 2.4, 1.35, fill=ICE, size=13, bold=True)
box(s, "clean child env\nHTTPS_PROXY · NODE_EXTRA_CA_CERTS\nCLAUDE_CONFIG_DIR · --model",
    3.4, 3.65, 3.1, 1.0, fill=RGBColor(0xFF, 0xFF, 0xFF), size=10)
box(s, "Cortex\nforward proxy + tls_bridge\ninference-parser", 7.0, 2.0, 2.7, 1.35, fill=ICE, size=12, bold=True)
box(s, "SSE /v1/events → disk\n(upstream TTL is 30 min)", 7.0, 3.65, 2.7, 0.8,
    fill=RGBColor(0xFF, 0xFF, 0xFF), size=10)
box(s, "LiteLLM\ngateway", 10.5, 2.0, 1.9, 0.95, fill=INK, color=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True)
box(s, "model", 10.5, 3.3, 1.9, 0.6, fill=RGBColor(0xFF, 0xFF, 0xFF), size=12)
arrow(s, 3.0, 2.47, 3.75, 2.47, label="spawn")
# the left-hand boxes are steps the driver performs; connect them or they read as floating
arrow(s, 1.85, 2.95, 1.85, 3.25)
arrow(s, 1.85, 4.05, 1.85, 4.35)
arrow(s, 6.15, 2.67, 7.0, 2.67, label="HTTPS")
arrow(s, 9.7, 2.47, 10.5, 2.47)
arrow(s, 11.45, 2.95, 11.45, 3.3)
arrow(s, 4.95, 3.35, 4.95, 3.65)
arrow(s, 8.35, 3.35, 8.35, 3.65)
box(s, "one NDJSON row per repetition   ·   whitelisted fields only, never raw prompts",
    0.7, 5.55, 11.7, 0.55, fill=RGBColor(0xFF, 0xFF, 0xFF), size=13, bold=True, color=INK)
tb(s, "Three measurement sources, because none can answer another’s question: the verdict says whether it worked,\n"
      "Cortex says what it cost, the transcript says which tools and skills actually ran.",
   0.7, 6.3, 11.9, 0.6, 13, color=MUTED)

# ─────────────────────────────────────────────────────────── 5. rationale
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

# ─────────────────────────────────────────────────────────── 6. task admission
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

# ─────────────────────────────────────────────────────────── 7. pricing
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Model pricing — internal LiteLLM", "rate card, 2026-09-09")
rows = [["benchmarked alias", "gateway entry", "input $/1M", "output $/1M", "vs sonnet-5"],
        ["claude-haiku-4-5-20251001", "aws/claude-haiku-4-5", "0.76", "3.80", "0.50×"],
        ["claude-sonnet-4-6", "aws/claude-sonnet-4-6", "2.28", "11.40", "1.50×"],
        ["claude-sonnet-5", "aws/claude-sonnet-5", "1.52", "7.60", "1.00×"],
        ["claude-opus-5", "aws/claude-opus-5", "3.80", "19.00", "2.50×"]]
table(s, rows, 0.7, 2.0, 11.9, [3.7, 3.2, 1.7, 1.8, 1.5], size=14,
      highlight={(3, 2): GOOD, (3, 3): GOOD, (4, 4): WARN})
tb(s, "sonnet-5 is priced at 2/3 of sonnet-4-6 — the single most consequential fact in the analysis.",
   0.7, 3.95, 11.9, 0.35, 16, color=GOOD, bold=True)
tb(s, "The cache caveat", 0.7, 4.5, 11.9, 0.3, 15, color=INK, bold=True)
tb(s, "The gateway publishes only Input and Output rates, but 81–97% of our prompt tokens are CACHE READS.\n"
      "  Scenario A — no discount: every prompt token at the Input rate (upper bound)\n"
      "  Scenario B — standard Anthropic/Bedrock convention: cacheRead ×0.10, cacheWrite ×1.25\n"
      "B lands ~4–5× below A. Which the gateway bills is UNVERIFIED (/model/info returns 403 for a non-admin key).\n"
      "The model ranking is identical under both, so the recommendation does not depend on resolving it.",
   0.7, 4.85, 11.9, 1.5, 13, color=BODY, spacing=3)

# ─────────────────────────────────────────────────────────── 8. finding: falsified
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

# ─────────────────────────────────────────────────────────── 9. finding: decomposition
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "One token term is a model constant; the other is not", "finding 2 · decomposition")
tb(s, "tokens/call ratio vs sonnet-4-6, across five structurally different cells",
   0.7, 1.95, 11.9, 0.3, 14, color=MUTED)
rows = [["model", "range", "spread", "reading"],
        ["haiku-4-5", "0.97 – 1.05", "0.07", "≈ same per-call context"],
        ["sonnet-5", "1.19 – 1.30", "0.11", "≈1.23× more per call"],
        ["opus-5", "0.89 – 0.97", "0.08", "≈0.90× — leaner per call"]]
table(s, rows, 0.7, 2.4, 11.9, [2.4, 2.6, 1.7, 5.2], size=14, highlight={(3, 3): GOOD})
tb(s, "Call count is NOT constant — 0.40–1.00× for haiku, 0.83–2.00× for opus-5 depending on the task.",
   0.7, 3.9, 11.9, 0.35, 15, color=WARN, bold=True)
box(s, "So decompose: the stable term is the MODEL, the variable term is the WORK.\n"
      "Reporting raw token totals conflates them.",
    0.7, 4.45, 11.7, 0.85, fill=RGBColor(0xFF, 0xFF, 0xFF), size=15, bold=True, color=INK)
tb(s, "Cache reads are 81–97% of prompt tokens in every cell — highest on sonnet-5 and opus-5. Reporting\n"
      "“input tokens” alone for this workload is meaningless.", 0.7, 5.5, 11.9, 0.6, 13, color=MUTED)

# ─────────────────────────────────────────────────────────── 10. finding: money
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

# ─────────────────────────────────────────────────────────── 11. finding: skill overhead
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Skill cost is a property of skill × model", "finding 4 · overhead")
tb(s, "skill-on ÷ skill-off tokens, same skill (xlsx), same tasks", 0.7, 1.95, 11.9, 0.3, 14, color=MUTED)
rows = [["task", "haiku-4-5", "sonnet-4-6", "sonnet-5", "opus-5"],
        ["xlsx-fin-colors", "2.88×", "1.50×", "2.01×", "0.93×"],
        ["xlsx-fin-font-clean", "2.37×", "1.08×" if False else "2.08×", "1.56×", "1.01×"]]
table(s, rows, 0.7, 2.4, 11.9, [3.9, 2.0, 2.0, 2.0, 2.0], size=15,
      highlight={(1, 1): WARN, (2, 1): WARN, (1, 4): GOOD, (2, 4): GOOD})
tb(s, "“What does this skill cost?” has no single answer.", 0.7, 3.65, 11.9, 0.35, 17, color=INK, bold=True)
tb(s, "opus-5 absorbs the skill for free (0.93× / 1.01×) — largely because it already works ~2× the calls on the\n"
      "OFF arm, so the guidance replaces effort rather than adding to it. On haiku the same skill costs ~2.5×.\n\n"
      "Caveat: this rests on ONE skill. Whether “free on opus-5” is an opus property or an xlsx property is\n"
      "currently indistinguishable — three more tasks on docx / pptx / pdf would separate them.",
   0.7, 4.1, 11.9, 1.6, 14, color=BODY, spacing=4)

# ─────────────────────────────────────────────────────────── 12. selection
s = prs.slides.add_slide(BLANK); bg(s, PAPER)
slide_title(s, "Skill selection is reliable", "finding 5 · selection")
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

# ─────────────────────────────────────────────────────────── 13. recommendation
s = prs.slides.add_slide(BLANK); bg(s, INK)
tb(s, "Model selection recommendation", 0.7, 0.6, 11.9, 0.7, 32,
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

# ─────────────────────────────────────────────────────────── 14. limitations
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

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"  wrote {OUT}  ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
