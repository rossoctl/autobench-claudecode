# Developer Guide

How to install this harness and drive it (§2–§3), and how it works from the inside: what goes
into a repetition, how the output is judged, what you must not break, and how to add to it.

This is the *mechanics* document. Two companions cover other ground and are not repeated
here:

| Document | Covers |
|---|---|
| [`README.md`](../README.md) | why the design is shaped this way, and the headline findings |
| [`results/EVALUATION.md`](../results/EVALUATION.md) | the study itself — results, statistics, limitations |
| this file (`docs/DEVELOPER_GUIDE.md`) | installation, the `autobench-modelskill` CLI, the data path, the contracts, the invariants, how to extend it |

Every path below is relative to the **repository root**, not to `docs/` — so `harness.py`
means `../harness.py` from here, and commands are written to be run from the root.

**Contents**

1. [What is being measured](#1-what-is-being-measured)
2. [Installation](#2-installation) — [prerequisites](#21-prerequisites) ·
   [install](#22-install) · [Cortex](#23-cortex-the-instrument) ·
   [the skills under test](#24-the-skills-under-test) ·
   [why there is no `pip install`](#25-why-there-is-no-pip-install)
3. [**Benchmarking with `autobench-modelskill`**](#3-benchmarking-with-autobench-modelskill) —
   [doctor first](#31-doctor-first) · [what you can benchmark](#32-what-you-can-benchmark) ·
   [one cell](#33-run-one-cell) · [across models](#34-compare-across-models) ·
   [reading the report](#35-reading-the-report) ·
   [the three measures](#36-the-three-measures-and-why-they-are-three) ·
   [significance](#37-significance-before-you-quote-a-gap) ·
   [a new skill of your own](#38-benchmarking-a-skill-of-your-own) ·
   [full syntax](#39-full-syntax)
4. [Repository map](#4-repository-map)
5. [The data path, end to end](#5-the-data-path-end-to-end)
6. [Inputs](#6-inputs) — [task anatomy](#61-task-directory-anatomy) ·
   [what the workspace holds](#62-what-the-workspace-contains--and-usually-does-not) ·
   [**who supplies content vs. formatting**](#63-who-supplies-the-content-and-who-supplies-the-formatting) ·
   [the prompt contract](#64-the-prompt-contract) · [the three arms](#65-the-three-arms) ·
   [skill isolation](#66-skill-isolation) · [the invocation](#67-the-exact-invocation) ·
   [`meta.json`](#68-metajson-keys)
7. [Evaluation](#7-evaluation) — [pytest verdict](#71-stream-1--artifact-correctness-by-pytest) ·
   [tamper check](#72-stream-2--tamper-check) ·
   [wire attribution](#73-stream-3--attribution-from-the-transcript-and-the-wire) ·
   [selection scoring](#74-selection-scoring) ·
   [confounds](#75-confounds--void-not-failed) ·
   [the OFF-arm gate](#76-the-gate-upstream-of-everything)
8. [The measurement side](#8-the-measurement-side)
9. [Adding a task](#9-adding-a-task)
10. [Command reference](#10-command-reference)
11. [Membership and the freeze workflow](#11-membership-and-the-freeze-workflow)
12. [The NDJSON row](#12-the-ndjson-row)
13. [Invariants](#13-invariants)
14. [Debugging](#14-debugging)
15. [Security](#15-security)

Benchmarking a model + skill pair, and nothing else? §2 then §3. The rest of this document is
what those two sections stand on.

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

## 2. Installation

### 2.1 Prerequisites

| Requirement | Check | Note |
|---|---|---|
| macOS or Linux | — | the harness uses `fcntl` locking and POSIX paths |
| Python **3.12+** as `python3` | `python3 -V` | stdlib only for the driver; the venv is for the *verdict* |
| Claude Code CLI, authenticated | `claude --version` | this is the subject under test, not a dependency to pin |
| **Cortex**, running | `curl -s localhost:47601/healthz` | the instrument. Without it there are no tokens at all (§2.3) |
| A gateway to talk to | `ANTHROPIC_BASE_URL` set | an internal LiteLLM in this repo's case; any Anthropic-compatible endpoint works |
| The skills you want to measure | `ls ~/.claude/skills` | §2.4 |

### 2.2 Install

```bash
git clone https://github.com/rossoctl/autobench-claudecode.git
cd autobench-claudecode
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# optional: put the CLI on PATH. It resolves its own real path, so a symlink still
# finds the clone it belongs to.
ln -s "$PWD/bin/autobench-modelskill" ~/.local/bin/autobench-modelskill

autobench-modelskill doctor        # or ./bin/autobench-modelskill doctor
```

The venv is **verdict-side**: `openpyxl`, `python-pptx` and `pytest` are what score an
artifact after the child exits, and `harness.py` runs the verdict with `.venv/bin/python` no
matter which interpreter drives it — so the venv must exist even if you invoke everything with
the system `python3`. Note that its `bin/` is also prepended to the **child's** `PATH`, so
anything a verdict asserts must be importable there too; that is deliberate, and it means the
agent can use those libraries as well.

**What you set, and what the harness sets.** Getting this backwards is the most common way a
run produces rows full of zeros:

| Variable | Set by | Why it matters |
|---|---|---|
| `ANTHROPIC_BASE_URL` | **you** | the gateway the child authenticates against — *and* the host the harness filters Cortex events by. Unset means no filter, so unrelated traffic in the window joins the row |
| `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY` | **you** | passed through to the child deliberately, so a curated config dir does not lose its credentials |
| `HTTPS_PROXY`, `HTTP_PROXY` | the harness, per repetition | pointed at `127.0.0.1:47600`. Do **not** set these yourself; an ambient proxy is stripped from the child (`lib_child.child_env`, `inherit_proxy=False`) |
| `NODE_EXTRA_CA_CERTS` | the harness | `~/.cortex/ca/ca.crt`. Claude Code is **Node**, so this is the lever that works; `SSL_CERT_FILE` is the Python runtime's equivalent and does nothing here |
| `CLAUDE_CONFIG_DIR` | the harness | a curated directory per repetition. Skill scoping is `CLAUDE_CONFIG_DIR`, not `HOME` (§6.6) |
| `no_proxy` / `NO_PROXY` | nobody | stripped from the child. A stale one in your shell routes *anything else* you run around Cortex, silently |
| `HARNESS_OUT`, `HARNESS_VENV` | optional overrides | `HARNESS_OUT` also moves the run lock, so two processes using different values would stop serializing. Prefer `--out` |

### 2.3 Cortex, the instrument

```bash
abctl service start        # from ~/.cortex/bin
```

Cortex must run as a **forward proxy with `tls_bridge`**. That is not a preference: the
reverse-proxy role was tried and measured, and it does **not** dispatch the inference parsers
— events arrive with no `inference` block, so every token field would read 0. The session API
listens on `127.0.0.1:47601`, the proxy on `47600`; `harness.py` exits early if either is
missing.

Events are held **in memory with a ~30-minute TTL** and there is no OTLP export and no
`/metrics`, which is why the harness streams `/v1/events` for the duration of a run rather
than querying afterwards.

Interception is **cooperative**. A child that does not use the proxy is simply not measured —
and the row says so, flagging `no_cortex_inference_events` rather than presenting zeros as
data. Verify, never assume.

### 2.4 The skills under test

A skill is a directory under `~/.claude/skills/<name>/` containing `SKILL.md`. `doctor` lists
which skills the active tasks need and blocks if one is absent, because the ON arm cannot run
without it. The harness copies the named skill into a curated config directory for the ON arm
and gives the OFF arm a config directory with none, plus
`CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` (§6.6).

### 2.5 Why there is no `pip install`

This repository contains a top-level module named `profile`, which would **shadow the stdlib
profiler for the entire environment** if it were ever put on `sys.path` by a distribution —
and an editable install does exactly that, via a `.pth`, for every process in that
environment regardless of the working directory. So there is no package and no console-script
entry point. `bin/autobench-modelskill` is a stdlib-only script that resolves its own real
path, which is all a symlink on `PATH` needs.

---

## 3. Benchmarking with `autobench-modelskill`

One command surface over the whole pipeline, for the question *"which model runs this skill
most efficiently?"*. It plans the repetitions, hands each one to `harness.py`, and compiles
the three measures a consumer actually asks for: **token efficiency, cost efficiency,
latency**.

It writes to `out/modelskill/` by default — deliberately outside `profile.RUN_DIRS`, so your
exploratory repetitions are structurally unable to join a cell someone has published a number
for (§11 says what happened the one time that was possible).

### 3.1 `doctor` first

```console
$ autobench-modelskill doctor
[  ok  ] python              3.12.7 (/usr/bin/python3)
[  ok  ] claude CLI          2.1.257 (Claude Code)  (/Users/you/.local/bin/claude)
[  ok  ] venv                /repo/.venv pytest + openpyxl importable
[  ok  ] cortex session api  http://127.0.0.1:47601/healthz 200
[  ok  ] cortex proxy        http://127.0.0.1:47600 accepting
[  ok  ] cortex CA           /Users/you/.cortex/ca/ca.crt (570 bytes, sha256:1a2b3c4d)
[  ok  ] target host         gateway.example.internal
[  ok  ] auth                ANTHROPIC_AUTH_TOKEN=set sha256:5e6f7a8b  ANTHROPIC_API_KEY=unset
[  ok  ] no_proxy            unset
[  ok  ] task skills         4/4 present in /Users/you/.claude/skills (docx, pdf, pptx, xlsx)
[  ok  ] run lock            free (/repo/out/.harness.lock)
[  ok  ] sse capture         not running; the harness will start and stop its own

12 ok, 0 warning(s), 0 blocker(s)
```

Every blocker makes a repetition **unmeasurable**, not merely degraded — with Cortex down the
row self-flags and every token field is 0. Exit status is 1 when any blocker is present, so
`doctor` works in a script. Credentials are reported as a **sha256 prefix only**; the digests
above are illustrative.

### 3.2 What you can benchmark

```bash
autobench-modelskill tasks              # active tasks: mode, skill, verdict style, arms
autobench-modelskill tasks --retired    # the discarded ones. A discarded task is a result
autobench-modelskill models             # aliases, the rate card, and its date
```

`models` prints the rate card behind every dollar figure, its `SOURCE_DATE`, and both cache
scenarios. Any `--model` string is accepted; one absent from the card reports no cost column
and still reports volume and latency.

### 3.3 Run one cell

```bash
autobench-modelskill run --task cortex-pyfix-001 --reps 5 --model claude-sonnet-5
```

`cortex-pyfix-001` is the canary — no skill involved, so it tests the rig rather than a
model. One repetition prints:

```
rep 1: passed=True pytest='6 passed in 0.00s' turns=10 tools=6 llm_calls=6 pin_ok=True
       tok(in/out/cache)=8/1016/162136 api=20s wall=21.3s confounded=False
```

Read that line as four different instruments: `passed` is pytest against the artifact,
`tools`/`turns` come from the transcript, `llm_calls` and the token counts come off the wire
from Cortex, and `api` comes from the CLI's own `result` event — the only measurement in the
row that survives the proxy being absent.

### 3.4 Compare across models

```bash
autobench-modelskill compare \
  --task xlsx-fin-colors \
  --models claude-haiku-4-5-20251001,claude-sonnet-5,claude-opus-5 \
  --arms on,off --reps 5 --significance
```

That is 3 models × 2 arms × 5 repetitions = **30 real `claude -p` invocations**, about **$4**
at the 2026-09-09 card, nearly two thirds of it `opus-5`. Add `--dry-run` first: it prints the
plan, the invocation count and the exact harness command for each cell without spending
anything.

Keep `--arms on,off`. The OFF arm is the control that makes the ON arm mean anything — and it
is the same gate that discarded 9 of the first 11 tasks written for this study (§7.6).

`compare` runs the cells in sequence and then reports. Repetitions serialize by design: the
measurement correlates Cortex events by **time window**, which cannot separate two concurrent
runs.

### 3.5 Reading the report

```bash
autobench-modelskill report                            # default out/modelskill
autobench-modelskill report --out out/runs --task xlsx-fin-font-clean --arms on
autobench-modelskill report --scenario A               # the cache-billing upper bound
autobench-modelskill report --json                     # machine-readable
```

`report` never invokes anything, so it is free to re-run and free to re-slice. It prints, in
order:

| Block | What it is for |
|---|---|
| **membership** | every file the numbers came from, with row counts and a sha256 prefix. Labeled UNPINNED, because it is whatever is on disk now — the frozen-manifest ceremony is for the *published* grid (§11) |
| **VOLUME** | `llm_calls`, `tool_calls`, tokens, and tokens per call. **These, and only these, decide whether a cell reproduced** |
| **COST** | per tier, per task and per *solved* task, under one named cache scenario |
| **LATENCY** | `api_s` from the CLI result event; `wall_s` beside it, labeled a diagnostic |
| **SKILL EFFECT** | ON ÷ OFF for the same task and model — what the skill costs, and what it bought |
| **COLD-CACHE** | repetitions whose cache tier split is an outlier *within their own cell*, named and not dropped |
| **RANKING** | the best model per measure, followed by the reminder that a point estimate is not a finding |

A real slice, trimmed:

```
VOLUME -- workload measures. These, and only these, decide whether a cell reproduced.

task                   arm  model         n drop  pass    tokens    CV calls tok/call
xlsx-fin-font-clean    on   haiku-4-5    29    1  0.52   222,327  0.66     6   37,054
xlsx-fin-font-clean    on   opus-5        5    0  1.00   277,638  0.08     8   34,705
xlsx-fin-font-clean    on   sonnet-4-6    8    0  1.00   343,513  0.18     9   38,168
xlsx-fin-font-clean    on   sonnet-5     11    0  1.00   485,797  0.94    10   48,580
```

Note the shape of that table rather than its winners: `tok/call` varies by ~40% across these
models while the **total** varies by 2.2×, because the total is `tok/call × calls` and it is
the *call count* that moved. A single "tokens" number would have hidden which term did the
work. Note also `drop 1` — a confounded repetition, excluded from every figure in the row.

Two things the report will not let you do:

- **Quote a wall-clock difference as a latency result.** Wall time moved ×1.34–1.81 for two
  models doing provably identical work, purely from machine load. The column is printed
  because it is real, and labeled because it is not evidence.
- **Read a dash as a zero.** A repetition recorded before the CLI `result` event was
  persisted has no api timing, so the cell prints `-` and the footer counts how many rows
  were timed (`3/11`). A missing measurement is never averaged in as a fast one.

### 3.6 The three measures, and why they are three

| Measure | Column | Binding when |
|---|---|---|
| **Token efficiency** | `tokens`, `tok/call`, `tok/solved` | a context window, a rate limit, or latency is the constraint |
| **Cost efficiency** | `$/task`, `$/solved` | you are paying the bill |
| **Latency** | `api_s`, `ttft_s`, `api_s/call` | someone is waiting for the answer |

They are not interchangeable, and the rankings genuinely invert. Unit price spans **5×** across
these models while token counts spread only about **2×**, so on `cortex-pyfix-001`:

| Model | tokens/solved | rank | $/solved | rank |
|---|---|---|---|---|
| `opus-5` | 144,834 | **1st** | 0.1030 | **4th** |
| `haiku-4-5` | 204,034 | **4th** | 0.0313 | **1st** |

`opus-5` is the most token-efficient and the least cost-efficient model tested. Both
`/solved` columns divide by pass rate, which charges a model for its failures — rank on raw
tokens and you can pick exactly the wrong model.

Money is always recomputed by `pricing.py` from the four token tiers, never scaled from a
token ratio, and never taken from the CLI's own `total_cost_usd` (that is the CLI's estimate
at *its* list prices, not your gateway's).

### 3.7 Significance, before you quote a gap

`--significance` runs an **exact two-sided permutation test** on per-repetition cost, the same
code path as the published table:

```
  cell                         a           b            n     gap      d       p   floor    80%  verdict
  xlsx-fin-font-clean/on       opus-5      sonnet-4-6 5v8  -28.7%   2.03   0.007   0.001      4  ESTABLISHED
  xlsx-fin-font-clean/on       opus-5      sonnet-5  5v11   -5.5%   0.08   0.919   0.000   2617  NO EVIDENCE either way
```

Three things to read, all of which have burned this study:

1. **The floor.** It is the smallest p the design can produce — `2/252 = 0.008` at 5 v 5. A p
   equal to its floor means the groups separate completely *at the design's limit*; it is not
   a large-sample result.
2. **The `80%` column is conditional on the cell being stationary across sessions.** On
   `xlsx-fin-font-clean` that prescription was bought — the extra repetitions it asked for
   were purchased — and the gap **changed sign**. Re-measure before trusting it.
3. **An intractable test is skipped, not approximated.** The test enumerates every split, so
   29 v 11 is C(40,29) ≈ 2.3 billion of them. Past 200,000 splits the row says
   `exact test skipped` and prints the count. Substituting a sampled p under the same column
   heading would be a different estimator wearing the same label.

### 3.8 Benchmarking a skill of your own

The measurement machinery is model-agnostic and skill-agnostic; the hard part is the **task**.
Full recipe in §9, but the order is not optional:

```bash
# 1. write tasks/<id>/ -- prompt.md, workspace/, verdict/, meta.json  (§6, §9)

# 2. GATE: does the agent already do it without the skill?
autobench-modelskill screen --pattern '<id>' --arm off --reps 3
#    passes unaided  -> the task measures the model, not the skill. Discard it.
#    fails every time -> keep

# 3. confirm the treatment actually arrived: skill_on_wire must be true on the ON arm
autobench-modelskill run --task <id> --arm on --reps 3

# 4. only now buy repetitions across models
autobench-modelskill compare --task <id> --models ... --arms on,off --reps 5
```

Step 2 is the whole study in miniature. The convention under test must be **arbitrary, not
good practice** — good practice is what the model already does, so the skill has nothing to
show. Nine of the first eleven tasks died at this gate, and they are in `tasks-retired/` with
the reason.

### 3.9 Full syntax

```
autobench-modelskill <command> [flags]

doctor                       every prerequisite; exit 1 on a blocker
tasks    [--retired]
models
screen   --pattern GLOB [--arm off|on|select] [--reps N] [--model M] [--out DIR] [--dry-run]
run      --task ID|PATH [--arm on|off|select] [--model M] [--reps N] [--out DIR] [--dry-run]
compare  --task ID [--task ID ...] --models M1,M2 [--arms on,off] [--reps N]
                  [--scenario A|B] [--significance] [--out DIR] [--dry-run]
report   [--task ID ...] [--arms A,B] [--models M1,M2] [--scenario A|B]
                  [--significance] [--json] [--out DIR]
```

| Flag | Default | Note |
|---|---|---|
| `--out` | `out/modelskill` | kept outside `profile.RUN_DIRS` so `--freeze` cannot publish it. The run lock stays global either way |
| `--reps` | 5 (`run`, `compare`), 3 (`screen`) | fewer than 3 is flagged before anything is spent: medians over 2 repetitions are the repetitions |
| `--model` | `claude-sonnet-4-6` | always pinned explicitly; the row carries `model_pin_honoured` |
| `--arms` | `on,off` | for `compare`. The control is what makes the treatment mean anything |
| `--scenario` | `B` | `B` applies cache discounts; `A` prices every prompt token at the input rate — an upper bound. Which one your gateway bills is an assumption, so it is named in the output |
| `--significance` | off | exact permutation tests between models, with floors |
| `--dry-run` | off | print the plan and the exact commands; invoke nothing |

Everything above is a wrapper. `harness.py`, `sweep.py` and `profile.py` remain the
developer-facing entry points and are documented in §10.

---

## 4. Repository map

| Path | What |
|---|---|
| `bin/autobench-modelskill` | the consumer CLI (§3). Plans repetitions, then compiles token/cost/latency. A script, not a package — see §2.5 |
| `harness.py` | the driver. One task → fresh workspace → `claude -p` → verdict → correlate Cortex → one NDJSON row |
| `sweep.py` | a set of tasks through one arm as a matrix |
| `profile.py` | the model grid: `--run` invokes, `--report` recompiles from stored runs with no invocations, `--freeze` publishes membership |
| `pricing.py` | the internal LiteLLM rate card, hand-maintained on purpose |
| `lib_child.py` | builds the sanitized child environment |
| `tasks/` | 7 active tasks |
| `tasks-retired/` | 9 discarded tasks, each with a `DISCARDED.md` stating why. **A discarded task is a result** |
| `tools/` | task generators plus the controls and analysis tools |
| `tests/` | 48 tests guarding the confound detector, workspace setup, the result-event whitelist and the CLI's reporting |
| `results/` | `EVALUATION.md`, the frozen manifest, the cost-profile artifacts, the generated deck |
| `out/` | **gitignored.** Per-run NDJSON and the raw SSE capture, which contains full prompts |
| `out/modelskill/` | where the CLI writes by default — outside `profile.RUN_DIRS`, so consumer runs cannot join the published grid |

---

## 5. The data path, end to end

One call to `run_rep` (`harness.py:362`), in order. The order is load-bearing in three
places, each flagged below.

1. **`fresh_ws`** (`harness.py:264`) copies `tasks/<id>/workspace/` to a new temp dir with
   `copytree`, ignoring `__pycache__`, `.pytest_cache`, `*.pyc`, `.venv`, `venv`.
2. **`test_hashes`** takes a sha256 of every `test_*.py` now present. ⚠️ **Order matters:**
   this snapshot must precede step 8.
3. **Baseline** — for a task with in-workspace tests, `pytest` must *fail* here. A suite
   that already passes means there is nothing to measure (`baseline_ok`). Hidden-verdict
   and selection tasks have no in-workspace baseline and are exempt.
4. **Child environment** (`child_env`, plus the extras at `harness.py:379`) — proxy vars,
   the Cortex CA for Node, the curated `CLAUDE_CONFIG_DIR`, bundled skills off, the venv
   on `PATH`.
5. **Arm shaping** (`harness.py:391`) — prefix the prompt with `/<skill>` on the `on` arm,
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

- **`RunLock`** (`harness.py:102`) serializes harness runs on the machine, waiting up to two
  hours. Cortex events are correlated by *time window* against a single shared proxy, so
  concurrent runs interleave — a smoke test once absorbed a sweep's events and was flagged
  `multiple_models`. The detector caught it; the lock makes the overlap impossible instead
  of merely detectable. **Never run two harness processes at once.** Interactive Claude Code
  on the same machine is safe because it has no `HTTPS_PROXY` and stays out of the window.
- **`Capture`** (`harness.py:143`) owns the SSE tail. Cortex's session store is in-memory
  with a 30-minute TTL, so the file on disk is the only durable record. A dead capture
  yields zero events, which is indistinguishable from "the proxy saw nothing" — so the
  harness starts it, proves it is producing, and stops it. An existing capture is adopted
  rather than duplicated.

---

## 6. Inputs

### 6.1 Task directory anatomy

```
tasks/<task-id>/
  prompt.md          required   the verbatim prompt (minus any arm prefix)
  workspace/         required   copied fresh into a temp dir every repetition
  meta.json          optional   skill, marker, mode, allowed-tool extras
  verdict/           optional   HIDDEN tests, installed only after the agent exits
```

Parsed by `load_task` (`harness.py:222`).

### 6.2 What the workspace contains — and usually does not

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

### 6.3 Who supplies the content, and who supplies the formatting

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

### 6.4 The prompt contract

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

### 6.5 The three arms

| Arm | Prompt | `--allowedTools` | Skills in config dir | Role |
|---|---|---|---|---|
| `on` | prefixed `/<skill>` | baseline + `Skill` | exactly the task's skill | treatment |
| `off` | unmodified | baseline | none | **control** |
| `select` | unmodified, names no skill | baseline + `Skill` | all `candidate_skills` | a different benchmark |

`select` asks a different question — not "does the skill improve compliance" but "does the
model reach for the right skill unprompted." It is scored from the transcript, not by
pytest.

### 6.6 Skill isolation

`main` builds a curated `CLAUDE_CONFIG_DIR` (`harness.py:593`) containing a `skills/`
directory holding **exactly the task's skill, or nothing at all**, copied from
`~/.claude/skills/<name>`, with `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`.

The consequence is the point: any *other* skill appearing in the transcript is a confound
by construction, not by judgment.

Note it is `CLAUDE_CONFIG_DIR` that scopes user skills — **not `HOME`**. That was
established by measurement, and getting it wrong silently leaks the real skill library into
the control arm.

### 6.7 The exact invocation

```
claude -p <prompt> \
       --add-dir <ws> \
       --model <model> \
       --allowedTools "Read Edit Write Bash(python*) Bash(pytest*)" [+ task extras] \
       --output-format stream-json --verbose
```

run with `cwd=ws` and the sanitized environment from §5, step 4.

- The tool allow-list is deliberately narrow. `meta.json` may add to it via
  `allowed_tools_extra` — the docx skill mandates a Node library, so without
  `Bash(node*)`/`Bash(npm*)` the agent silently falls back to `python-docx` and the
  harness would measure the fallback rather than the skill.
- The model is **pinned explicitly**. Inheriting it is unsafe: `ANTHROPIC_MODEL` in the
  ambient environment differed from `settings.json`, so comparisons drifted silently.
  `--model` beats both, and `model_pin_honoured` verifies on the wire that it took.
- `--output-format stream-json --verbose` is what makes the transcript machine-readable.

### 6.8 `meta.json` keys

| Key | Meaning |
|---|---|
| `skill` | skill name; enables the `on`/`off` contrast. Absent ⇒ a no-skill task |
| `skill_marker` | a distinctive phrase from the skill's `SKILL.md`, matched on the wire |
| `mode` | `"compliance"` (default) or `"selection"` |
| `expected_skill` | selection mode: the correct skill, or `null` for the negative case |
| `candidate_skills` | selection mode: what to make available |
| `allowed_tools_extra` | additional `--allowedTools` entries |

---

## 7. Evaluation

The verdict is a conjunction over independent evidence streams. Each exists because the
others can be fooled.

### 7.1 Stream 1 — artifact correctness, by pytest

`pytest -q` runs in the workspace under the repo venv (`pytest_run`, `harness.py:281`),
after the agent has exited.

**What the evaluator sees is only the artifact.** It opens the single `.xlsx` the agent left
in the workspace — via `openpyxl`, exactly as any downstream consumer would — and asserts
against it. It reads no transcript, no prompt, and no intermediate script; it does not know
which arm or model produced the file, and it has no channel through which it could. Zero or
several `.xlsx` files is a loud failure rather than a guess about which one to grade. Where
that file came from is §6.3.

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

### 7.2 Stream 2 — tamper check

sha256 of every `test_*.py` before and after the agent runs, snapshotted before the hidden
verdict arrives (§5, steps 2 and 8).

```python
passed = (rc1 == 0) and tests_untouched
```

Editing the tests green fails the repetition. Green pytest alone is not a pass.

### 7.3 Stream 3 — attribution, from the transcript and the wire

`analyse_transcript` (`harness.py:290`) walks the stream-json and collects `tool_use`
blocks: `tools`, `skills`, `skill_names`, `subagents`, `background`, `assistant_turns`.

The transcript has a blind spot that the wire covers. **An explicit `/skill-name` is
expanded client-side into the prompt and produces no `tool_use` at all**, so the transcript
*cannot* confirm the skill was applied. Hence `skill_on_wire`: the task's `skill_marker` is
matched against `inference.messages` on request-phase Cortex events, in memory, and **only
a boolean escapes** — those messages are the full prompt and the session API is
unauthenticated.

Conversely, a `Skill` tool_use means the *model* reached for a skill itself, which is the
measurement in `select` mode and a confound in compliance mode.

### 7.4 Selection scoring

No pytest at all. `selection_correct` is derived from which skills fired:

```python
if expected_skill is None:   selection_correct = not fired      # negative case
else:                        selection_correct = expected_skill in fired
passed = bool(selection_correct)
```

The negative case (`select-none`) matters: an over-eager selector is as wrong as a blind
one, so a selection benchmark that tests only true positives is half a benchmark.

### 7.5 Confounds — void, not failed

A repetition can be **invalid** rather than **failed**, and conflating the two biases every
median. Detectors (`harness.py:490` onward):

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

### 7.6 The gate upstream of everything

**Every task is pre-screened on the `off` arm.** A task the agent passes *without* the
skill is not measuring the skill and must be discarded. 9 of 11 candidates died at this
gate and live in `tasks-retired/`, each with a `DISCARDED.md`.

---

## 8. The measurement side

Tokens, `llm_calls`, and `skill_on_wire` come from correlating Cortex SSE events by time
window (`harness.py:446`) — nothing else in the row provides them. `tool_calls` and
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

## 9. Adding a task

1. **Write `prompt.md`** as a plain business request with concrete numbers. Do not name the
   convention you intend to test (§6.4).
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

## 10. Command reference

Setup is §2; the consumer-facing CLI is §3. What follows is the developer surface underneath
it. Cortex must be reachable either way — session API on `127.0.0.1:47601`, proxy on `47600`
— and `harness.py` exits early if it is not.

| Command | Effect |
|---|---|
| `autobench-modelskill doctor` | check the whole rig before spending anything (§3.1) |
| `python3 harness.py tasks/cortex-pyfix-001 --reps 3` | the canary: proves the rig works |
| `python3 harness.py tasks/<id> --arm off --reps 3` | pre-screen a candidate task |
| `python3 harness.py tasks/<id> --model claude-sonnet-5 --out out/scratch` | one cell, output redirected |
| `python3 sweep.py --arm off --reps 3 --pattern 'xlsx-*'` | a task set through one arm; `--out` to redirect |
| `python3 profile.py --run --reps 5` | the grid: **invokes**, costs money |
| `python3 profile.py --report` | recompile from stored runs, **no invocations** |
| `python3 profile.py --freeze` | publish membership to the manifest |
| `python3 profile.py --report --all` | ignore the manifest, glob everything; labels itself |
| `.venv/bin/python tools/cost_significance.py` | which cost gaps are established |
| `.venv/bin/python tools/stability_probe.py --task <id>` | which cells reproduce across sessions |
| `.venv/bin/python tools/make_summary_deck.py` | regenerate the deck |
| `.venv/bin/python -m pytest -q` | 48 tests |

`harness.py` flags: `--reps`, `--out` (default `out/runs`), `--arm {on,off,select}`,
`--model`.

Use `.venv/bin/python`, not `python3`, for anything needing `openpyxl` or `pptx`.

---

## 11. Membership and the freeze workflow

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

## 12. The NDJSON row

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

**Client-side timing** — `cli_duration_ms`, `cli_duration_api_ms`, `cli_ttft_ms`,
`cli_ttft_stream_ms`, `cli_time_to_request_ms`, `cli_num_turns`, `cli_total_cost_usd`,
`cli_usage`

That group comes from the CLI's own `result` event and is a **different instrument** from the
Cortex columns beside it — what the client believed happened, counted before the request left
the machine. Two consequences worth knowing:

- It is the only measurement in the row that **survives the proxy being absent**, and
  `cli_duration_api_ms` is the only timing here that is not wall-clock: it excludes local tool
  execution, which `wall_seconds` cannot separate. That is what makes latency answerable
  (§3.6).
- `cli_total_cost_usd` is the **CLI's** estimate at *its* list prices, not your gateway's.
  Money still comes from `pricing.cost()`.

The same whitelist discipline applies, and here it is not a formality: the result event also
carries `result` — the final assistant text — and a nested `modelUsage`. `cli_usage` keeps
only integer-valued keys, a shape filter rather than a key list, because `usage` gains nested
sub-objects across CLI versions. Absent (timed out, killed, or an older CLI) means every key
is present and `None`, never 0. Rows recorded before this was persisted have no `cli_*` fields
at all, and the report renders that as a dash.

---

## 13. Invariants

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
14. **Exploratory runs stay outside `profile.RUN_DIRS`.** That tuple is what `--freeze` globs.
    One ad-hoc canary repetition landing in it moved a published cell from n=10 to n=11 and
    changed its median. The CLI defaults to `out/modelskill` for this reason, and a test pins
    it there.

---

## 14. Debugging

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
| the `api_s` column is all dashes, `timed 0/n` | those rows predate `cli_*` being persisted. Re-run to measure latency; a dash is a missing measurement, not a zero |
| `report` says "none reportable" and exits 1 | every cell failed a token identity and was quarantined. Read the `QUARANTINED` lines — do not average what is left |
| `doctor` warns `target host … ANTHROPIC_BASE_URL unset` | the harness cannot filter Cortex events by host, so any other traffic in the window joins the row |

---

## 15. Security

- `out/` is gitignored: the SSE capture contains raw prompts.
- Persisted Cortex fields are a whitelist, not a blacklist.
- `skill_on_wire` matches in memory and emits only a boolean; the marker is never stored
  alongside the messages it matched.
- The Cortex session API is unauthenticated on localhost. Treat everything it returns as
  sensitive.
- See invariant 12 for the credential-handling rule.
