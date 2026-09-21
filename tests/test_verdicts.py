"""Prove each compliance verdict discriminates -- against fixtures, before spending anything.

WHY THIS FILE EXISTS. `pptx-size-contrast` keyed on `slide.shapes.title`, which is None for a
deck built from blank layouts -- the path the skill's own pptxgenjs guidance takes. It therefore
scored a textbook-compliant deck as 0/3 and reported "the skill does not help" for three paid
repetitions before anyone read the verdict rather than the result. A verdict is an instrument and
gets calibrated like one: it must FAIL the artifact an unaided run produces and PASS a compliant
one, and both halves have to be shown, because a verdict that fails everything looks exactly like
a discriminating one from the pass rate alone.

The fixtures are built with the same library the task forces, so "what an unaided run produces"
is measured rather than imagined. That is how the three docx rules were found to be
path-dependent in the first place: python-docx satisfies all of them by default, so the retired
docx-* tasks could not discriminate at any number of repetitions.

No LLM calls, no cost.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import textwrap

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent


def has_node(pkg):
    return harness.node_apparatus()["node_packages"].get(pkg) is not None


def build_with_docxjs(tmp_path, script, out_name="memo.docx"):
    """Run a docx-js snippet and return the .docx it wrote."""
    d = tmp_path / "gen"
    d.mkdir(parents=True, exist_ok=True)
    harness.link_node_modules(str(d), ["docx"])
    (d / "gen.mjs").write_text(textwrap.dedent(script))
    r = subprocess.run(["node", "gen.mjs"], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"fixture generator failed:\n{r.stdout}\n{r.stderr}"
    return d / out_name


def run_verdict(task_id, artifact, tmp_path):
    """Score an artifact exactly as the harness does: the hidden verdict, in its own dir.

    The verdict resolves its artifact relative to its OWN file, so it has to be copied beside
    the fixture rather than pointed at it -- the same arrangement `install_verdict` makes.
    """
    d = tmp_path / f"verdict-{task_id}"
    shutil.copytree(ROOT / "tasks" / task_id / "verdict", d)
    shutil.copy2(artifact, d / artifact.name)
    r = subprocess.run([harness.VENV_PY, "-m", "pytest", "-q"], cwd=d,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout + r.stderr)


def discriminates(task_id, tmp_path, default_js, compliant_js, out_name):
    """The two halves of calibration, asserted together."""
    rc_d, out_d = run_verdict(task_id, build_with_docxjs(
        tmp_path / "d", default_js, out_name), tmp_path / "d")
    assert rc_d != 0, (
        f"{task_id}: the verdict PASSES the artifact an unaided docx-js run produces, so the "
        f"task cannot measure the skill at any n:\n{out_d[-800:]}")
    rc_c, out_c = run_verdict(task_id, build_with_docxjs(
        tmp_path / "c", compliant_js, out_name), tmp_path / "c")
    assert rc_c == 0, (
        f"{task_id}: the verdict FAILS a compliant artifact, so a passing run would be scored "
        f"as a failure -- the pptx-size-contrast defect:\n{out_c[-800:]}")


pytestmark = pytest.mark.skipif(not has_node("docx"),
                                reason="docx not installed globally (npm install -g docx)")

PRELUDE = """
    import { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
             TableLayoutType, WidthType, AlignmentType, LevelFormat, convertInchesToTwip }
        from "docx";
    import fs from "fs";
"""

MEMO = ('new Paragraph("MEMO to All Staff from Facilities"), '
        'new Paragraph("The office is closed on 4 July and the building reopens the next '
        'working day.")')


def test_docxjs_us_letter_discriminates(tmp_path):
    """docx-js defaults to A4 (11906 x 16838 twips); the skill's rule says set Letter."""
    discriminates(
        "docxjs-us-letter", tmp_path,
        PRELUDE + f"""
        const doc = new Document({{ sections: [{{ children: [{MEMO}] }}] }});
        fs.writeFileSync("memo.docx", await Packer.toBuffer(doc));
        """,
        PRELUDE + f"""
        const doc = new Document({{ sections: [{{
          properties: {{ page: {{ size: {{ width: 12240, height: 15840 }} }} }},
          children: [{MEMO}] }}] }});
        fs.writeFileSync("memo.docx", await Packer.toBuffer(doc));
        """,
        "memo.docx")


ITEMS = ["get a laptop", "set up SSO", "meet your buddy", "read the team handbook",
         "ship a small change"]


def test_docxjs_native_bullets_discriminates(tmp_path):
    """docx-js emits plain paragraphs unless a numbering definition is configured, so the
    typed-bullet footgun is reachable -- which it is not on the python-docx path."""
    typed = ", ".join(f'new Paragraph("\\u2022 {t}")' for t in ITEMS)
    native = ", ".join(f'new Paragraph({{ text: "{t}", numbering: '
                       f'{{ reference: "todo", level: 0 }} }})' for t in ITEMS)
    discriminates(
        "docxjs-native-bullets", tmp_path,
        PRELUDE + f"""
        const doc = new Document({{ sections: [{{ children: [
          new Paragraph("Welcome. Here is week one."), {typed} ] }}] }});
        fs.writeFileSync("onboarding.docx", await Packer.toBuffer(doc));
        """,
        PRELUDE + f"""
        const doc = new Document({{
          numbering: {{ config: [{{ reference: "todo", levels: [{{ level: 0,
            format: LevelFormat.BULLET, text: "\\u2022", alignment: AlignmentType.LEFT }}] }}] }},
          sections: [{{ children: [
            new Paragraph("Welcome. Here is week one."), {native} ] }}] }});
        fs.writeFileSync("onboarding.docx", await Packer.toBuffer(doc));
        """,
        "onboarding.docx")


TIERS = [("Bronze", "49", "48 hours"), ("Silver", "149", "8 hours"), ("Gold", "499", "1 hour")]


def _rows(width_js):
    head = ["Tier", "Monthly price", "Response time"]
    body = [head] + [list(t) for t in TIERS]
    rows = ", ".join(
        "new TableRow({ children: [" + ", ".join(
            f'new TableCell({{ children: [new Paragraph("{c}")] }})' for c in r) + "] })"
        for r in body)
    return f"new Table({{ rows: [{rows}]{width_js} }})"


def test_docxjs_table_dxa_discriminates(tmp_path):
    """A docx-js table with no explicit width emits w:tblW w:type="auto", and PERCENTAGE emits
    w:type="pct" -- the thing the skill forbids because it breaks in Google Docs."""
    discriminates(
        "docxjs-table-dxa", tmp_path,
        PRELUDE + f"""
        const doc = new Document({{ sections: [{{ children: [
          new Paragraph("Support tiers"),
          {_rows(', width: { size: 100, type: WidthType.PERCENTAGE }')} ] }}] }});
        fs.writeFileSync("rates.docx", await Packer.toBuffer(doc));
        """,
        PRELUDE + f"""
        const doc = new Document({{ sections: [{{ children: [
          new Paragraph("Support tiers"),
          {_rows(', layout: TableLayoutType.FIXED, '
                 'width: { size: 9360, type: WidthType.DXA }')} ] }}] }});
        fs.writeFileSync("rates.docx", await Packer.toBuffer(doc));
        """,
        "rates.docx")


# Calibrated by MEASUREMENT instead of by fixture, which is the stronger of the two: across the
# 193 published repetitions both of these have OFF rows that fail and ON rows that pass, on more
# than one model. That is the same two-sided proof a fixture gives, taken from the real artifact
# distribution rather than from one hand-built document. Not a backlog entry.
EMPIRICALLY_CALIBRATED = {"xlsx-fin-colors", "xlsx-fin-font-clean"}


def test_every_hidden_verdict_task_is_calibrated_here():
    """A task whose verdict was never shown to discriminate is a task whose pass rate means
    nothing -- and the failure is invisible, because "0/3" reads the same either way."""
    calibrated = {n for n in globals() if n.startswith("test_")}
    missing = []
    for d in sorted((ROOT / "tasks").iterdir()):
        meta = d / "meta.json"
        if not (d / "verdict").is_dir() or not meta.is_file():
            continue
        if not json.loads(meta.read_text()).get("skill") or d.name in EMPIRICALLY_CALIBRATED:
            continue
        slug = d.name.replace("-", "_")
        if not any(slug in n for n in calibrated):
            missing.append(d.name)
    assert not missing, (
        f"no fixture calibration for {missing}. Add one here before spending on the arm: the "
        f"pptx-size-contrast defect cost three paid repetitions and produced a wrong finding.")
