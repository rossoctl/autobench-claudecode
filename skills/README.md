# The skill as apparatus

On the ON arm, **the skill text is the independent variable.** `harness.py` copies
`~/.claude/skills/<name>` into a per-repetition config dir at run time, so until now a row said
which model and which venv it was measured with, but not which *skill*. An upstream skill update
between two runs would move a pass rate with no model involved and nothing in the data to show
it — the same defect `.python-version` fixed for the verdict venv, on the half of the apparatus
that matters more.

This directory fixes that in two pieces:

| File | What it is for |
|---|---|
| `MANIFEST.json` | the installed skills' digests, frozen. Regenerate with `tools/freeze_skills.py` |
| `<skill>-<variant>/overlay.json` | an **edit recipe**: the experiment "does rewording the skill help?" |

Every row now also carries `skill_variant`, `skill_sha` and `skill_files`
(`harness.skill_apparatus`), digested from the tree **actually handed to the child** — so an OFF
arm's empty dir is `null` rather than a hash of nothing, and a selection task's four candidates
are covered by one field.

## Why this repo contains no skill prose

The skills are Anthropic's, and each ships a `LICENSE.txt` that forbids retaining copies outside
the Services, reproducing them, creating derivative works, and distributing them to third
parties. This repo is public. So:

* **`MANIFEST.json` stores digests only** — enough to prove the instrument did not move, and it
  discloses nothing. Per-file `sha256` is kept for the `.md` prose the agent reads; the ~1.1 MB of
  XSD schemas and helper scripts per skill is covered by the tree digest but not enumerated,
  because 240 hashes bury the one line a human needs.
* **A variant is a recipe, not a forked file.** `skills/docx-v2/SKILL.md` would be a derivative
  work of their document, publicly distributed. `skills/docx-v2/overlay.json` plus our own prose
  fragments is our writing plus short anchors, and the edited skill exists only inside the temp
  config dir the harness already builds to run the child.

That constraint turned out to be the better design anyway: a 20 KB forked `SKILL.md` makes a
reviewer hunt for the changed paragraph, whereas `git diff` on a recipe *is* the experiment.

## Writing a variant

```
skills/pptx-v2/
  overlay.json        the recipe
  requirements.md     prose this variant inserts (our own words)
```

```json
{
  "description": "one line: what hypothesis this variant tests",
  "base": {"SKILL.md": "<sha256 of the installed file this was written against>"},
  "ops": [
    {"file": "SKILL.md", "op": "prepend", "text_file": "requirements.md"},
    {"file": "SKILL.md", "op": "replace_once", "find": "<short anchor>", "text_file": "qa.md"}
  ]
}
```

Ops are `prepend`, `append` and `replace_once`; text comes from `text_file` (relative to the
variant dir) or inline `text`, exactly one of the two. The guard rails all exist because a
half-applied edit is worse than a failed run — it still produces rows:

* `base` pins the upstream bytes the recipe was authored against. If the installed skill changed,
  the run **exits**: every `find` anchor has become a guess. Update the ops, update `base`, and
  treat the result as a new instrument (re-run the canary).
* `replace_once` requires the anchor to occur **exactly once**.
* An op may only target a file the skill already ships. Adding one is what a typo looks like, and
  a file `SKILL.md` never references is a file the agent never reads — the edit would appear to
  apply and change nothing.
* An overlay that applies zero ops exits, rather than recording itself as a treatment.

Get the `base` digest with:

```bash
shasum -a 256 ~/.claude/skills/pptx/SKILL.md
```

Then run it:

```bash
python3 harness.py tasks/pptx-no-accent-lines --arm on --skill-variant v2 --reps 3
```

The flag is refused in two places, both on purpose: on a **selection** task, because which skill
fires is the measurement and editing one candidate biases that choice silently; and on any arm
other than `on`, because the control receives no skill and the flag would be inert while still
appearing in the command line.

## The baseline

`MANIFEST.json` was first written on 2026-09-21, and nothing under the four skill directories had
changed since 2026-09-08 (`find -newermt`), so those digests **are** the skills behind the 193
published repetitions in `results/`. `bin/autobench-claudecode-cli doctor` compares the installed
digests against the manifest and **WARNs** on drift — the same audience split as the venv checks:
a consumer wants a number, a contributor is about to add rows to a frozen grid.
