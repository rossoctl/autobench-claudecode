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
| Default for skill-driven document work | **`claude-sonnet-5`** | 100% pass on every task, and **cheaper than `sonnet-4-6` in 2 of 3 cells** despite using more tokens |
| Cost-sensitive, tolerant of retries | **`claude-haiku-4-5`** | Cheapest in **every** cell by 2–4×, but only **40%** pass on the harder task |
| Not indicated by this evidence | `claude-opus-5` | **Most expensive in every cell**, with no pass-rate advantage over sonnet |

Three findings that a simpler measurement would have got wrong:

1. **Ranking on tokens picks the wrong model.** `opus-5` used the *fewest* tokens on two of
   three cells yet is the *most expensive* everywhere, because it is priced 2.5× `sonnet-5`.
2. **`sonnet-5` looks worse in tokens and better in dollars.** It used 2.2× `sonnet-4-6`'s
   tokens on one task, but at 2/3 the unit price it still wins overall.
3. **Raw cost hides reliability.** `haiku` has the lowest token count on
   `xlsx-fin-font-clean` but passes only 40% of the time; charging it for its failures still
   leaves it cheapest, which is a genuine finding rather than an artefact.

---

## 2. Terms in use

These were conflated early in the work and are kept strictly separate.

| Term | Meaning |
|---|---|
| **Harness** | The whole measuring apparatus: tasks + driver + verdict + Cortex. |
| **Agent under test** | The thing being measured. Here: Claude Code. |
| **Benchmark provider** | Supplies tasks *and* scores them. Here the harness is its own provider. |
| **Task** | One unit of work: `prompt.md` + a fresh `workspace/`, optionally a hidden `verdict/`. |
| **Verdict** | The programmatic pass test. A command's exit code — never a model's opinion. |
| **Arm** | A condition applied to a task. `off` = skill unavailable (control), `on` = skill available and explicitly invoked, `select` = all skills available, none named. |
| **Cell** | One (task × arm × model) combination, measured over *n* repetitions. |
| **Repetition** | One headless `claude -p` invocation in a fresh workspace. |
| **Compliance task** | Asks for ordinary work; the hidden verdict checks whether a *skill convention* was followed. |
| **Selection task** | Names no skill; the verdict is whether the model *chose* the right one. |
| **Confound** | A repetition whose measurement is untrustworthy (foreign skill, subagent, model-pin mismatch, no artefact, missing Cortex events). Reported separately, never averaged in. |
| **Cost per solved task** | `median tokens ÷ pass rate` — charges a model for its failures. |

Note `workload-harness` (hyphenated) is a **proper noun** — an unrelated upstream project.
It is never used here as a common noun.

---

## 3. Benchmarking setup, and why it is shaped this way

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

## 4. Model pricing (internal LiteLLM, 2026-09-09)

Transcribed from the gateway's own model pages. `/model/info` returns **403** for a
non-admin key, so these are hand-entered rather than pulled programmatically.

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

## 5. Methodology: how a task earns its place

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

## 6. Results

### 6.1 Pass rate — and a prediction of ours that was falsified

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

### 6.2 Tokens — one term is a model constant, the other is not

`tokens/call` ratio vs `sonnet-4-6`, across five structurally different cells:

| Model | Range | Spread | Reading |
|---|---|---|---|
| `haiku-4-5` | 0.97–1.05 | **0.07** | ≈ same per-call context |
| `sonnet-5` | 1.19–1.30 | **0.11** | **≈1.23× more** per call |
| `opus-5` | 0.89–0.97 | **0.08** | **≈0.90× — leaner** per call |

**Call count is not constant** — 0.40–1.00× for haiku, 0.83–2.00× for opus-5 by task. So
decompose: the stable term is the model, the variable term is the work. Reporting raw totals
conflates them.

Cache reads are **81–97% of prompt tokens** in every cell (highest on `sonnet-5`/`opus-5`).

### 6.3 Money — which reverses the token conclusion

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

### 6.4 Skill overhead is a property of skill × model

Skill-on ÷ skill-off tokens:

| Task | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|
| `xlsx-fin-colors` | 2.88× | 1.50× | 2.01× | **0.93×** |
| `xlsx-fin-font-clean` | 2.37× | 2.08× | 1.56× | **1.01×** |

"What does this skill cost" has no single answer. `opus-5` absorbs it for free — largely
because it already works ~2× the calls on the OFF arm, so the skill adds guidance rather than
effort.

### 6.5 Skill selection works

All candidate skills present (`xlsx`/`docx`/`pptx`/`pdf`), prompt names none, verdict from
the transcript. `sonnet-4-6`, n=3: **12/12 correct, 0 confounded** — including a prompt that
never says "spreadsheet" (fired `xlsx` 3/3) and a negative case where firing nothing is
correct (fired nothing 3/3, so no over-eagerness).

---

## 7. Model selection recommendation

**Adopt `claude-sonnet-5` as the default.** 100% pass on every task, and cheaper than the
incumbent `sonnet-4-6` in 2 of 3 cells — 29% cheaper on `xlsx-fin-font-clean` and 30% on the
no-skill canary — despite consuming *more* tokens. Its 2/3 unit price more than absorbs the
1.23× per-call context.

**Use `claude-haiku-4-5` where a retry is acceptable.** Cheapest in every cell by 2–4× and
fastest (14–39 s vs 59–78 s). But it passed the harder compliance task only **40%** of the
time *with the skill supplied*, so it is unsuitable where first-attempt correctness matters.
Its economics survive its failures on these tasks; that will not hold as tasks get harder.

**Do not default to `claude-opus-5` for this class of work.** Most expensive in all three
cells (1.6–2.1× `sonnet-5`) with no pass-rate advantage. It is genuinely the most
*token*-efficient and leanest per call, and it was the only model to solve a task unaided —
so it may well justify itself on harder work. It does not on this evidence.

**Confidence.** The pass-rate and cost orderings are robust: they hold across both pricing
scenarios and, for `tokens/call`, across five independent cells. The absolute dollar figures
are not tight — see limitations.

---

## 8. Limitations, stated plainly

1. **One skill.** Every skill-specific conclusion rests on `xlsx`. Whether "the skill is free
   on opus-5" is an opus property or an xlsx property is currently indistinguishable.
2. **n=5 per cell**, some CVs up to 0.85. The `tokens/call` constants are trustworthy because
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

## 9. Reproducing

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
