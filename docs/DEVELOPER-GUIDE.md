# Developer Guide

How this harness works from the inside: what goes into a repetition, how the output is
judged, what you must not break, and how to add to it.

This is the *mechanics* document. Two companions cover other ground and are not repeated
here:

| Document | Covers |
|---|---|
| [`README.md`](../README.md) | why the design is shaped this way, and the headline findings |
| [`results/EVALUATION.md`](../results/EVALUATION.md) | the study itself — results, statistics, limitations |
| this file (`docs/DEVELOPER-GUIDE.md`) | the data path, the contracts, the invariants, how to extend it |

Every path below is relative to the **repository root**, not to `docs/` — so `harness.py`
means `../harness.py` from here, and commands are written to be run from the root.

**Contents**

1. [What is being measured](#1-what-is-being-measured)
2. [Repository map](#2-repository-map)
3. [The data path, end to end](#3-the-data-path-end-to-end)
4. [Inputs](#4-inputs) — [task anatomy](#41-task-directory-anatomy) ·
   [what the workspace holds](#42-what-the-workspace-contains--and-usually-does-not) ·
   [**who supplies content vs. formatting**](#43-who-supplies-the-content-and-who-supplies-the-formatting) ·
   [the prompt contract](#44-the-prompt-contract) · [the three arms](#45-the-three-arms) ·
   [skill isolation](#46-skill-isolation) · [the invocation](#47-the-exact-invocation) ·
   [`meta.json`](#48-metajson-keys)
5. [Evaluation](#5-evaluation) — [pytest verdict](#51-stream-1--artifact-correctness-by-pytest) ·
   [tamper check](#52-stream-2--tamper-check) ·
   [wire attribution](#53-stream-3--attribution-from-the-transcript-and-the-wire) ·
   [selection scoring](#54-selection-scoring) ·
   [confounds](#55-confounds--void-not-failed) ·
   [the OFF-arm gate](#56-the-gate-upstream-of-everything)
6. [The measurement side](#6-the-measurement-side)
7. [Adding a task](#7-adding-a-task)
8. [Command reference](#8-command-reference)
9. [Membership and the freeze workflow](#9-membership-and-the-freeze-workflow)
10. [The NDJSON row](#10-the-ndjson-row)
11. [Invariants](#11-invariants)
12. [Debugging](#12-debugging)
13. [Security](#13-security)

---

## 1. What is being measured

One **repetition** is one `claude -p` invocation against one task, in one arm, on one
model, in a throwaway workspace. It yields exactly one NDJSON row.

One **cell** is (task, arm, model) over n repetitions. The published grid is 5 (task, arm)
pairs × 4 models = **20 cells**. The n per cell is deliberately uneven — read the `n`
column, never quote a single n for the profile.

A repetition is *not* one LLM call. A single task issues several — across the pinned grid,
2 to 47, median 6 — and the row's `llm_calls` counts them off the wire.

---

## 2. Repository map

| Path | What |
|---|---|
| `harness.py` | the driver. One task → fresh workspace → `claude -p` → verdict → correlate Cortex → one NDJSON row |
| `sweep.py` | a set of tasks through one arm as a matrix |
| `profile.py` | the model grid: `--run` invokes, `--report` recompiles from stored runs with no invocations, `--freeze` publishes membership |
| `pricing.py` | the internal LiteLLM rate card, hand-maintained on purpose |
| `lib_child.py` | builds the sanitized child environment |
| `tasks/` | 7 active tasks |
| `tasks-retired/` | 9 discarded tasks, each with a `DISCARDED.md` stating why. **A discarded task is a result** |
| `tools/` | task generators plus the controls and analysis tools |
| `tests/` | 22 tests guarding the confound detector and workspace setup |
| `results/` | `EVALUATION.md`, the frozen manifest, the cost-profile artifacts, the generated deck |
| `out/` | **gitignored.** Per-run NDJSON and the raw SSE capture, which contains full prompts |

---

## 3. The data path, end to end

One call to `run_rep` (`harness.py:328`), in order. The order is load-bearing in three
places, each flagged below.

1. **`fresh_ws`** (`harness.py:253`) copies `tasks/<id>/workspace/` to a new temp dir with
   `copytree`, ignoring `__pycache__`, `.pytest_cache`, `*.pyc`, `.venv`, `venv`.
2. **`test_hashes`** takes a sha256 of every `test_*.py` now present. ⚠️ **Order matters:**
   this snapshot must precede step 8.
3. **Baseline** — for a task with in-workspace tests, `pytest` must *fail* here. A suite
   that already passes means there is nothing to measure (`baseline_ok`). Hidden-verdict
   and selection tasks have no in-workspace baseline and are exempt.
4. **Child environment** (`child_env`, plus the extras at `harness.py:345`) — proxy vars,
   the Cortex CA for Node, the curated `CLAUDE_CONFIG_DIR`, bundled skills off, the venv
   on `PATH`.
5. **Arm shaping** (`harness.py:357`) — prefix the prompt with `/<skill>` on the `on` arm,
   add `Skill` to the tool allow-list on `on` and `select`, leave both alone on `off`.
6. **Invoke** `claude -p` with `cwd=ws`, wall-clocked as `[t0, t1]`, then `sleep(4)` so the
   final SSE event lands on disk.
7. **`analyse_transcript`** parses the stream-json to recover which tools, skills,
   subagents, and background tools actually ran.
8. **Tamper check** — re-hash `test_*.py` and compare against step 2, *while the workspace
   still holds only the agent's own files*. ⚠️ Taking this after step 9 would compare `{}`
   against `{test_compliance.py}` and mark every hidden-verdict task as tampered, so no
   such task could ever pass no matter how green pytest was.
9. **Install the hidden verdict** — `copytree(task["verdict"], ws)` with the same ignore
   patterns. ⚠️ It must be `copytree`, not per-entry `copy2`: running the verdict tests by
   hand leaves a `__pycache__/` inside `verdict/`, and a flat copy dies on it with
   `IsADirectoryError`. That killed a 25-repetition opus run at repetition 1.
10. **Score** — `pytest -q` again; `passed = (rc == 0) and tests_untouched`.
11. **Correlate Cortex** — events in `[t0, t1]` for the target host give tokens and
    `llm_calls`; request-phase messages give `skill_on_wire`.
12. **Detect confounds**, then emit the row.

Two context managers wrap all of this:

- **`RunLock`** (`harness.py:91`) serializes harness runs on the machine, waiting up to two
  hours. Cortex events are correlated by *time window* against a single shared proxy, so
  concurrent runs interleave — a smoke test once absorbed a sweep's events and was flagged
  `multiple_models`. The detector caught it; the lock makes the overlap impossible instead
  of merely detectable. **Never run two harness processes at once.** Interactive Claude Code
  on the same machine is safe because it has no `HTTPS_PROXY` and stays out of the window.
- **`Capture`** (`harness.py:132`) owns the SSE tail. Cortex's session store is in-memory
  with a 30-minute TTL, so the file on disk is the only durable record. A dead capture
  yields zero events, which is indistinguishable from "the proxy saw nothing" — so the
  harness starts it, proves it is producing, and stops it. An existing capture is adopted
  rather than duplicated.

---

## 4. Inputs

### 4.1 Task directory anatomy

```
tasks/<task-id>/
  prompt.md          required   the verbatim prompt (minus any arm prefix)
  workspace/         required   copied fresh into a temp dir every repetition
  meta.json          optional   skill, marker, mode, allowed-tool extras
  verdict/           optional   HIDDEN tests, installed only after the agent exits
```

Parsed by `load_task` (`harness.py:211`).

### 4.2 What the workspace contains — and usually does not

The workspace is the agent's starting state, and for most tasks it is **empty of subject
matter**. Both xlsx tasks ship exactly one file:

```
tasks/xlsx-fin-font-clean/workspace/README.txt
  "Working directory for this task. Produce the requested spreadsheet here."
```

**No spreadsheet is provided — not a complete one and not a partial one.** The agent
authors `model.xlsx` from nothing, given only the prose prompt. This is required by what
the verdict measures: the tests assert *authoring conventions* (one consistent
professional font, savings as formulas rather than typed numbers), and any starter workbook
would pre-decide exactly those conventions. Handing over a half-built file would convert a
generative benchmark into a repair benchmark and would measure the starter file's styling.

Only two tasks ship real input files:

| Task | Workspace | Kind |
|---|---|---|
| `xlsx-fin-colors`, `xlsx-fin-font-clean` | `README.txt` only | generative |
| `select-deck`, `select-spreadsheet`, `select-implicit-sheet` | `README.txt` only | generative |
| `cortex-pyfix-001` | `billing.py` + `test_billing.py` | repair |
| `select-none` | `shipping.py` + `test_shipping.py` | repair |

### 4.3 Who supplies the content, and who supplies the formatting

A recurring question, and the one most worth being precise about: **the evaluator grades an
`.xlsx` file — so where does that file come from, and who decided what is in it?**

The file is produced entirely by the agent under test. Its ingredients arrive from three
different places, and keeping them separate is what makes the benchmark work.

| Element | Source |
|---|---|
| the numbers — 7,200,000 base and 6,150,000 upside; or FY2024 12,400,000 at 8% | `prompt.md`, human-authored. **Pinned**, so every repetition is comparable |
| derived values — the saving, the ratio, the projected years | the agent writes them as **Excel formulas**. The verdict requires ≥2 formula cells, so computing them in Python and typing the result fails |
| labels, sheet layout, title row | the agent's choice, loosely steered by "label everything clearly enough that a colleague could follow it" |
| **formatting — font, colors, number formats** | **absent from the prompt.** This is the skill's contribution, and it is the treatment being measured |
| the `.xlsx` bytes | the agent: `Write` a Python script, `Bash` run it, using `openpyxl` from the harness venv — which is on the agent's `PATH` deliberately (see the comment atop `requirements.txt`) |

There is no spreadsheet-writing tool. The agent authors code and executes it. Across the
142 pinned xlsx repetitions the tool histogram is `Bash` 725, `Write` 113, `Read` 69,
`Edit` 23, `Skill` 16, `Agent` 1 — that last being the single subagent-confound repetition.

**The harness never generates, seeds, or modifies an `.xlsx`.** It supplies prose and reads
back whatever the agent produced:

```
prompt.md  ──facts, numbers──►  claude -p  ──writes .py, runs it──►  model.xlsx
skill      ──conventions────►      │                                     │
                                   └── font/format rules ────────────────┘
                                                                         ▼
                                               verdict/test_compliance.py reads it
                                               with openpyxl and asserts conventions
```

Content is pinned so repetitions are comparable and the assertions can be mechanical;
formatting is unspecified so the skill is the only possible source of it. Name the font in
the prompt and both arms pass — the discriminator is gone. Omit the numbers and no two
repetitions are comparable.

**The same split holds for every task kind, with a different thing left unspecified:**

| Task kind | Content comes from | What is left unspecified — i.e. what is measured |
|---|---|---|
| compliance, generative (`xlsx-*`) | the prompt's numbers | presentation conventions, supplied only by the skill |
| repair (`cortex-pyfix-001`) | `workspace/billing.py` plus `test_billing.py`, which **is** the specification | whether the agent can make a visible spec pass without editing it |
| selection (`select-*`) | the prompt's request | which skill the agent reaches for, when none is named |

In every case the harness fixes the inputs and leaves exactly one thing to the agent, so
that whatever the verdict measures has only one possible cause.

### 4.4 The prompt contract

**A compliance prompt must never name the convention under test.** From
`tasks/xlsx-fin-font-clean/prompt.md`:

> Build `model.xlsx` with a two-scenario opex summary. […] Make it look like something a
> finance team would circulate.

The word *font* never appears, yet the verdict checks the font. The gap between what the
prompt asks for and what the test asserts is exactly where the skill does its work. Name
the convention and both arms pass, which destroys the discriminator.

Prompts are ordinary business requests with concrete numbers, so the artifact is
checkable: base 7,200,000, upside 6,150,000, show the saving and the saving as a share of
base, "both calculated."

### 4.5 The three arms

| Arm | Prompt | `--allowedTools` | Skills in config dir | Role |
|---|---|---|---|---|
| `on` | prefixed `/<skill>` | baseline + `Skill` | exactly the task's skill | treatment |
| `off` | unmodified | baseline | none | **control** |
| `select` | unmodified, names no skill | baseline + `Skill` | all `candidate_skills` | a different benchmark |

`select` asks a different question — not "does the skill improve compliance" but "does the
model reach for the right skill unprompted." It is scored from the transcript, not by
pytest.

### 4.6 Skill isolation

`main` builds a curated `CLAUDE_CONFIG_DIR` (`harness.py:557`) containing a `skills/`
directory holding **exactly the task's skill, or nothing at all**, copied from
`~/.claude/skills/<name>`, with `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`.

The consequence is the point: any *other* skill appearing in the transcript is a confound
by construction, not by judgment.

Note it is `CLAUDE_CONFIG_DIR` that scopes user skills — **not `HOME`**. That was
established by measurement, and getting it wrong silently leaks the real skill library into
the control arm.

### 4.7 The exact invocation

```
claude -p <prompt> \
       --add-dir <ws> \
       --model <model> \
       --allowedTools "Read Edit Write Bash(python*) Bash(pytest*)" [+ task extras] \
       --output-format stream-json --verbose
```

run with `cwd=ws` and the sanitized environment from §3, step 4.

- The tool allow-list is deliberately narrow. `meta.json` may add to it via
  `allowed_tools_extra` — the docx skill mandates a Node library, so without
  `Bash(node*)`/`Bash(npm*)` the agent silently falls back to `python-docx` and the
  harness would measure the fallback rather than the skill.
- The model is **pinned explicitly**. Inheriting it is unsafe: `ANTHROPIC_MODEL` in the
  ambient environment differed from `settings.json`, so comparisons drifted silently.
  `--model` beats both, and `model_pin_honoured` verifies on the wire that it took.
- `--output-format stream-json --verbose` is what makes the transcript machine-readable.

### 4.8 `meta.json` keys

| Key | Meaning |
|---|---|
| `skill` | skill name; enables the `on`/`off` contrast. Absent ⇒ a no-skill task |
| `skill_marker` | a distinctive phrase from the skill's `SKILL.md`, matched on the wire |
| `mode` | `"compliance"` (default) or `"selection"` |
| `expected_skill` | selection mode: the correct skill, or `null` for the negative case |
| `candidate_skills` | selection mode: what to make available |
| `allowed_tools_extra` | additional `--allowedTools` entries |

---

## 5. Evaluation

The verdict is a conjunction over independent evidence streams. Each exists because the
others can be fooled.

### 5.1 Stream 1 — artifact correctness, by pytest

`pytest -q` runs in the workspace under the repo venv (`pytest_run`, `harness.py:270`),
after the agent has exited.

**What the evaluator sees is only the artifact.** It opens the single `.xlsx` the agent left
in the workspace — via `openpyxl`, exactly as any downstream consumer would — and asserts
against it. It reads no transcript, no prompt, and no intermediate script; it does not know
which arm or model produced the file, and it has no channel through which it could. Zero or
several `.xlsx` files is a loud failure rather than a guess about which one to grade. Where
that file came from is §4.3.

Placement of the suite is the central design decision:

**Hidden verdict** (`tasks/<id>/verdict/test_compliance.py`) — installed only *after* the
agent exits. For a compliance task the test *enumerates the conventions*, so an agent that
can read it simply complies. Both arms would then pass and the discriminator would be gone.
The test is the answer key, so the agent must not see it.

**Visible spec** (`tasks/cortex-pyfix-001/workspace/test_billing.py`) — where the tests
*are* the specification, visibility is correct. The prompt even instructs the agent to run
them, and forbids editing them.

What a compliance suite actually asserts is mechanical, not a smell test. From
`xlsx-fin-font-clean`:

```python
PROFESSIONAL = {"arial", "times new roman", "helvetica", "calibri light", "garamond"}
```

- **one** font across every non-empty cell, and it must be in that set. Calibri fails
  explicitly — it is Excel's unstyled default and "is what you get by not deciding."
- no `#REF!` / `#DIV/0!` / `#VALUE!` / `#N/A` / `#NAME?` literals, checked **twice**: once
  with formulas and once with cached values (`data_only=True`), because an error can hide
  in either view.
- the saving and the ratio must be **formulas**, not typed numbers — at least two cells
  starting with `=`.
- exactly **one** `.xlsx` in the directory; zero or several fails loudly rather than
  guessing which one to grade.

### 5.2 Stream 2 — tamper check

sha256 of every `test_*.py` before and after the agent runs, snapshotted before the hidden
verdict arrives (§3, steps 2 and 8).

```python
passed = (rc1 == 0) and tests_untouched
```

Editing the tests green fails the repetition. Green pytest alone is not a pass.

### 5.3 Stream 3 — attribution, from the transcript and the wire

`analyse_transcript` (`harness.py:279`) walks the stream-json and collects `tool_use`
blocks: `tools`, `skills`, `skill_names`, `subagents`, `background`, `assistant_turns`.

The transcript has a blind spot that the wire covers. **An explicit `/skill-name` is
expanded client-side into the prompt and produces no `tool_use` at all**, so the transcript
*cannot* confirm the skill was applied. Hence `skill_on_wire`: the task's `skill_marker` is
matched against `inference.messages` on request-phase Cortex events, in memory, and **only
a boolean escapes** — those messages are the full prompt and the session API is
unauthenticated.

Conversely, a `Skill` tool_use means the *model* reached for a skill itself, which is the
measurement in `select` mode and a confound in compliance mode.

### 5.4 Selection scoring

No pytest at all. `selection_correct` is derived from which skills fired:

```python
if expected_skill is None:   selection_correct = not fired      # negative case
else:                        selection_correct = expected_skill in fired
passed = bool(selection_correct)
```

The negative case (`select-none`) matters: an over-eager selector is as wrong as a blind
one, so a selection benchmark that tests only true positives is half a benchmark.

### 5.5 Confounds — void, not failed

A repetition can be **invalid** rather than **failed**, and conflating the two biases every
median. Detectors (`harness.py:456` onward):

| Confound | Meaning |
|---|---|
| `no_artifact_produced` | the agent could not do the work at all — e.g. its skill needs a tool that was not allowed. A harness fault; **never** score it as non-compliance |
| `expected_skill_not_on_wire` | `on` arm, but the skill text never reached the model |
| `skill_leaked_into_off_arm` | the control is void: the skill arrived anyway |
| `foreign_skill_invoked` | a *different* skill fired. Re-invoking the task's own skill is benign and is not flagged |
| `subagent_invoked` | work outside the single agent loop. Real and billable, but unattributable — measured at 2.7–8.2× the tokens |
| `multiple_skills_fired` | selection mode: several fired, muddying attribution |
| `multiple_models` / `model_pin_ignored` | the wire disagrees with the request |
| `bad_baseline` | the suite already passed before the agent ran |
| `no_cortex_inference_events` | nothing was captured; the row has no measurement |

Deliberately **not** a confound: background tools (`TaskOutput`, `TaskStop`). They are
recorded in `background_tools` but issue no LLM calls of their own, so every token still
belongs to the one loop being measured. Treating them as a confound was wrong twice —
mechanically, and empirically: in both pptx cells the single most expensive repetition
carries *no* background tool, so the flag marks a subset of a bimodal cost mode. Excluding
on it biases the median rather than cleaning it, which is how a published overhead figure
came to be quoted as 3.0×. `tests/test_confound_detector.py` has a source-level guard that
fails if anyone re-adds it.

### 5.6 The gate upstream of everything

**Every task is pre-screened on the `off` arm.** A task the agent passes *without* the
skill is not measuring the skill and must be discarded. 9 of 11 candidates died at this
gate and live in `tasks-retired/`, each with a `DISCARDED.md`.

---

## 6. The measurement side

Tokens, `llm_calls`, and `skill_on_wire` come from correlating Cortex SSE events by time
window (`harness.py:412`) — nothing else in the row provides them. `tool_calls` and
`assistant_turns` come from the transcript and are proxy-independent.

Cost is computed by `pricing.py`, never stored: `cost(model, uncached=, cache_read=,
cache_write=, output=, scenario=)`. `SOURCE_DATE` is `2026-09-09` and the card is
hand-maintained on purpose. Two scenarios exist because cache billing is an assumption:
scenario **A** prices all prompt tokens at the input rate; scenario **B** applies
`CACHE_READ_MULT = 0.10` and `CACHE_WRITE_MULT = 1.25`. Report both, or say which.

### Two warnings that have each cost a day

**Read volume, never cost or wall time, when judging whether a cell reproduced.**
`llm_calls`, `tool_calls`, and `total_tokens` are workload measures and decide the verdict.
Cost and `wall_seconds` are diagnostics only.

- **Cost follows the cache tier split, which follows run order.** A cold first repetition
  in a fresh session re-tiers roughly 29k prompt tokens from cacheRead (0.10×) to
  cacheWrite (1.25×) at an unchanged *total*, a 12.5× price ratio that moves a three-
  repetition mean about 30%. The detector is the cacheWrite share of prompt tokens against
  the grid median (`COLD_MULT = 2.0` in `tools/stability_probe.py`) — not cost, and not CV.
- **Wall time follows machine load.** In the pyfix probe it moved ×1.34–×1.81 for two
  models doing provably identical amounts of work. It is not evidence about a model, and it
  is not a latency measurement.

**Money is recomputed, never scaled.** A cell's cacheRead share moves independently of its
total, so scaling a dollar figure by a token ratio is wrong. Call `pricing.cost()`.

---

## 7. Adding a task

1. **Write `prompt.md`** as a plain business request with concrete numbers. Do not name the
   convention you intend to test (§4.4).
2. **Choose the convention.** It must be **arbitrary, not good practice** — something a
   competent agent would not do by default. Good practice is what the model already does,
   so the skill cannot show up. See `README.md` for the heuristic and the six tasks it
   killed.
3. **Write the verdict tests.** Hidden in `verdict/` for compliance; in `workspace/` only
   when the tests *are* the spec. Assert mechanically checkable properties of the artifact.
   Fail loudly on a missing or ambiguous artifact rather than guessing.
4. **Seed `workspace/`** with the minimum. Usually a `README.txt` saying where to put the
   output — no starter artifact, or you pre-decide the thing you are testing.
5. **Add `meta.json`** with `skill` and a `skill_marker` copied verbatim from the skill's
   `SKILL.md`.
6. **Pre-screen on the `off` arm**, at least 3 repetitions:
   ```bash
   python3 harness.py tasks/<id> --arm off --reps 3
   ```
   If it passes without the skill, retire it with a `DISCARDED.md`. This is the gate, not a
   formality.
7. **Confirm the `on` arm** and check `skill_on_wire` is `true` in the row. If it is
   `false`, the treatment never happened and the contrast is meaningless.
8. **Check the confounds** on both arms before believing any number.
9. **Only then** add it to `profile.CELLS` and buy repetitions.

---

## 8. Command reference

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
abctl service start          # Cortex: forward proxy + tls_bridge, from ~/.cortex/bin
```

Cortex must be reachable — the session API on `127.0.0.1:47601`, the proxy on `47600`.
`harness.py` exits early if it is not.

| Command | Effect |
|---|---|
| `python3 harness.py tasks/cortex-pyfix-001 --reps 3` | the canary: proves the rig works |
| `python3 harness.py tasks/<id> --arm off --reps 3` | pre-screen a candidate task |
| `python3 harness.py tasks/<id> --model claude-sonnet-5 --out out/scratch` | one cell, output redirected |
| `python3 sweep.py --arm off --reps 3 --pattern 'xlsx-*'` | a task set through one arm |
| `python3 profile.py --run --reps 5` | the grid: **invokes**, costs money |
| `python3 profile.py --report` | recompile from stored runs, **no invocations** |
| `python3 profile.py --freeze` | publish membership to the manifest |
| `python3 profile.py --report --all` | ignore the manifest, glob everything; labels itself |
| `.venv/bin/python tools/cost_significance.py` | which cost gaps are established |
| `.venv/bin/python tools/stability_probe.py --task <id>` | which cells reproduce across sessions |
| `.venv/bin/python tools/make_summary_deck.py` | regenerate the deck |
| `.venv/bin/python -m pytest -q` | 22 tests |

`harness.py` flags: `--reps`, `--out` (default `out/runs`), `--arm {on,off,select}`,
`--model`.

Use `.venv/bin/python`, not `python3`, for anything needing `openpyxl` or `pptx`.

---

## 9. Membership and the freeze workflow

`profile.py --report` reads a **pinned** file list from `results/profile-manifest.json`
(filenames, row counts, sha256 — never prompt content). This exists because the report
used to glob `out/runs/` and `out/runs-archive/` directly, so any ad-hoc repetition landed
in a published cell: one canary run moved a cell from n=10 to n=11 and changed its median,
and the committed artifact stopped reproducing.

**`--run` does not publish.** You must freeze afterward:

```bash
python3 profile.py --run --reps 5
python3 profile.py --freeze
```

Exclusion works at two granularities:

```bash
python3 profile.py --freeze --exclude <basename>=<reason>
python3 profile.py --freeze --exclude-rep <basename>#<rep>=<reason>
```

Per-repetition exclusion exists because one `select-deck` file holds a contaminated
repetition beside two clean ones; keying on `basename#rep` leaves the file's sha256 valid,
so integrity still covers the bytes actually read. Reasons are stored and carry forward
across re-freezes; `--reset-exclusions` drops them. A rep exclusion matching nothing prints
`STALE REP EXCLUSION` rather than silently doing nothing. `--report` shouts
`!! MEMBERSHIP PROBLEM` on any MISSING or CHANGED file.

**Preflight a published artifact by diffing a fresh `--report` against the committed
file. That diff is the integrity test.**

Adding a stability probe: register the cell in the `PROBES` dict in
`tools/stability_probe.py` **and** in the manifest's `excluded` map, in the same change.
Probe runs must not join the grid.

---

## 10. The NDJSON row

One row per repetition, written to `out/runs/<task>-<arm>-<model>-<timestamp>.ndjson`.

**Identity** — `task_id`, `arm`, `mode`, `rep`, `model_requested`, `model`, `workspace`,
`allowed_tools`, `hidden_verdict`

**Verdict** — `passed`, `pytest_rc`, `pytest_tail`, `tests_untouched`, `baseline_ok`,
`baseline_tail`, `no_artifact_produced`, `selection_correct`, `expected_selection`,
`expected_skill`

**Attribution** — `tool_calls`, `tool_histogram`, `assistant_turns`, `skills_invoked`,
`skills_fired`, `skill_on_wire`, `subagents_invoked`, `background_tools`

**Measurement** — `llm_calls`, `input_tokens`, `output_tokens`, `prompt_tokens`,
`completion_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`,
`wall_seconds`, `t0`, `t1`, `cortex_events`, `cortex_tunnels`

**Integrity** — `confounded`, `confound_reasons`, `model_pin_honoured`, `timed_out`,
`child_exit`

Persisted Cortex fields are a **whitelist** (`EVENT_KEEP`, `INF_KEEP`). Raw events carry
`inference.messages` — the full prompt — and are dropped. Widening that whitelist is a
disclosure decision.

Not currently persisted, though parsed: the CLI's own `result` event carries
`duration_ms`, `duration_api_ms`, `ttft_ms`, `usage`, and `total_cost_usd`.
`analyse_transcript` returns it and `run_rep` keeps only `assistant_turns`.

---

## 11. Invariants

Each of these prevents a failure that actually happened.

1. **Snapshot test hashes before installing the hidden verdict.** Otherwise every
   hidden-verdict task is marked tampered and can never pass.
2. **Install the verdict with `copytree` + ignore patterns**, never per-entry `copy2`. A
   stray `__pycache__/` in `verdict/` raises `IsADirectoryError` and kills the run
   mid-flight. Guarded by `tests/test_workspace_setup.py`.
3. **One harness process at a time.** `RunLock` enforces it; do not bypass it. Time-window
   correlation cannot separate two concurrent runs.
4. **Pin the model with `--model` and verify `model_pin_honoured`.** Never inherit it.
5. **Pre-screen every task on the `off` arm.** No exceptions.
6. **Never let a compliance prompt name the convention under test.**
7. **Keep the hidden verdict hidden.** If the agent can read the answer key, both arms pass.
8. **Background tools are not confounds.** Source-level guard in the tests.
9. **`--run` does not publish. Freeze explicitly, and diff before committing.**
10. **Judge reproduction on volume, never on cost or wall time.**
11. **Recompute money with `pricing.cost()`.** Never scale a dollar figure by a token ratio.
12. **Never print credentials or a process environment.** Use `pgrep -f` or
    `ps -o pid,etime,stat,comm` — never `command`, `args`, or `aux`, which render a
    neighboring process's environment. Match on value shape, install via an in-process
    pipe, print only a hash.
13. **`out/` stays gitignored.** It holds raw prompts.

---

## 12. Debugging

| Symptom | Likely cause |
|---|---|
| exits with "Cortex session API not reachable on 47601" | `abctl service start` |
| `no_cortex_inference_events` | capture died, or a stale `no_proxy` routed the child **around** the proxy. Interception is cooperative — verify, do not assume |
| `expected_skill_not_on_wire` on the `on` arm | skill missing from `~/.claude/skills/<name>`, or the marker no longer matches the current `SKILL.md` |
| `skill_leaked_into_off_arm` | config dir not clean, or `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` not set |
| `no_artifact_produced` | the skill needs a tool that is not allowed. Add `allowed_tools_extra`; do **not** score it |
| `bad_baseline` | in-workspace tests already pass — the task measures nothing |
| `multiple_models` | a concurrent run leaked into the window. Check the lock |
| `IsADirectoryError` mid-run | a `__pycache__/` in `verdict/` reached a flat copy. See invariant 2 |
| `--report` prints `!! MEMBERSHIP PROBLEM` | a manifest file is missing or its bytes changed. Do not freeze over it — find out why |
| a cell's cost jumped ~30% with identical tokens | a cold first repetition re-tiered the cache. Run `tools/stability_probe.py` |
| `ModuleNotFoundError: pptx` / `openpyxl` | you used `python3` instead of `.venv/bin/python` |
| "another harness run holds the lock; waiting..." | expected. Runs are serialized by design |

---

## 13. Security

- `out/` is gitignored: the SSE capture contains raw prompts.
- Persisted Cortex fields are a whitelist, not a blacklist.
- `skill_on_wire` matches in memory and emits only a boolean; the marker is never stored
  alongside the messages it matched.
- The Cortex session API is unauthenticated on localhost. Treat everything it returns as
  sensitive.
- See invariant 12 for the credential-handling rule.
