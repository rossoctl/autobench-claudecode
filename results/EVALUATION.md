# AutoBench for Claude Code — Evaluation

**Date:** 2026-09-09 · **Subject under test:** Claude Code (`claude` CLI 2.1.257)
**Gateway:** internal ETE LiteLLM · **Repetitions recorded:** 193 · **Skill measured:** `xlsx`

---

## 1. Executive summary

We built a harness whose subject is the Claude Code agent, scored every task by a
programmatic verdict (no LLM judge), measured tokens on the wire with Cortex, and priced the
result against the internal LiteLLM rate card.

**The recommendation, on evidence:**

| Use | Model | Why |
|---|---|---|
| Default for skill-driven document work | **`claude-sonnet-5`** | 100% pass on every task, and more **cost-efficient** than `sonnet-4-6` in 2 of 3 cells despite being *less* token-efficient |
| Cost-sensitive, tolerant of retries | **`claude-haiku-4-5`** | Most **cost-efficient** in every cell by 2–4×, but only **40%** pass on the harder task |
| Not indicated by this evidence | `claude-opus-5` | Least **cost-efficient** in every cell — though the *most token-efficient*, so it may suit token-bound rather than bill-bound work |

Three findings that a simpler measurement would have got wrong:

1. **Token-efficiency and cost-efficiency are different measures, and they disagree.**
   `opus-5` is the **most token-efficient** model tested and the **least cost-efficient**; on
   `cortex-pyfix-001` the two rankings are exactly inverted. Quoting one number as
   "efficiency" picks the answer by accident.
2. **`sonnet-5` looks worse in tokens and better in dollars.** It used 2.2× `sonnet-4-6`'s
   tokens on one task, but at 2/3 the unit price it still wins overall.
3. **Raw cost hides reliability.** `haiku` has the lowest token count on
   `xlsx-fin-font-clean` but passes only 40% of the time; charging it for its failures still
   leaves it cheapest, which is a genuine finding rather than an artefact.

---

## 2. What a benchmark is made of

Six parts. Drop any one and you have a demo, a load generator, or a number nobody can
defend. **Cortex supplies exactly one of them.**

| Part | Why it is required | Here |
|---|---|---|
| **Tasks** | A defined unit of work, reproducible from a fixed definition into a fresh workspace every time | `tasks/<id>/prompt.md` + `workspace/` |
| **Programmatic evaluator** | A verdict that is a command's exit code, not a model's opinion. This is what makes it a benchmark rather than a load generator | hidden `verdict/` → `pytest -q` |
| **Controls** | An arm that isolates the one variable under study, so an effect can be attributed to it | `off` / `on` / `select` arms |
| **Repetition** | The subject is non-deterministic, so a single run is an anecdote. Report medians and spread | *n* per cell, CV reported |
| **Attribution** | Evidence of what *actually* ran, so a result produced by something other than the thing under test is caught | `stream-json` transcript → confounds |
| **Observability** | What it cost: tokens by cache tier, latency, the real model served — measured, not estimated | **Cortex supplies this** |

**Cortex is a component of the harness, not the benchmark.** It supplies the observability
data and nothing else: it sees bytes on the wire and can never score whether the work was
correct. Conversely the verdict knows correctness but nothing about cost, and the transcript
knows which local tools ran but carries no token counts. That separation is why all three
sources are needed — see §4.

---

## 3. Terms in use

These were conflated early in the work and are kept strictly separate.

| Term | Meaning |
|---|---|
| **Harness** | The whole measuring apparatus: tasks + driver + verdict + Cortex. |
| **Agent under test** | The thing being measured. Here: Claude Code. |
| **Benchmark provider** | Supplies tasks *and* scores them. Here the harness is its own provider. |
| **Task** | One unit of work: `prompt.md` + a fresh `workspace/`, optionally a hidden `verdict/`. |
| **Verdict** | The programmatic pass test. A command's exit code — never a model's opinion. |
| **Arm** | A condition applied to a task. `off` = skill unavailable (control), `on` = skill available and explicitly invoked, `select` = all skills available, none named. |
| **Cell** | One (task × arm × model) combination, measured over *n* repetitions. `xlsx-fin-colors` / `on` / `sonnet-5` at n=5 is one cell. The profile has 5 (task, arm) pairs × 4 models = **20 cells**. |
| **Repetition** (= one task run) | One headless `claude -p` invocation in a fresh workspace. |
| **LLM call** | One `/v1/chat/completions` request/response on the wire. **A single task makes several** — 5 to 24 in these runs — each re-sending the growing conversation. |
| **Compliance task** | Asks for ordinary work; the hidden verdict checks whether a *skill convention* was followed. |
| **Selection task** | Names no skill; the verdict is whether the model *chose* the right one. |
| **Confound** | A repetition whose measurement is untrustworthy (foreign skill, subagent, model-pin mismatch, no artefact, missing Cortex events). Reported separately, never averaged in. |
| **Token-efficiency** | Tokens consumed per **solved** task. What a context window, a rate limit or wall-clock latency actually sees. |
| **Cost-efficiency** | Dollars per **solved** task — token-efficiency weighted by that model's unit price. |
| **Cost per solved task** | `median ÷ pass rate`, so a model is charged for its failures. Applies to either measure above. |

Note `workload-harness` (hyphenated) is a **proper noun** — an unrelated upstream project.
It is never used here as a common noun.

---

## 4. Benchmarking setup, and why it is shaped this way

```
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  harness.py  (driver, holds an exclusive run lock)                       │
   │                                                                          │
   │  1. copy tasks/<id>/workspace/  ──►  fresh temp dir   (no cross-run      │
   │                                                        contamination)    │
   │  2. build a CLEAN child environment:                                     │
   │        HTTPS_PROXY, NODE_EXTRA_CA_CERTS   ─► route this child via Cortex │
   │        CLAUDE_CONFIG_DIR                  ─► exactly which skills exist  │
   │        CLAUDE_CODE_DISABLE_BUNDLED_SKILLS ─► drop the binary's own       │
   │        --model <pinned>                   ─► beats env AND settings.json │
   └──────────────────────────────────────────────────────────────────────────┘
                  │  spawn
                  ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │  claude -p  (child)   │───────►│  Cortex              │──► LiteLLM ──► model
        │  headless, one task   │CONNECT │  forward proxy       │  (real HTTPS)
        │  stream-json on stdout│        │  + tls_bridge        │
        └───────────────────────┘        │  inference-parser    │
                  │                      └──────────────────────┘
                  │ edits files                    │ Server-Sent Events
                  ▼                                ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │ 3. install hidden     │        │  out/events/*.sse    │
        │    verdict/  AFTER    │        │  (30-min TTL upstream│
        │    the child exits    │        │   → streamed to disk)│
        │ 4. run `pytest -q`    │        └──────────────────────┘
        └───────────────────────┘
                  │                                │
                  └────────────┬───────────────────┘
                               ▼
                     one NDJSON row per repetition
```

**Transport, precisely — the env var name misleads.** `HTTPS_PROXY` is *named* https but its
value is `http://127.0.0.1:47600`: the hop from the child to the local Cortex service is
**plaintext HTTP `CONNECT` on loopback**, not HTTPS. `tls_bridge` then terminates TLS with
its own CA — which is exactly why `NODE_EXTRA_CA_CERTS` is required — so the request body can
be parsed, and Cortex makes the real HTTPS connection outbound to the gateway. This is
visible in the captured events: the first is `host=…:443, tunnel=true` (the CONNECT), and the
following ones carry the decrypted request and response with no port and no tunnel flag.

**SSE** is Server-Sent Events — Cortex's `GET /v1/events` live stream. The harness copies it
to disk because the upstream session store is in-memory with a 30-minute TTL, so the file is
the only durable record.

**Three measurement sources, because none can answer another's question:**

| Question | Source | Why not the others |
|---|---|---|
| Did it work? | verdict exit code | Cortex sees bytes, not correctness |
| Tokens, cache tiers, latency | Cortex, on the wire | The transcript carries no token counts |
| Which tools/skills/subagents ran | `stream-json` transcript | Cortex cannot see local tool calls (Read/Edit/Bash never leave the machine) |

**Design decisions and their rationale:**

- **Per-invocation isolation, not global config.** Everything is passed to the child, so the
  operator's `~/.claude/settings.json` is never modified (`abctl claude-code status` stays
  "0 of 3 set"). One Cortex sees *all* traffic on the machine, so global wiring would let
  interactive typing pollute a benchmark window. Interactive use stays safe precisely
  because it has no `HTTPS_PROXY`.
- **Forward proxy + `tls_bridge`, not a reverse listener.** Measured: the reverse role
  records events but leaves `plugins=[]`, so no tokens. Only forward + bridge dispatches the
  inference parser.
- **`CLAUDE_CONFIG_DIR`, not `HOME`.** `HOME` is *not* the skill lookup root — four arms
  with a curated `HOME` reported an identical 60 slash commands. Bundled skills are a
  separate population needing their own switch.
- **The model is pinned and then verified on the wire.** The model actually used came from an
  ambient `ANTHROPIC_MODEL` that disagreed with `settings.json`; `--model` beats both, and
  every row records requested-vs-observed so a substitution is flagged, not averaged.
- **An exclusive run lock.** Cortex correlates by *time window* against one shared proxy, so
  two overlapping runs interleave — observed, detected, then made impossible.
- **Artefacts are whitelisted.** Cortex events carry `inference.messages` and
  `inference.completion` — full prompts and model output — on an unauthenticated API. The
  NDJSON stores a field whitelist; `out/` is never committed.

---

## 5. Model pricing (internal LiteLLM, 2026-09-09)

**Provenance.** The rate card is **maintained by hand** in `pricing.py`, transcribed from
the gateway's model pages (`/ui/?page=models`) on **2026-09-09**. That is deliberate, not a
gap: the page sits behind an interactive internal web-authorization flow and fills its
contents by script, so there is no endpoint a benchmark credential can read and no automated
pull is attempted. When rates change, edit `PRICES` and bump `SOURCE_DATE`.

| Benchmarked alias | Gateway entry | Input $/1M | Output $/1M | Output:input |
|---|---|---|---|---|
| `claude-haiku-4-5-20251001` | `aws/claude-haiku-4-5` | **0.76** | **3.80** | 5.0× |
| `claude-sonnet-4-6` | `aws/claude-sonnet-4-6` | **2.28** | **11.40** | 5.0× |
| `claude-sonnet-5` | `aws/claude-sonnet-5` | **1.52** | **7.60** | 5.0× |
| `claude-opus-5` | `aws/claude-opus-5` | **3.80** | **19.00** | 5.0× |

**`sonnet-5` is priced at 2/3 of `sonnet-4-6`** — the single most consequential fact in the
cost analysis. `opus-5` is 2.5× `sonnet-5` and 5× `haiku`.

### The cache-pricing caveat

The gateway publishes only Input and Output rates, but **81–97% of our prompt tokens are
cache reads**. Two scenarios are therefore reported:

| Scenario | Assumption |
|---|---|
| **A — no cache discount** | Every prompt token billed at the Input rate. Upper bound. |
| **B — standard cache** | `cacheRead ×0.10`, `cacheWrite ×1.25`, uncached ×1.00 — the published Anthropic/Bedrock convention. Likely case. |

B lands roughly 4–5× below A. **Which the gateway actually bills is unverified** and should
be confirmed against an invoice before either figure is quoted as fact.

**The model ranking is identical under both scenarios in all three cells**, so the
recommendation does not depend on resolving this.

Two further caveats: the price pages are titled `aws/claude-*` while the benchmark pinned the
bare aliases; both route and Cortex confirmed the bare alias was served, but identical
billing is assumed, not proven. And Cortex never populates `costMicros` (`priced:false`, an
in-tree TODO), so every dollar figure here is computed by us from token counts.

---

## 6. Methodology: how a task earns its place

A task is only admitted if it can actually measure something. Two rules, both learned the
hard way — **9 of the first 11 tasks written were discarded.**

**Rule 1 — the verdict must be tamper-proof, not merely green.** A pass requires the verdict
to exit 0 *and* every `test_*.py` to be byte-identical to what shipped. Deleting the test, or
rewriting it to assert the buggy behaviour, also makes `pytest` green.

**Rule 2 — pre-screen on the OFF arm and discard anything that passes.** A task the agent
already passes *without* the skill is not measuring the skill.

**Hidden verdicts.** For a compliance task the test enumerates the conventions being checked.
Left visible in `workspace/`, the agent reads it and complies — so both arms pass and the task
measures "can you read a test". Hidden verdicts are installed only *after* the child exits.

### The verdict files actually used

| Task | Verdict file | Visible to the agent? | What it asserts |
|---|---|---|---|
| `cortex-pyfix-001` | `workspace/test_billing.py` | **Yes** — the tests *are* the spec | 6 tests over two seeded bugs (a percentage treated as a fraction; a dropped remainder in an even split) |
| `xlsx-fin-colors` | `verdict/test_compliance.py` | **No** — installed after the agent exits | 2 tests: hardcoded numeric inputs are blue-font; formula cells are not blue |
| `xlsx-fin-font-clean` | `verdict/test_compliance.py` | **No** | 3 tests: one consistent professional font; no `#REF!`/`#DIV/0!`-class literals; the saving and ratio are formulas, not typed values |

All are plain `pytest`, run by the repo's `.venv` interpreter. The pass condition is exit 0
**and** every `test_*.py` byte-identical to what shipped.

### Why tasks were discarded — the reusable heuristic

**A compliance rule discriminates only when it is arbitrary and house-specific, not when it
is objectively better practice.** A capable model already does good practice unprompted.

| Skill | Rule kind | Outcome |
|---|---|---|
| `xlsx` | blue = hardcoded input (arbitrary banking convention) | **discriminates** |
| `xlsx` | professional font, zero formula errors | **discriminates** |
| `xlsx` | `$#,##0` / `0.0%` / `0.0x`, assumptions as cell refs | passes unaided — discarded |
| `docx` | real bullets, US Letter, DXA table widths | passes unaided — discarded |
| `pptx` | size hierarchy, non-text-only slides | passes unaided — discarded |

A second trap: **path-dependent rules.** The `docx` rules exist to correct footguns in
docx-js, the library that skill itself mandates (A4 default, percentage table widths). The
unaided agent uses python-docx, whose defaults already satisfy them, so it never meets the
footgun. Testing those needs the same library forced in both arms — a different experiment.

---

## 7. Results

### 7.1 Pass rate — and a prediction of ours that was falsified

We predicted pass rate would be useless for ranking models: the OFF arm is pinned at 0 by the
pre-screen, the ON arm at 100 because the skill states the answer. **That held only for the
two mid-tier models it was observed on.** Widening the tiers broke it in both directions:

| Model | `xlsx-fin-colors` OFF → ON | `xlsx-fin-font-clean` OFF → ON |
|---|---|---|
| `haiku-4-5` | 0.00 → 1.00 | 0.00 → **0.40** ← does not reliably comply *even when told* |
| `sonnet-4-6` | 0.00 → 1.00 | 0.00 → 1.00 |
| `sonnet-5` | 0.00 → 1.00 | 0.00 → 1.00 |
| `opus-5` | **0.20** → 1.00 ← sometimes knows the convention unaided | 0.00 → 1.00 |

**Generalisable lesson: "the measure is saturated" is a claim about the models you happened
to test, not about the task.**

### 7.2 Tokens — two factors, only one of which is a model property

**`tokens per task = tokens per LLM CALL × LLM calls per task`.** The two factors behave
completely differently, so a raw total hides both.

Note the unit: a *task* is one `claude -p` run; it makes **several LLM calls** (5–24 observed),
each re-sending the accumulated conversation. One measured task on `opus-5` looked like this —
5 calls, prompt growing 27,060 → 29,276 as the conversation built up:

| LLM call | prompt | completion | total |
|---|---|---|---|
| 1 | 27,060 | 142 | 27,202 |
| 2 | 27,441 | 217 | 27,658 |
| 3 | 28,370 | 469 | 28,839 |
| 4 | 29,145 | 142 | 29,287 |
| 5 | 29,276 | 163 | 29,439 |

That re-sending is also why cache reads dominate: each call's prompt is mostly the previous
turn's context.

**Factor 1 — tokens per LLM call.** Ratio vs `sonnet-4-6`, across five structurally different
cells:

| Model | Range | Spread | Reading |
|---|---|---|---|
| `haiku-4-5` | 0.97–1.05 | **0.07** | ≈ same context per LLM call |
| `sonnet-5` | 1.19–1.30 | **0.11** | **≈1.23× more** per LLM call |
| `opus-5` | 0.89–0.97 | **0.08** | **≈0.90× — leaner** per LLM call |

**Factor 2 — LLM calls per task — is not constant**: 0.40–1.00× for haiku, 0.83–2.00× for
`opus-5`, depending on the task. So a model has a stable appetite *per LLM call* that you can
budget with, while how many calls a job needs is a separate matter. Reporting raw token totals
multiplies the two and conflates them.

Cache reads are **81–97% of prompt tokens** in every cell (highest on `sonnet-5`/`opus-5`).

### 7.3 Money — which reverses the token conclusion

Cost per **solved** task, scenario B (standard cache), `$` per task:

| Task | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|
| `xlsx-fin-colors` (ON) | **0.0386** | 0.1590 | 0.1678 | 0.2719 |
| `xlsx-fin-font-clean` (ON) | **0.1075** ⚠️ | 0.1873 | 0.1332 | 0.2486 |
| `cortex-pyfix-001` (no skill) | **0.0313** | 0.0837 | 0.0588 | 0.1030 |

⚠️ haiku's figure already charges it for a 0.40 pass rate.

Scenario A (no cache discount) for the same cells — **same ordering throughout**:

| Task | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|
| `xlsx-fin-colors` | 0.1409 | 0.5916 | 0.9080 | 1.1625 |
| `xlsx-fin-font-clean` | 0.3364 | 0.8462 | 0.7035 | 1.1259 |
| `cortex-pyfix-001` | 0.1597 | 0.4567 | 0.3113 | 0.5649 |

**`opus-5` used the fewest tokens on two of three cells and is the most expensive on all
three.** That is the entire case for pricing the measurement rather than counting tokens.

### 7.4 Token-efficiency is not cost-efficiency

Two different questions, and they answer differently:

| | Token-efficiency | Cost-efficiency |
|---|---|---|
| Measures | tokens per solved task | dollars per solved task |
| Binding when | context window, rate limits, latency | you are paying the bill |
| Driven by | how much context, how many calls | the same, weighted by unit price |

They diverge because unit price spans **5×** (haiku $0.76 → opus-5 $3.80 per 1M input), which
swamps the ~2× spread in token counts. On `cortex-pyfix-001` the two rankings are **exactly
inverted**:

| Model | tokens/solved | rank | $/solved | rank |
|---|---|---|---|---|
| `opus-5` | 144,834 | **1st** | 0.1030 | **4th** |
| `sonnet-4-6` | 196,634 | 2nd | 0.0842 | 3rd |
| `sonnet-5` | 200,732 | 3rd | 0.0588 | 2nd |
| `haiku-4-5` | 204,034 | **4th** | 0.0313 | **1st** |

**`opus-5` is the most token-efficient and the least cost-efficient model tested.** Quoting a
single number and calling it "efficiency" picks the answer by accident. Where the two are
reported together in this document, the measure is always named.

### 7.5 A subagent's calls land in the totals — and can't be separated out

An LLM call can trigger further LLM calls — a subagent (`Agent`) runs its own agent loop, and
background tasks run asynchronously. **Cortex counts all of them**: the child's `HTTPS_PROXY`
is inherited by its subprocesses, so a subagent's traffic crosses the same proxy and lands in
the measurement window as ordinary response events. For cost that is correct — those calls
are real and billed.

**They are not attributable, though.** On the wire a subagent's call looks exactly like the
main loop's, so:

| Measure | Effect |
|---|---|
| total tokens / dollars | **correct** — the calls really happened |
| tokens per LLM call | **unaffected** — still that model's per-call average |
| LLM calls per task | **inflated** — the "task" is no longer a single agent loop |
| skill-overhead ratios | **invalid** — compares two different amounts of work |

Measured impact, comparing affected repetitions against others in the same cell:

| Cell | with downstream work | without |
|---|---|---|
| `pptx-body-left-aligned` ON | 26 calls / 1,255,632 tok | 10 calls / 458,514 tok |
| `pptx-size-contrast` ON | 36 calls / 1,908,134 tok | 10 calls / 491,474 tok |
| `select-deck` SELECT | 46 calls / 2,485,834 tok | 7 calls / 302,900 tok |

That is **2.7×–8.2×**, which is why these repetitions must be flagged rather than averaged in.

**This detector was broken until 2026-09-09.** It matched a tool named `Task`, but this Claude
Code build names the subagent tool `Agent`, so five affected repetitions were reported as
clean. Now matches both, plus `TaskOutput`/`TaskStop` for background work, and is unit-tested.
One published figure was wrong as a result: `pptx` skill overhead was stated as 18×, from a
median including two contaminated repetitions; excluding them it is **3.0×**.

**The cost profile in §7.1–7.4 is unaffected** — none of the 5 affected repetitions fall in
its 20 cells. All were in the retired `pptx` tasks and one `select` task.

### 7.6 Skill overhead is a property of skill × model

Skill-on ÷ skill-off, in **both** measures — they differ, because the input/output/cache mix
shifts between arms even at a fixed unit price:

| Task | Measure | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|---|
| `xlsx-fin-colors` | tokens | 2.88× | 1.50× | 2.01× | **0.93×** |
| `xlsx-fin-colors` | **dollars** | 1.97× | 1.33× | 1.88× | **1.06×** |
| `xlsx-fin-font-clean` | tokens | 2.37× | 2.08× | 1.56× | **1.01×** |
| `xlsx-fin-font-clean` | **dollars** | 2.24× | 1.71× | 1.41× | **1.08×** |

In dollars the skill adds **6–8% on opus-5** and roughly **doubles the bill on haiku**. Note
opus-5's dollar overhead sits slightly *above* 1.0 even where its token overhead dips below —
so "the skill is free on opus-5" is too strong; "barely noticeable" is accurate.

"What does this skill cost" has no single answer. `opus-5` barely notices it because it
already works ~2× the calls **without** the skill (10 vs 8 on `xlsx-fin-colors`), so the
guidance replaces exploration rather than adding to it — which is why its token ratio can dip
below 1.0 at all.

### 7.7 Skill selection works

All candidate skills present (`xlsx`/`docx`/`pptx`/`pdf`), prompt names none, verdict from
the transcript. `sonnet-4-6`, n=3: **12/12 correct, 0 confounded** — including a prompt that
never says "spreadsheet" (fired `xlsx` 3/3) and a negative case where firing nothing is
correct (fired nothing 3/3, so no over-eagerness).

---

## 8. Model selection recommendation

**Adopt `claude-sonnet-5` as the default.** 100% pass on every task, and more
**cost-efficient** than the incumbent `sonnet-4-6` in 2 of 3 cells — 29% on
`xlsx-fin-font-clean`, 30% on the no-skill canary — *despite being less token-efficient*. Its
2/3 unit price more than absorbs the 1.23× per-call context.

**Use `claude-haiku-4-5` only behind a validator.** Most cost-efficient in every cell by 2–4×
and fastest (14–39 s vs 59–78 s). But it passed the harder compliance task only **40%** of the
time *with the skill supplied*. What it actually got wrong, across the three failures:

| Rep | Failure | Detectable by eye? |
|---|---|---|
| 3 | mixed fonts — `['calibri', 'cambria']` | maybe, on close inspection |
| 4 | mixed fonts — `['arial', 'calibri']` | maybe |
| 5 | **hardcoded the values instead of using formulas** (0 formulas where ≥2 required) | **no — the numbers are correct** |

That third one is the reason "retries are acceptable" is too casual a condition. A hardcoded
spreadsheet *looks* right and reports the right figures; it breaks silently the first time an
input changes. So the precondition is not tolerance of retries but **the ability to detect the
failure programmatically** — the same verdict the benchmark uses. Without a validator in the
pipeline you do not get retries, you get silent defects. With one, haiku's economics survive
its failures on these tasks (cost per *solved* task already charges for them); that will not
hold as tasks harden.

**Do not default to `claude-opus-5` where the bill is the constraint.** Least cost-efficient
in all three cells (1.6–2.1× `sonnet-5`) with no pass-rate advantage. But note the measure
matters: it is the **most token-efficient** model tested and the leanest per LLM call, and it was
the only model to solve a task unaided. If the binding constraint is a context window, a rate
limit or latency rather than the invoice, that verdict can reverse — which is precisely the
argument for scoping the choice rather than picking one global default.

**Confidence.** The pass-rate and cost orderings are robust: they hold across both pricing
scenarios and, for tokens per LLM call, across five independent cells. The absolute dollar figures
are not tight — see limitations.

---

## 9. Limitations, stated plainly

1. **One skill.** Every skill-specific conclusion rests on `xlsx`. Whether "the skill is free
   on opus-5" is an opus property or an xlsx property is currently indistinguishable.
2. **n=5 per cell**, some CVs up to 0.85. The tokens-per-LLM-call constants are trustworthy because
   they reproduce across five independent cells; individual cost figures are indicative.
3. **Cache billing unverified** — the largest single uncertainty (4–5× on absolute cost),
   though it does not change any ranking.
4. **Two tasks in one narrow genre.** Both discriminators are financial-spreadsheet
   formatting. This is not a general coding benchmark.
5. **`aws/` vs bare alias pricing** assumed identical; unprovable with a non-admin key.
6. **Wall-clock is gateway-dependent** and was not load-controlled; treat it as indicative.

**What would change the conclusion:** if the gateway does *not* discount cache reads,
absolute costs rise ~4–5× and cache-heavy agentic use becomes far more expensive in
aggregate — the ranking survives but budget planning changes materially. If harder tasks were
added, `haiku`'s reliability gap would likely widen and `opus-5` might start earning its
premium.

---

## 10. Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
abctl service start                       # Cortex, forward + tls_bridge
python3 profile.py --run --reps 5         # the grid (~2.5 h, 100 invocations)
python3 profile.py --report               # recompile, no invocations
python3 pricing.py                        # the rate card
```

Raw per-repetition records are in the gitignored `out/runs/`. `profile.py --report` asserts
two token identities per cell — `prompt == uncached + cacheRead + cacheWrite` and
`total == prompt + completion` — and quarantines any cell that fails them. None did.
