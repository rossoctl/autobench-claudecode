#!/usr/bin/env python3
"""Freeze the installed skills into skills/MANIFEST.json -- the treatment, pinned.

WHY. On the ON arm the skill text IS the independent variable, and the harness copies it out
of ~/.claude/skills at run time. Nothing in the repo recorded which version that was, so an
upstream skill update between two runs would move a pass rate with no model involved and
nothing in the data to show it. That is the identical defect .python-version fixed for the
venv, on the half of the apparatus that matters more.

WHAT IS RECORDED, and what deliberately is not. A digest per skill (see
`harness.skill_tree_sha`), a file count, and a per-file sha256 for the PROSE only -- the .md
files the agent reads. The 1.2MB of XSD schemas and helper scripts in each skill dir are
covered by the tree digest but not enumerated: the manifest is meant to be read by a human
deciding whether the instrument moved, and 240 schema hashes bury the one line that answers
that. No file CONTENTS are stored here, only digests -- and that is not merely tidiness: each
skill's LICENSE.txt forbids retaining copies outside the Services, derivative works and
distribution to third parties, and this repo is public. Digests prove the instrument did not
move while disclosing nothing. It is also why a skill variant is an edit RECIPE rather than a
forked SKILL.md; see skills/README.md.

Run it when a skill is deliberately updated, and treat the diff the way a requirements.lock
change is treated: a new instrument, so re-run the canary before attributing any movement.
"""
import datetime as dt
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "skills" / "MANIFEST.json"


def needed_skills():
    """Every skill any ACTIVE task can reach -- named or offered as a candidate.

    Candidates count. A selection task's measurement is which of four skills fires, so all
    four descriptions are part of that treatment, `pdf` included even though no compliance
    task uses it.
    """
    need = set()
    for d in sorted((ROOT / "tasks").iterdir()):
        meta = d / "meta.json"
        if not meta.is_file():
            continue
        m = json.loads(meta.read_text())
        if m.get("skill"):
            need.add(m["skill"])
        need.update(m.get("candidate_skills") or [])
    return sorted(need)


def freeze(skill):
    src = harness.SKILLS_ROOT / skill
    if not src.is_dir():
        sys.exit(f"{src} does not exist -- cannot freeze {skill!r}")
    files = [p for p in sorted(src.rglob("*")) if p.is_file()]
    prose = {p.relative_to(src).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in files if p.suffix.lower() == ".md"}
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files),
            "tree_sha256": harness.skill_tree_sha(src), "prose": prose}


def main():
    skills = needed_skills()
    doc = {
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "~/.claude/skills",
        "note": ("Digests of the skills as installed when this was written. The ON arm's "
                 "treatment is this text, so a changed digest is a changed experiment, not "
                 "a changed tool. Regenerate with tools/freeze_skills.py."),
        "skills": {s: freeze(s) for s in skills},
    }
    MANIFEST.parent.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}")
    for s, v in doc["skills"].items():
        print(f"  {s:6} {v['tree_sha256'][:16]}  {v['files']:3} files  "
              f"{v['bytes'] / 1e6:5.2f}MB  {len(v['prose'])} prose")


if __name__ == "__main__":
    main()
