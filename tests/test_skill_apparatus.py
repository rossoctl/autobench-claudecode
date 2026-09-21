"""Tests for the SKILL as apparatus -- the treatment, pinned and diffable.

WHY THIS FILE EXISTS. On the ON arm the skill text is not context, it is the independent
variable, and `harness.assemble_skill` copies it out of ~/.claude/skills at run time. Until
`skill_variant`/`skill_sha`/`skill_files` existed, an upstream skill update between two runs
would move a pass rate with no model involved and leave nothing in the data to show it -- the
same defect the venv had before .python-version, on the half of the apparatus that matters more.

Two audiences again, same split as test_apparatus.py: the manifest conformance test here is
STRICT, because a contributor running pytest is about to add rows to a frozen grid, while
`doctor` only WARNs for a consumer who wants a number from whatever they have installed.
"""
import inspect
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "skills" / "MANIFEST.json"


def tree(tmp_path, files, name="t"):
    d = tmp_path / name
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


# --------------------------------------------------------------- the digest

def test_digest_is_content_sensitive(tmp_path):
    a = tree(tmp_path, {"SKILL.md": "use Arial\n"}, "a")
    b = tree(tmp_path, {"SKILL.md": "use Calibri\n"}, "b")
    assert harness.skill_tree_sha(a) != harness.skill_tree_sha(b)


def test_digest_covers_filenames_not_only_bytes(tmp_path):
    """A skill is resolved by FILENAME: pptx/SKILL.md says "read pptxgenjs.md for full
    details", so a rename changes what the agent can reach with every byte intact."""
    a = tree(tmp_path, {"pptxgenjs.md": "x\n", "SKILL.md": "see pptxgenjs.md\n"}, "a")
    b = tree(tmp_path, {"pptxgen.md": "x\n", "SKILL.md": "see pptxgenjs.md\n"}, "b")
    assert harness.skill_tree_sha(a) != harness.skill_tree_sha(b)


def test_digest_does_not_depend_on_write_order(tmp_path):
    """Two trees with the same content must agree, or the field records nothing but the order
    the filesystem happened to hand back."""
    a = tree(tmp_path, {"SKILL.md": "x\n", "scripts/go.py": "y\n"}, "a")
    b = tree(tmp_path, {"scripts/go.py": "y\n", "SKILL.md": "x\n"}, "b")
    assert harness.skill_tree_sha(a) == harness.skill_tree_sha(b)


# --------------------------------------------------------------- the recorded fields

def test_no_skill_records_none_not_a_hash_of_nothing(tmp_path):
    """The OFF arm's skills dir is empty and sha256 of nothing is a real hexdigest -- which in
    a row would read as "some skill was present". None cannot be misread."""
    (tmp_path / "skills").mkdir()
    ap = harness.skill_apparatus(str(tmp_path))
    assert ap == {"skill_variant": None, "skill_sha": None, "skill_files": 0}


def test_it_digests_what_the_child_got_not_what_was_asked_for(tmp_path):
    """One field then covers the empty OFF dir, a selection task's four candidates and any
    overlay -- and it is the only version still checkable after the fact."""
    d = tmp_path / "skills"
    (d / "xlsx").mkdir(parents=True)
    (d / "xlsx" / "SKILL.md").write_text("hello\n")
    ap = harness.skill_apparatus(str(tmp_path), "v2")
    assert ap["skill_files"] == 1
    assert ap["skill_variant"] == "v2"
    assert ap["skill_sha"] == harness.skill_tree_sha(d)


def test_default_variant_is_named_not_null(tmp_path):
    """"as-installed" is a claim about the treatment; null would be indistinguishable from a
    row written before the field existed."""
    d = tmp_path / "skills" / "xlsx"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("hello\n")
    assert harness.skill_apparatus(str(tmp_path))["skill_variant"] == "as-installed"


def test_run_rep_persists_them():
    """The defect this guards already happened once with the result event: a function that
    computes the right thing and a row that never carries it."""
    src = inspect.getsource(harness.run_rep)
    assert "**skill_apparatus(" in src, (
        "run_rep no longer records the skill -- an upstream skill update becomes "
        "indistinguishable from a model regression")


def test_the_fields_carry_digests_not_prose():
    """The skills are third-party and licensed against copies leaving the Services; `out/` is
    gitignored but NDJSON rows are the thing we publish summaries of."""
    d = harness.SKILLS_ROOT / "xlsx"
    if not d.is_dir():
        pytest.skip("xlsx skill not installed")
    blob = json.dumps({"skill_sha": harness.skill_tree_sha(d)})
    assert "SKILL.md" not in blob and "/Users/" not in blob


# --------------------------------------------------------------- variant recipes

def install(tmp_path, monkeypatch, files, variants=None):
    """Point harness at a fake ~/.claude/skills and a fake repo skills/ dir."""
    root = tree(tmp_path, files, "installed")
    monkeypatch.setattr(harness, "SKILLS_ROOT", root)
    monkeypatch.setattr(harness, "VARIANTS", tmp_path / "variants")
    for name, contents in (variants or {}).items():
        tree(tmp_path / "variants", contents, name)
    return root


def sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


BASE = "# Skill\n\nNEVER use accent lines.\n"


def test_as_installed_is_a_verbatim_copy(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE})
    applied = harness.assemble_skill("s", tmp_path / "dest")
    assert applied == []
    assert (tmp_path / "dest" / "SKILL.md").read_text() == BASE


def test_a_recipe_prepends_our_own_prose(tmp_path, monkeypatch):
    """A recipe rather than a forked SKILL.md: the skills are Anthropic's and licensed against
    derivative works and distribution, and `git diff` on a recipe IS the experiment, where a
    diff of a 20KB fork makes a reviewer hunt for the changed paragraph."""
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE}, {"s-v2": {
        "overlay.json": json.dumps({"base": {"SKILL.md": sha(BASE)},
                                    "ops": [{"file": "SKILL.md", "op": "prepend",
                                             "text_file": "req.md"}]}),
        "req.md": "# Requirements\n\n"}})
    applied = harness.assemble_skill("s", tmp_path / "dest", variant="v2")
    assert (tmp_path / "dest" / "SKILL.md").read_text() == "# Requirements\n\n" + BASE
    assert applied == ["prepend SKILL.md <- req.md"]


def test_replace_once_refuses_an_ambiguous_anchor(tmp_path, monkeypatch):
    """Two matches means the recipe is guessing which paragraph it edits."""
    install(tmp_path, monkeypatch, {"s/SKILL.md": "QA\nQA\n"}, {"s-v2": {
        "overlay.json": json.dumps({"ops": [{"file": "SKILL.md", "op": "replace_once",
                                            "find": "QA", "text": "bounded QA"}]})}})
    with pytest.raises(SystemExit, match="occurs 2 times"):
        harness.assemble_skill("s", tmp_path / "dest", variant="v2")


def test_a_stale_base_digest_stops_the_run(tmp_path, monkeypatch):
    """The worst outcome is a HALF-applied edit, because the run still produces rows. If
    upstream moved, every `find` anchor has become a guess."""
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE}, {"s-v2": {
        "overlay.json": json.dumps({"base": {"SKILL.md": sha("something else")},
                                    "ops": [{"file": "SKILL.md", "op": "append",
                                             "text": "x"}]})}})
    with pytest.raises(SystemExit, match="The upstream"):
        harness.assemble_skill("s", tmp_path / "dest", variant="v2")


def test_a_recipe_cannot_invent_a_file_the_skill_never_reads(tmp_path, monkeypatch):
    """What a typo looks like. SKILL.md has no reference to `REQUIREMENTS.md`, so the edit
    would appear to apply and change nothing the agent sees."""
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE}, {"s-v2": {
        "overlay.json": json.dumps({"ops": [{"file": "REQUIREMENTS.md", "op": "append",
                                             "text": "x"}]})}})
    with pytest.raises(SystemExit, match="does not ship"):
        harness.assemble_skill("s", tmp_path / "dest", variant="v2")


def test_an_empty_overlay_is_refused(tmp_path, monkeypatch):
    """It would record itself as a treatment while changing nothing."""
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE},
            {"s-v2": {"overlay.json": json.dumps({"ops": []})}})
    with pytest.raises(SystemExit, match="applied no ops"):
        harness.assemble_skill("s", tmp_path / "dest", variant="v2")


def test_an_unknown_variant_exits(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, {"s/SKILL.md": BASE})
    with pytest.raises(SystemExit, match="overlay.json"):
        harness.assemble_skill("s", tmp_path / "dest", variant="nope")


# --------------------------------------------------------------- guard rails in main()

def test_selection_mode_refuses_a_variant():
    """Which skill fires IS the measurement there, so editing one candidate's prose while
    leaving the other three alone changes the choice being measured without saying so."""
    src = inspect.getsource(harness.main)
    assert "--skill-variant is not allowed on a selection task" in src


def test_the_control_arm_refuses_a_variant():
    """The OFF arm receives no skill, so the flag would be inert while still appearing in the
    command line -- and that command line is what a later reader trusts."""
    src = inspect.getsource(harness.main)
    assert "has nothing to overlay on the" in src


# --------------------------------------------------------------- conformance to the manifest

def test_the_installed_skills_match_the_manifest():
    """STRICT here, WARN in doctor. skills/MANIFEST.json is the baseline behind the 193
    published repetitions; rows measured against a drifted skill cannot be compared to them,
    and no later analysis can detect that."""
    frozen = json.loads(MANIFEST.read_text())["skills"]
    drift = {}
    for name, rec in frozen.items():
        d = harness.SKILLS_ROOT / name
        if not d.is_dir():
            pytest.skip(f"{name} skill not installed")
        got = harness.skill_tree_sha(d)
        if got != rec["tree_sha256"]:
            drift[name] = (rec["tree_sha256"][:16], got[:16])
    assert not drift, (
        f"frozen vs installed: {drift}. The ON-arm treatment differs from the one behind "
        f"results/. Re-freeze with tools/freeze_skills.py, then treat it as a NEW instrument: "
        f"re-run the canary before attributing any movement to a model.")


def test_every_skill_a_task_can_reach_is_pinned():
    """Candidates count: a selection task's measurement is which of four skills fires, so all
    four descriptions are part of that treatment."""
    frozen = json.loads(MANIFEST.read_text())["skills"]
    need = set()
    for d in sorted((ROOT / "tasks").iterdir()):
        meta = d / "meta.json"
        if not meta.is_file():
            continue
        m = json.loads(meta.read_text())
        if m.get("skill"):
            need.add(m["skill"])
        need.update(m.get("candidate_skills") or [])
    assert not (need - set(frozen)), (
        f"unpinned skills reachable from tasks/: {sorted(need - set(frozen))} -- "
        f"run tools/freeze_skills.py")


def test_the_manifest_stores_digests_not_skill_text():
    """The skills' LICENSE.txt forbids copies outside the Services, derivative works and
    distribution to third parties, and this repo is public."""
    body = MANIFEST.read_text()
    assert "NEVER" not in body, "manifest appears to contain skill prose, not just digests"
    for rec in json.loads(body)["skills"].values():
        for digest in rec["prose"].values():
            assert len(digest) == 64 and int(digest, 16) >= 0
