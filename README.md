# AutoBench for Claude Code

Automated benchmarking for Claude Code. The **subject under test is the Claude Code agent
itself**: a benchmark run is a set of tasks, each task is one headless `claude -p` session
in a fresh workspace, scored by a programmatic verdict.

There is no LLM judge. A task passes when a command exits 0 — that is the whole point, and
it is what separates a benchmark from a load generator.

For the mechanics — the data path through a repetition, what supplies a task's inputs, how
the verdict is scored, the invariants, and how to add a task — see
[`docs/DEVELOPER-GUIDE.md`](docs/DEVELOPER-GUIDE.md).

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
| `pptx` | 164k → **bimodal, see below** | 32s → 235s (**7.4×**) | none (both pass) |

⚠️ **`pptx` has no single honest overhead number, and two earlier attempts to give one were
wrong.** It was first published as 18×, then corrected to 3.0×. Both were artifacts of
membership. The ON arm is *bimodal* — six repetitions per task split three-low / three-high:

| task | ON-arm total tokens, sorted |
|---|---|
| `pptx-body-left-aligned` | 207k, 254k, 663k ┆ 1234k, 1278k, 1324k |
| `pptx-size-contrast` | 364k, 380k, 603k ┆ 1275k, 2338k, 2541k |

Against a 164k OFF median that is **≈2.3× in the low mode and ≈7.9× in the high mode**. The
median of six lands in the empty gap *between* the modes, so it is the least stable statistic
available here — which is how one membership change moved it from 18× to 3.0×. With n=6 we
cannot say how often each mode occurs, so we quote the two modes and not an average.

The 3.0× specifically came from excluding the repetitions that used a background task
(`TaskOutput`). **That exclusion was invalid** and has been reverted: a background task here is
a background *shell* command, which issues no LLM calls of its own, so its tokens still belong
to the loop being measured. Empirically too — in both tasks the single most expensive
repetition carries *no* background tool (1324k vs 1278k; 2541k vs 1275k), so the flag marked a
subset of the high mode rather than a cause of it. Only a genuine subagent spawn (`Agent`)
remains a confound; see "Downstream LLM calls" below.

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

## Deliverables

| Document | Contents |
|---|---|
| [`results/EVALUATION.md`](results/EVALUATION.md) | Full evaluation: terms, setup + rationale, pricing, methodology, all findings, model recommendation, limitations |
| [`results/autobench-claudecode-summary.pptx`](results/autobench-claudecode-summary.pptx) | 19-slide summary of the same material, contents on slide 2 (regenerate: `tools/make_summary_deck.py`) |
| [`results/xlsx-cost-profile-20260909.txt`](results/xlsx-cost-profile-20260909.txt) | Raw compiled profile output — **current**. 18 cells at n=5, the 2 pass-rate discriminators at n≈30; read the `n` column |
| [`results/xlsx-cost-profile-20260908.txt`](results/xlsx-cost-profile-20260908.txt) | The earlier flat-n=5 snapshot, kept for comparison. Reproducible only from the manifest as it stood at commit `f00124a` — `--report` today reads the current manifest and will not regenerate it |

Two analysis tools recompute the statistical claims from the frozen manifest, so no significance
figure in the evaluation is ever retyped:

```bash
python3 tools/cost_significance.py   # which cost gaps are established: exact permutation tests
python3 tools/stability_probe.py     # which cells reproduced across sessions (pyfix yes, font-clean no)
```

### Monetary cost

`pricing.py` holds the internal LiteLLM rate card, transcribed by hand from the gateway's
model pages (`/ui/?page=models`) and dated. That page is behind an interactive internal
web-authorization flow and renders client-side, so there is nothing for a benchmark
credential to read — when rates change, edit `PRICES` and bump `SOURCE_DATE`.

| Benchmarked alias | Input $/1M | Output $/1M |
|---|---|---|
| `claude-haiku-4-5-20251001` | 0.76 | 3.80 |
| `claude-sonnet-4-6` | 2.28 | 11.40 |
| `claude-sonnet-5` | **1.52** | **7.60** |
| `claude-opus-5` | 3.80 | 19.00 |

`sonnet-5` is priced at **2/3 of `sonnet-4-6`**, which is how it can come out cheaper despite
using more tokens — but only where the token gap is small enough for the price gap to cover it.
Its point estimate is cheaper on two of the three cells measured, and **only one of those three
cells actually separates the two models**: the no-skill canary (29.9%, *p* = 0.008) — which is also
the one cell re-measured a day later, where it came back at 30.6%. On `xlsx-fin-colors` the two are
statistically indistinguishable (7.9% apart, *p* = 0.78, §7.3.1), and `xlsx-fin-font-clean` turned
out not to be stationary — re-run a day later it reversed sign for `sonnet-5` while `sonnet-4-6`
reproduced to within 3% (§7.3.2). `opus-5` is 2.5× `sonnet-5`.

**Cache pricing is the one unverified input.** The gateway publishes only Input and Output
rates while 81–97% of our prompt tokens are cache reads, so two scenarios are computed: **A**
bills every prompt token at the Input rate (upper bound), **B** applies the standard
`cacheRead ×0.10 / cacheWrite ×1.25` convention. B lands ~4–5× below A. **The top and bottom of
the ranking are identical under both** — `haiku-4-5` cheapest, `opus-5` dearest in every cell — so
the recommendation does not depend on resolving it. The *full* ordering is not identical: the two
sonnets change places on `xlsx-fin-colors`. That reads as a scenario-dependent answer but is
really an absent one, since neither ordering is statistically established in that cell. Confirm
against an invoice before quoting an absolute figure.

## Comparing models

Pin with `--model`; the pin is verified against what Cortex saw on the wire. `profile.py`
runs a grid and compiles a cost profile; `--report` recompiles from stored runs with no
invocations, so the analysis is never coupled to a multi-hour run.

```bash
python3 profile.py --run --reps 5      # the grid
python3 profile.py --report            # recompile only
```

Full output: [`results/xlsx-cost-profile-20260909.txt`](results/xlsx-cost-profile-20260909.txt)
— four models on the two `xlsx` discriminators plus the no-skill canary.

**The grid is deliberately uneven, so read the `n` column.** 18 cells sit at n=5; the two cells
whose pass rate is neither 0 nor 1 — `xlsx-fin-font-clean`/ON/`haiku` and
`xlsx-fin-colors`/OFF/`opus-5` — were taken to n≈30, because they are the only two where sampling
error could change a conclusion. Both rose (0.40→0.52, 0.20→0.37) and both 95% intervals roughly
halved. A uniform n=10 was considered and rejected: it costs ~$14 to tighten 16 cells that are
already saturated at 0 or 1.

### Pass rate ranks models — a prediction of mine that was wrong

I expected pass rate to be useless here: the OFF arm is pinned at 0 by the pre-screen and
the ON arm at 100 because the skill states the answer. That held for the two mid-tier models
it was observed on, and **broke as soon as the tiers widened**:

| | OFF | ON |
|---|---|---|
| `haiku-4-5` | 0.00 | **0.52** (n=29) ← does not reliably comply even when told |
| `sonnet-4-6` | 0.00 | 1.00 |
| `sonnet-5` | 0.00 | 1.00 |
| `opus-5` | **0.37** (n=30) ← sometimes knows the convention unaided | 1.00 |

(`xlsx-fin-font-clean` ON for haiku; `xlsx-fin-colors` OFF for opus-5.) So a compliance task
does have resolution — just not between models that both sit above the ceiling.

Those two bolded cells are the only rates in the profile that are neither 0 nor 1, so they are the
only ones sampling error could overturn — which is why they, and only they, were taken to n≈30.
Both rose (0.40→0.52, 0.20→0.37) and both 95% Wilson intervals roughly halved (to 0.34 and 0.33
wide). Neither reaches 0 or 1, so both readings above stand; the n=5 versions were pessimistic.

### Tokens per LLM call is a model constant; calls per task is not

`tokens per task = tokens per LLM CALL × LLM calls per task`. One task is one
`claude -p` run and makes **several** LLM calls (2–29 observed), each re-sending the
growing conversation — which is also why cache reads dominate.

Ratio vs `sonnet-4-6`, across five structurally different cells:

| model | spread across cells | reading |
|---|---|---|
| `haiku-4-5` | 0.95–1.04, **spread 0.09** | ≈ same context per LLM call |
| `sonnet-5` | 1.18–1.24, **spread 0.05** | **≈1.21× more** per LLM call |
| `opus-5` | 0.88–0.93, **spread 0.05** | **≈0.90× — leaner** per LLM call |

Per-call context is stable enough to budget with. **Call count is not**: it swings 0.40–1.00×
for haiku and 0.83–2.00× for opus-5 depending on the task. So decompose — the constant term
is the model, the variable term is the work.

### Cost per solved task, which inverts the naive assumption

`median tokens ÷ pass rate`, so a model that fails is charged for its failures:

| task | haiku-4-5 | sonnet-4-6 | sonnet-5 | opus-5 |
|---|---|---|---|---|
| `xlsx-fin-colors` (ON) | **192,703** | 266,640 | 565,306 | 284,825 |
| `xlsx-fin-font-clean` (ON) | 429,832 | 350,461 | 420,459 | **277,638** |
| `cortex-pyfix-001` | 204,034 | 196,634 | 200,732 | **144,834** |

`opus-5` is the **cheapest** on two of three and `sonnet-5` the dearest on two of three —
bigger is not more expensive here. And haiku on `font-clean` shows why the denominator
matters: its raw token count is the lowest of all four (222k vs 278k–420k), but at a 0.52 pass
rate (n=29) its cost per *solved* task is the **worst** of the four. Ranking on raw tokens would
have picked exactly the wrong model.

### The skill is nearly free on opus-5 and expensive on haiku

Skill-on ÷ skill-off tokens:

| task | haiku-4-5 | sonnet-4-6 | sonnet-5 | opus-5 |
|---|---|---|---|---|
| `xlsx-fin-colors` | 2.88× | 1.54× | 1.98× | **0.94×** |
| `xlsx-fin-font-clean` | 3.33× | 2.06× | 1.44× | **1.01×** |

So "what does this skill cost" has no single answer — it is a property of skill × model.
`opus-5` absorbs it for free, largely because it already works harder on the OFF arm — twice as
many calls there as `sonnet-4-6` makes, and more calls without the skill than with it (10 vs 8 on
`xlsx-fin-colors`) — so the skill adds guidance rather than effort.

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

### Downstream LLM calls

An LLM call can trigger further LLM calls: a subagent (`Agent`) runs its own agent loop.
**Cortex counts those**, because the child's `HTTPS_PROXY` is inherited by its subprocesses, so
a subagent's traffic traverses the same proxy and appears as ordinary response events inside the
measurement window. For **cost** that is exactly right: those calls are real and billed.

A **background task** (`TaskOutput`/`TaskStop`) is a different thing and is *not* a source of
downstream LLM calls — it is an asynchronous *shell* command whose output the main loop later
reads. Its tokens belong to the loop being measured. Conflating the two is what produced the
withdrawn `pptx` figure above, so the harness records background tools but never treats them as
a confound.

**But they are not attributable.** On the wire a subagent's call is indistinguishable from the
main loop's. So:

| Measure | Effect of downstream work |
|---|---|
| total tokens / dollars | **correct** — the calls really happened |
| tokens per LLM call | **unaffected** — still that model's per-call average |
| LLM calls per task | **inflated** — the "task" is no longer one agent loop |
| skill-overhead ratios | **invalid** — mixes two different amounts of work |

Measured impact where it occurred: **2.7×–8.2× the tokens** versus other repetitions of the
same cell.

| Cell | with downstream | without |
|---|---|---|
| `pptx-body-left-aligned` ON | 26 calls / 1,255,632 | 10 calls / 458,514 |
| `pptx-size-contrast` ON | 36 calls / 1,908,134 | 10 calls / 491,474 |
| `select-deck` SELECT | 46 calls / 2,485,834 | 7 calls / 302,900 |

The harness therefore flags such repetitions as confounded (`subagent_invoked`,
`background_task_used`) rather than averaging them in. **This detector was broken until
2026-09-09**: it matched only a tool named `Task`, while this Claude Code build names the
subagent tool `Agent`, so five affected repetitions passed as clean. Fixed and unit-tested
against both names.

**The xlsx cost profile is unaffected** — 0 of the 5 affected repetitions fall in its 20
cells; all were in the retired `pptx` tasks and one `select` task.

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

| task | tokens per LLM call OFF → ON | LLM calls per task OFF → ON | total |
|---|---|---|---|
| `xlsx-fin-colors` | 33,568 → 36,977 (**+3,409**) | 5 → 5 (+0%) | **+10%** |
| `xlsx-fin-font-clean` | 33,482 → 36,805 (**+3,323**) | 5 → **10** (+100%) | **+120%** |

The per-call increase is a near-constant ~3.3–3.4k, matching the injected `SKILL.md`
(~2,865 tokens). The entire difference between +10% and +120% is **call count** — the skill
made the agent do twice as much work on one task and no extra work on the other.

So a bigger skill bundle is *not* inherently more expensive: only 1 of 6 skill-on runs read
anything from the skill's 54-file `scripts/` directory. Compare **tokens per LLM call** to see
the skill text, and **call count** to see the behavioural cost. Comparing raw totals across
skills measures task shape instead.

## Security

`out/` is gitignored and must stay that way. The Cortex session API is **unauthenticated**
and its events carry `inference.messages` and `inference.completion` — full prompts and
model output. The NDJSON therefore stores a **field whitelist**; skill verification matches
its marker in memory and emits only a boolean.

## License

Apache 2.0 — see [LICENSE](LICENSE).
