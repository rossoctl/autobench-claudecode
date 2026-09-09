# AutoBench for Claude Code

Automated benchmarking for Claude Code. The **subject under test is the Claude Code agent
itself**: a benchmark run is a set of tasks, each task is one headless `claude -p` session
in a fresh workspace, scored by a programmatic verdict.

There is no LLM judge. A task passes when a command exits 0 — that is the whole point, and
it is what separates a benchmark from a load generator.

## What measures what

| Concern | Source |
|---|---|
| Did it work? | the verdict command's exit code (`pytest -q`) |
| Tokens, latency, cache tiers | [Cortex](https://github.com/rossoctl/cortex) on the wire |
| Which tools/skills/subagents actually ran | the `stream-json` transcript |

Tokens come from the wire and attribution from the transcript, because neither source can
answer the other's question. Cortex sees bytes but not which local tool ran; the transcript
sees tool calls but not tokens.

## Requirements

- `claude` CLI, authenticated.
- A running Cortex proxy in **forward + `tls_bridge`** mode. This is the only shape that
  dispatches the inference parsers — the reverse role records events with `plugins=[]`.
- Python 3.12+.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
abctl service start                     # Cortex, on 47600/47601
```

## Run

```bash
python3 harness.py tasks/cortex-pyfix-001 --reps 3
python3 sweep.py --arm off --reps 3 --pattern 'xlsx-*'   # control
python3 sweep.py --arm on  --reps 3 --pattern 'xlsx-*'   # skill available + invoked
```

Output lands in the gitignored `out/`: one NDJSON row per repetition, plus the Cortex SSE
capture. Cortex's session store is in-memory with a 30-minute TTL, so the harness starts
and stops that capture itself — the file on disk is the only durable record.

## Task layout

```
tasks/<task-id>/
  prompt.md          the request, verbatim, as a user would phrase it
  workspace/         copied fresh per repetition
  verdict/           OPTIONAL: hidden tests, installed only AFTER the agent exits
  meta.json          OPTIONAL: {"skill": "...", "skill_marker": "..."}
```

**`workspace/` vs `verdict/` is the most important design choice in a task.**

- Tests in `workspace/` are **visible** to the agent. Correct when the tests *are* the
  spec — "make this failing suite pass" (`cortex-pyfix-001`).
- Tests in `verdict/` are **hidden**, installed only after the agent exits. Required for
  *compliance* tasks, where the test enumerates the conventions being checked. Leave such a
  test visible and the agent simply reads it and complies, so the skill-on and skill-off
  arms both pass and the task measures nothing except "can you read a test".

## Two rules a task must satisfy

**1. The verdict must be tamper-proof, not merely green.** A pass requires the verdict to
exit 0 **and** every `test_*.py` to be byte-identical to what shipped. Deleting the test,
or rewriting it to assert the buggy behaviour, also makes `pytest` green.

**2. A skill task must be pre-screened on the OFF arm, and discarded if it passes.** A task
the agent already passes *without* the skill is not measuring the skill. This is not
hypothetical: **9 of the first 11 tasks written have been discarded this way.**
`claude-sonnet-4-6` already writes `=prev*(1+$cell)` instead of hardcoding a growth rate,
already applies `$#,##0`/`0.0%`/`0.0x` unprompted, and already builds real bulleted lists
and a sensible slide size hierarchy.

Discarded tasks are kept in `tasks-retired/` with the reason recorded, because **a discarded
task is a result** — it tells you where the model is already competent. Run
`sweep.py --arm off` before ever believing an ON arm.

### Pick arbitrary conventions, not good practice

The single best predictor of whether a compliance task will discriminate: is the rule
**house-specific and arbitrary**, or is it **objectively better practice**? A capable model
already does good practice unprompted, so rules of the second kind cannot separate the arms.

Measured across 11 tasks and three skills:

| Skill | Rule kind | Outcome |
|---|---|---|
| `xlsx` | investment-banking colour coding (blue = hardcoded input) | **discriminates** 0/3 → 3/3 |
| `xlsx` | professional font, no formula errors | **discriminates** 0/3 → 3/3 |
| `xlsx` | `$#,##0` / `0.0%` / `0.0x`; assumptions as cell refs | passes unaided — discarded |
| `docx` | real bullets, US Letter, DXA table widths | passes unaided — discarded |
| `pptx` | size hierarchy, non-text-only slides | passes unaided — discarded |

Blue-for-inputs is an arbitrary banking convention with no general-purpose reason to prefer
it, so the model does not volunteer it. "Use real list numbering instead of typing a bullet
character" is simply correct, so it does.

A second trap the `docx` rules exposed: they are **path-dependent**. They exist to correct
footguns in docx-js, the library the skill itself mandates — A4 defaults, percentage table
widths. The unaided agent reaches for python-docx, whose defaults already satisfy all three,
so it never meets the footgun. Testing such a rule requires forcing the same library in both
arms, which is a different experiment.

### Following a skill is not free

Skill-on cost, same tasks, same model:

| Skill | tokens OFF → ON | wall OFF → ON | verdict change |
|---|---|---|---|
| `xlsx` | 167k → 185k (+10%) | 82s → 80s | **0/3 → 3/3** |
| `docx` | 160k → 1.03M (**6.5×**) | 27s → 501s (**18×**) | none (both pass) |
| `pptx` | 132k → 2.34M (**18×**) | 35s → 393s (**11×**) | none (both pass) |

The docx and pptx skills route through Node toolchains (docx-js, pptxgenjs) with npm
installs and LibreOffice validation loops. That is a real cost worth knowing about, but it
says nothing about whether the resulting document is *better* — these verdicts only check
the rules they check, and both skills' main promise is visual quality, which is deliberately
outside a programmatic verdict.

## Skill selection (a different benchmark)

`--arm select` makes every candidate skill available, does **not** name one in the prompt,
and scores "did the right skill fire" from the transcript. This is the one place the
transcript is authoritative: a *model-selected* skill is a real `Skill` tool call, whereas an
explicit `/skill-name` is expanded client-side and never appears.

```bash
python3 sweep.py --arm select --reps 3 --pattern 'select-*'
```

A negative case is mandatory. Measuring only true positives rewards a model that fires a
skill on everything, so `select-none` is an ordinary Python bugfix where the correct
behaviour is to invoke nothing.

Result on `claude-sonnet-4-6`, four candidate skills available (`xlsx`/`docx`/`pptx`/`pdf`),
n=3 each — **12/12 correct, 0 confounded**:

| task | expected | fired |
|---|---|---|
| `select-spreadsheet` (names the artifact) | `xlsx` | `xlsx` ×3 |
| `select-deck` (names the artifact) | `pptx` | `pptx` ×3 |
| `select-implicit-sheet` (never says "spreadsheet") | `xlsx` | `xlsx` ×3 |
| `select-none` (plain bugfix) | *nothing* | nothing ×3 |

Selection is reliable, including the implicit case and with no false positives. The obvious
consequence: these four tasks are now **too easy to discriminate anything**, so extending
this arm means genuinely ambiguous prompts, not more clear ones.

## Comparing models

Pin with `--model`; the pin is verified against what Cortex saw on the wire. `profile.py`
runs a grid and compiles a cost profile; `--report` recompiles from stored runs with no
invocations, so the analysis is never coupled to a multi-hour run.

```bash
python3 profile.py --run --reps 5      # the grid
python3 profile.py --report            # recompile only
```

Full output: [`results/xlsx-cost-profile-20260908.txt`](results/xlsx-cost-profile-20260908.txt)
— four models on the two `xlsx` discriminators plus the no-skill canary.

### Pass rate ranks models — a prediction of mine that was wrong

I expected pass rate to be useless here: the OFF arm is pinned at 0 by the pre-screen and
the ON arm at 100 because the skill states the answer. That held for the two mid-tier models
it was observed on, and **broke as soon as the tiers widened**:

| | OFF | ON |
|---|---|---|
| `haiku-4-5` | 0.00 | **0.40** ← does not reliably comply even when told |
| `sonnet-4-6` | 0.00 | 1.00 |
| `sonnet-5` | 0.00 | 1.00 |
| `opus-5` | **0.20** ← sometimes knows the convention unaided | 1.00 |

(`xlsx-fin-font-clean` ON for haiku; `xlsx-fin-colors` OFF for opus-5.) So a compliance task
does have resolution — just not between models that both sit above the ceiling.

### tokens/call is a model constant; call count is not

Ratio vs `sonnet-4-6`, across five structurally different cells:

| model | spread across cells | reading |
|---|---|---|
| `haiku-4-5` | 0.97–1.05, **spread 0.07** | ≈ same per-call context |
| `sonnet-5` | 1.19–1.30, **spread 0.11** | **≈1.23× more** per call |
| `opus-5` | 0.89–0.97, **spread 0.08** | **≈0.90× — leaner** per call |

Per-call context is stable enough to budget with. **Call count is not**: it swings 0.40–1.00×
for haiku and 0.83–2.00× for opus-5 depending on the task. So decompose — the constant term
is the model, the variable term is the work.

### Cost per solved task, which inverts the naive assumption

`median tokens ÷ pass rate`, so a model that fails is charged for its failures:

| task | haiku-4-5 | sonnet-4-6 | sonnet-5 | opus-5 |
|---|---|---|---|---|
| `xlsx-fin-colors` (ON) | **192,703** | 257,611 | 573,855 | 284,825 |
| `xlsx-fin-font-clean` (ON) | 395,968 | 350,461 | 446,052 | **277,638** |
| `cortex-pyfix-001` | 204,034 | 195,868 | 200,732 | **144,834** |

`opus-5` is the **cheapest** on two of three and `sonnet-5` the dearest on two of three —
bigger is not more expensive here. And haiku on `font-clean` shows why the denominator
matters: its raw token count is the lowest of all four (158k), but at a 0.40 pass rate its
cost per *solved* task is worse than sonnet-4-6's. Ranking on raw tokens would have picked
exactly the wrong model.

### The skill is nearly free on opus-5 and expensive on haiku

Skill-on ÷ skill-off tokens:

| task | haiku-4-5 | sonnet-4-6 | sonnet-5 | opus-5 |
|---|---|---|---|---|
| `xlsx-fin-colors` | 2.88× | 1.50× | 2.01× | **0.93×** |
| `xlsx-fin-font-clean` | 2.37× | 2.08× | 1.56× | **1.01×** |

So "what does this skill cost" has no single answer — it is a property of skill × model.
`opus-5` absorbs it for free, largely because it already works harder on the OFF arm (2.0×
the calls), so the skill adds guidance rather than effort.

Cache reads are 81–97% of prompt tokens across every model and cell, highest on `sonnet-5`
and `opus-5` (95–97%).

**No dollar figures anywhere.** Cortex leaves `costMicros` unpopulated (`priced:false`, an
in-tree TODO), so any price would be one we invented. Tokens are split by tier — apply your
own rates.

## Concurrency

Runs hold an exclusive lock (`out/.harness.lock`). Cortex events are correlated by **time
window** against one shared proxy, so two overlapping runs interleave — a smoke test run
beside a sweep picked up the sweep's events and was flagged `multiple_models`. The detector
caught it; the lock makes it impossible. Interactive Claude Code on the same machine is
still safe, because it has no `HTTPS_PROXY` and so never enters the window.

## Isolation, and why it is per-invocation

Everything is passed to the child process, so your own `~/.claude/settings.json` is never
modified and interactive Claude Code use is unaffected. One Cortex sees *all* traffic on the
machine, so a global wiring would let interactive typing pollute a benchmark window.

| Lever | Effect |
|---|---|
| `HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS` | route this child through Cortex |
| `CLAUDE_CONFIG_DIR` | scope which **user** skills exist — **not** `HOME`, which is not the lookup root |
| `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1` | drop the skills bundled into the binary (a separate population) |
| `--model` | pin the model; it beats both the environment and `settings.json` |

The model is pinned and then **verified on the wire**, because the model actually used can
come from an ambient `ANTHROPIC_MODEL` that disagrees with `settings.json`. A run whose
observed model differs from the requested one is flagged, not silently averaged in.

## Confounds

A repetition is flagged `confounded` rather than quietly averaged when the invoked set
exceeds what the task intends: a **foreign** skill, any **subagent** (`Task`), a missing
expected skill on the wire, skill text leaking into the OFF arm, a model-pin mismatch, or
no Cortex events at all.

Two subtleties learned the hard way:

- An explicit `/skill-name` produces **no `Skill` tool_use** — the CLI expands it into the
  prompt client-side. So the transcript cannot confirm an explicitly-requested skill was
  applied; that is checked on the wire via a marker phrase from its `SKILL.md`. The
  transcript still catches the confounder that matters, a *model-selected* skill.
- A `Skill` call for the task's **own** skill is benign, not a confound.

## Interpreting results

- **Pass rate is primary.** The ON arm carries ~1 kB of injected `SKILL.md` and may pull in
  the skill's scripts, so the arms are **not token-comparable by construction**. Answering
  "is the skill's guidance efficient?" needs a third, token-matched arm.
- **Report medians and CV over repetitions.** This subject is not deterministic. Pinning the
  model removes much of the drift but not all of it.
- **Cache reads dominate.** Measured on real runs: 10–14 *uncached* input tokens against
  112k–192k cache reads, i.e. 79–97% of prompt tokens. Reporting "input tokens" alone for
  this workload is meaningless.

### Report tokens per LLM call, not just totals

A skill's token cost is a property of **skill × task**, not of the skill. Measured across
both surviving tasks with the *same* `xlsx` skill:

| task | tokens/call OFF → ON | llm calls OFF → ON | total |
|---|---|---|---|
| `xlsx-fin-colors` | 33,568 → 36,977 (**+3,409**) | 5 → 5 (+0%) | **+10%** |
| `xlsx-fin-font-clean` | 33,482 → 36,805 (**+3,323**) | 5 → **10** (+100%) | **+120%** |

The per-call increase is a near-constant ~3.3–3.4k, matching the injected `SKILL.md`
(~2,865 tokens). The entire difference between +10% and +120% is **call count** — the skill
made the agent do twice as much work on one task and no extra work on the other.

So a bigger skill bundle is *not* inherently more expensive: only 1 of 6 skill-on runs read
anything from the skill's 54-file `scripts/` directory. Compare **tokens per call** to see
the skill text, and **call count** to see the behavioural cost. Comparing raw totals across
skills measures task shape instead.

## Security

`out/` is gitignored and must stay that way. The Cortex session API is **unauthenticated**
and its events carry `inference.messages` and `inference.completion` — full prompts and
model output. The NDJSON therefore stores a **field whitelist**; skill verification matches
its marker in memory and emits only a boolean.

## License

Apache 2.0 — see [LICENSE](LICENSE).
