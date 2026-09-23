# AutoBench for Claude Code — Evaluation

**Date:** 2026-09-09 · **Subject under test:** Claude Code (`claude` CLI 2.1.257)
**Gateway:** IBM Research's ETE LiteLLM (an enterprise deployment we are a tenant of, not a Red Hat service) · **Repetitions recorded:** 209 (149 in the cost grid: 18 cells
at n=5, 2 discriminator cells at n≈30), plus 12 in the two cross-session stability probes of §7.3.2
that are deliberately kept out of the grid ·
**Skill measured:** `xlsx`

> **Scope of the skill under test.** Every number below was measured against the skills
> **as installed** at the digests frozen in `skills/MANIFEST.json`, which is the state those
> directories were in on 2026-09-08 and therefore the state behind all 193 published
> repetitions. Skill text is apparatus: `bin/autobench-claudecode-cli doctor` warns when the
> installed digests drift from the manifest, and every row written since carries
> `skill_variant` / `skill_sha` / `skill_files` so a moved pass rate can be attributed. Results
> here say nothing about any later version of a skill, or about the `*-v2` rewording variants
> in `skills/` — those are a separate experiment with its own arms.

---

## 1. Executive summary

We built a harness whose subject is the Claude Code agent, scored every task by a
programmatic verdict (no LLM judge), measured tokens on the wire with Cortex, and priced the
result against the internal LiteLLM rate card.

**The recommendation, on evidence:**

| Use | Model | Why |
|---|---|---|
| Default for skill-driven document work | **`claude-sonnet-5`** | 100% pass on every task, and never dearer than `sonnet-4-6` with evidence behind it — **decisively cheaper on 1 of 3 cells — the one cell re-measured in a second session, where it
reproduced — and unresolved on the other 2** (scenario B, §7.3.1–§7.3.2) — despite being *less* token-efficient |
| Cost-sensitive, tolerant of retries | **`claude-haiku-4-5`** | Most **cost-efficient** in every cell, by 1.5–4.2× over the next cheapest, but only **52%** pass on the harder task (n=29) |
| Not indicated by this evidence | `claude-opus-5` | Least **cost-efficient** in every cell — though the *most token-efficient*, so it may suit token-bound rather than bill-bound work |

Three findings that a simpler measurement would have got wrong:

1. **Token-efficiency and cost-efficiency are different measures, and they disagree.**
   `opus-5` is the **most token-efficient** model tested and the **least cost-efficient**; on
   `cortex-pyfix-001` the two rankings are exactly inverted. Quoting one number as
   "efficiency" picks the answer by accident.
2. **`sonnet-5` looks worse in tokens and better in dollars.** It used 2.2× `sonnet-4-6`'s
   tokens on one task, but at 2/3 the unit price it still wins overall.
3. **Raw cost hides reliability.** `haiku` has the lowest token count on
   `xlsx-fin-font-clean` but passes only 52% of the time (n=29); charging it for its failures
   still leaves it cheapest, which is a genuine finding rather than an artefact.

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
| **Cell** | One (task × arm × model) combination, measured over *n* repetitions. `xlsx-fin-colors` / `on` / `sonnet-5` is one cell (n=5). The profile has 5 (task, arm) pairs × 4 models = **20 cells**, 149 repetitions — 18 cells at n=5 and the 2 pass-rate discriminators at n≈30. The grid is deliberately uneven; read the *n* column, never a single *n*. |
| **Repetition** (= one task run) | One headless `claude -p` invocation in a fresh workspace. |
| **LLM call** | One `/v1/chat/completions` request/response on the wire. **A single task makes several** — 2 to 29 in these runs — each re-sending the growing conversation. |
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

## 5. Model pricing (IBM Research ETE LiteLLM, 2026-09-09)

**Whose gateway.** Every repetition was served by **IBM Research's ETE deployment of LiteLLM** —
an enterprise organization's internal gateway that this project is a tenant of, not a Red Hat
service. The rates below are therefore an enterprise arrangement rather than a public price list,
and they are external state: the model set and the rates can change from the other side without
notice, which is what §5's staleness check exists for.

**Provenance.** The rate card in `pricing.py` was transcribed by hand from the gateway's model
pages (`/ui/?page=models`) on **2026-09-09**, and every figure below was computed from it.

> **Correction, 2026-09-23.** This section previously called that hand maintenance deliberate,
> on the grounds that "there is no endpoint a benchmark credential can read". That was true of
> the *UI* — which does sit behind an interactive web-authorization flow and renders
> client-side — and wrong about the *API*: the gateway serves
> `GET /public/litellm_model_cost_map` with **no credential at all**. `prices.json` now pins
> that map for the four models priced here (`tools/fetch_prices.py`, `--check` for drift).
> **No number in this evaluation moves.** What that map publishes is the *upstream provider's
> list* rates, not what we pay: the gateway bills below list, by the same proportion for every
> model and both directions, and scaling list by that proportion reproduces the table below to
> the cent. The proportion is not stated in this repository — it is a term of that organization's
> arrangement, not a result of this study, and nothing computed here needs it named. Even its
> uniformity is *inferred from the agreement of the two cards, not read*:
> `/config/cost_margin_config` would state it and is `403` for a key scoped to
> `['llm_api_routes']`. That is why the hand card stays as the independent witness the snapshot
> is tested against.

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
| **B — standard cache** | `cacheRead ×0.10`, `cacheWrite ×1.25`, uncached ×1.00. Likely case. |

B lands roughly 4–5× below A. **Which the gateway actually bills is unverified** and should
be confirmed against an invoice before either figure is quoted as fact.

Since 2026-09-23 the two multipliers are a **reading rather than a convention**: the cost map
states each model's `cache_read_input_token_cost` and `cache_creation_input_token_cost`
outright, and for all four they come to exactly ×0.10 and ×1.25 of input. What is still unshown
is whether this gateway *applies* them — `/spend/calculate` and `/cost/estimate` would answer
that and are both `403` for our key.

**The top-and-bottom ranking is identical under both scenarios in all three cells** — `haiku-4-5`
cheapest, `opus-5` dearest — so the recommendation does not depend on resolving this. The *full*
ordering is not identical: the two sonnets change places on `xlsx-fin-colors`. That looks like a
scenario-dependent answer but is really an absent one — neither ordering is statistically
established in that cell (§7.3.1).

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
| `haiku-4-5` | 0.00 → 1.00 | 0.00 → **0.52** (n=29) ← does not reliably comply *even when told* |
| `sonnet-4-6` | 0.00 → 1.00 | 0.00 → 1.00 |
| `sonnet-5` | 0.00 → 1.00 | 0.00 → 1.00 |
| `opus-5` | **0.37** (n=30) → 1.00 ← sometimes knows the convention unaided | 0.00 → 1.00 |

Every cell above is n=5 except the two bolded ones, which are the only two rates in the whole
profile that are neither 0 nor 1 — so they are the only two where sampling error could change a
conclusion, and the only two taken to n≈30. Both *rose* when the sample grew (0.40→0.52 and
0.20→0.37) and both 95% Wilson intervals halved (0.65→0.34 wide, 0.59→0.33 wide): the n=5
readings were pessimistic, not wrong in direction. Neither interval reaches 0 or 1, so neither
row's qualitative claim moves.

**Generalisable lesson: "the measure is saturated" is a claim about the models you happened
to test, not about the task.**

### 7.2 Tokens — two factors, only one of which is a model property

**`tokens per task = tokens per LLM CALL × LLM calls per task`.** The two factors behave
completely differently, so a raw total hides both.

Note the unit: a *task* is one `claude -p` run; it makes **several LLM calls** (2–29 observed),
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
| `haiku-4-5` | 0.95–1.04 | **0.09** | ≈ same context per LLM call |
| `sonnet-5` | 1.18–1.24 | **0.05** | **≈1.21× more** per LLM call |
| `opus-5` | 0.88–0.93 | **0.05** | **≈0.90× — leaner** per LLM call |

**Factor 2 — LLM calls per task — is not constant**: 0.40–1.00× for haiku, 0.83–2.00× for
`opus-5`, depending on the task. So a model has a stable appetite *per LLM call* that you can
budget with, while how many calls a job needs is a separate matter. Reporting raw token totals
multiplies the two and conflates them.

Cache reads are **81–97% of prompt tokens** in every cell (highest on `sonnet-5`/`opus-5`).

### 7.3 Money — which reverses the token conclusion

Cost per **solved** task, scenario B (standard cache), `$` per task:

| Task | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|
| `xlsx-fin-colors` (ON) | **0.0386** | 0.1746 | 0.1608 | 0.2719 |
| `xlsx-fin-font-clean` (ON) | **0.0822** ⚠️ | 0.1896 | 0.1261 | 0.2486 |
| `cortex-pyfix-001` (no skill) | **0.0313** | 0.0839 | 0.0588 | 0.1030 |

⚠️ haiku's figure already charges it for a 0.52 pass rate (n=29) — it is a cost *per solved* task,
so the ~48% of runs that have to be redone are already paid for. This is the one cost figure the
n≈30 re-run moved: at n=5 it read 0.1075 on a 0.40 pass rate. The correction goes in haiku's
favour (a better pass rate divides the same median cost by more), widening its margin over
`sonnet-5` in this cell from 1.17× to 1.53× — still the narrowest of the three cells, and the ⚠️
stands because that margin is small enough for the validator you need anyway to eat it. Propagating
the pass rate's own 95% interval ([0.344, 0.686]) through the division: haiku's cost per solved task
runs 0.0619–0.1234, i.e. a margin over `sonnet-5` of **2.04× at the optimistic end and 1.02× at the
pessimistic end**. So haiku stays cheapest across the entire interval — but at the low end by 2%,
which is a tie in all but name.

Scenario A (no cache discount) for the same cells:

| Task | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|
| `xlsx-fin-colors` | 0.1409 | 0.6677 | 0.8920 | 1.1625 |
| `xlsx-fin-font-clean` | 0.3501 | 0.8484 | 0.6625 | 1.1259 |
| `cortex-pyfix-001` | 0.1597 | 0.4582 | 0.3113 | 0.5649 |

The haiku `xlsx-fin-font-clean` cell moved in **opposite directions** between the two scenarios on
the n≈30 re-run (A 0.3364→0.3501, B 0.1075→0.0822). Two things changed at once: the pass rate rose
(cheaper per solved task, in both scenarios) and the median cache-read volume rose (dearer). A
charges cache reads at full rate, so there the volume increase wins; B discounts them 10×, so
there the pass rate wins. The ranking is unaffected in both.

**`haiku-4-5` is cheapest and `opus-5` dearest in every cell under both scenarios** — that much
does not depend on the cache assumption. The middle of the field does: on `xlsx-fin-colors` the
two sonnets **swap** between scenarios (B: `sonnet-5` 0.1608 < `sonnet-4-6` 0.1746; A: 0.8920 >
0.6677). `sonnet-5` carries ~2.1× the tokens at 2/3 the unit price, so which one wins depends on
how hard cache reads are discounted. On the other two cells `sonnet-5` is cheaper under both.

**`opus-5` used the fewest tokens on two of three cells and is the most expensive on all
three.** That is the entire case for pricing the measurement rather than counting tokens.

### 7.3.1 Which of those cost differences are actually established

A point estimate is not a finding. The tables above are medians over n=5, and the per-repetition
cost spread is wide, so some of those gaps are solid and some are noise. Each gap below is an
exact two-sided permutation test on per-repetition scenario-B cost (all 252 splits at n=5 vs 5).
**Read `p = 0.008` as "the smallest value this design can produce"** — at 5 vs 5 the floor is
2/252, so it means complete separation, not a large-sample certainty.

The headline `sonnet-5` vs `sonnet-4-6` comparison, scenario B:

| Cell | median saving | Cohen's *d* | exact *p* | reps/cell for 80% power | verdict |
|---|---|---|---|---|---|
| `cortex-pyfix-001` (canary) | 29.9% | 9.09 | **0.008** | already there at 5 | **established**, and reproduced across sessions (§7.3.2) |
| `xlsx-fin-font-clean` (ON) | 33.5% | 1.42 | 0.056 | ~8 (have 5) | **not established — and not fixable with reps, see §7.3.2** |
| `xlsx-fin-colors` (ON) | 7.9% | 0.16 | 0.778 | **~617** | **a tie — no evidence either way** |

So the honest statement is **not** "cheaper in all three cells". It is: decisively cheaper on the
canary, unresolved on `xlsx-fin-font-clean`, and *indistinguishable* on `xlsx-fin-colors`. The
three cells look similar in the table and are epistemically miles apart — the colors gap is one
quarter of a standard error, and settling it would take ~617 repetitions per cell (~$150 and most
of a day) because `sonnet-5`'s cost CV in that cell is 0.42. That is the cell to stop quoting, not
the cell to re-run.

The **reps/cell** column deserves a warning label. It inverts the standard power formula on the SD
observed in *this* sample, which assumes the cell is stationary — that a repetition bought
tomorrow is drawn from the same distribution as one bought today. That assumption was put to the
test on two cells: `cortex-pyfix-001` passed and `xlsx-fin-font-clean` failed. §7.3.2 is what
happened, and the reason its number is the one marked unfixable.

This also weakens the **swap** described above. Under scenario A the point estimates do reverse
(`sonnet-4-6` 0.6677 < `sonnet-5` 0.8920), but that reversal is itself not established
(p = 0.397). The correct reading is not "B and A disagree about which sonnet is cheaper here" but
"**this cell does not resolve the two sonnets under either scenario**". The cache assumption
(§9.3) decides where the point estimate lands; it does not rescue a comparison this noisy.

Two further checks, so the fix does not leave a different overclaim standing:

* **`haiku-4-5` cheapest** — established in every cell and both scenarios tested (p = 0.008 each).
* **`opus-5` dearest** — separated from `sonnet-5` in five of the six cases: the canary under both
  scenarios and `xlsx-fin-font-clean` under both (p = 0.008 and 0.040) at full power, plus
  `xlsx-fin-colors` under B (p = 0.048) but underpowered there — that one clears 0.05 on a sample
  that would need ~18 reps/cell to do so reliably, so it is a pass, not a comfortable one. It fails
  outright on `xlsx-fin-colors` under A (p = 0.294), where its gap over `sonnet-5` is swamped by
  `sonnet-5`'s own spread. The *ordering* is consistent in all six cases; the statistical
  separation fails in one of them.

None of this changes the recommendation in §8 — `sonnet-5` is never dearer than `sonnet-4-6` with
evidence behind it — but "all three cells" was doing work the data cannot support.

Every figure in this section is recomputed from the frozen manifest by `tools/cost_significance.py`,
which prints both estimators side by side (see §7.3.3) rather than having them retyped here.

### 7.3.2 We bought the reps §7.3.1 prescribed, and they falsified the prescription

The table above prescribed ~8 repetitions per cell to settle `xlsx-fin-font-clean`. We bought 3 more
per sonnet on **2026-09-09, ~23 hours after the grid**, holding everything we control constant: same
task directory, same ON arm, same skill files, same harness commit, same Cortex proxy, same model
alias on the wire. Reproduce the whole of this section with `tools/stability_probe.py` (`--task` to
pick a cell).

They did not settle it. Read as three views of one question (scenario B, `sonnet-5` vs `sonnet-4-6`,
median-profile gap first, mean gap second — see §7.3.3):

| Reading | n | `sonnet-4-6` | `sonnet-5` | gap (median profile) | gap (means) | exact *p* |
|---|---|---|---|---|---|---|
| 09-08 grid — **what is published** | 5 v 5 | 0.1873 | 0.1386 | 33.5% cheaper | 26.0% cheaper | 0.056 |
| 09-09 probe alone | 3 v 3 | 0.1971 | 0.4759 | **118.7% dearer** | 141.4% dearer | 0.100 |
| both sessions pooled | 8 v 8 | 0.1910 | 0.2651 | 6.2% cheaper | 38.8% dearer | 0.477 |

(Costs are per-repetition means here, not the per-solved medians of §7.3, so they do not match that
table cell-for-cell. Both arms pass 100% in this cell, so nothing is hidden in a pass-rate divisor.
The 3 v 3 *p* of 0.100 **is that design's floor** — C(6,3) = 20 splits, so 2/20 is the smallest
two-sided value it can produce, and hitting it means the six repetitions separate completely.)

The sign reverses between sessions and the pooled reading is a tie. So the answer to "is `sonnet-5`
cheaper here" is not "yes, marginally" and not "no" — it is that **the cell is not stationary**, and
a *p*-value computed across two sessions of it is measuring drift rather than the models.

**Which is drifting is the useful part, and there is a control for it.** Both sonnets were re-run in
the same session pair, so `sonnet-4-6` is a control on the rig. Per model, 09-08 versus 09-09:

| Measure | `sonnet-4-6` 09-08 → 09-09 | | `sonnet-5` 09-08 → 09-09 | |
|---|---|---|---|---|
| LLM calls | 8.8 → 8.7 | ×0.98, *p* = 1.000 | 9.6 → 32.3 | **×3.37, *p* = 0.018** |
| tool calls | 7.8 → 7.7 | ×0.98, *p* = 1.000 | 8.6 → 31.3 | **×3.64, *p* = 0.018** |
| total tokens | 334,843 → 325,112 | ×0.97, *p* = 0.875 | 457,120 → 1,876,787 | **×4.11, *p* = 0.018** |
| wall seconds *(diagnostic)* | 71.3 → 84.8 | ×1.19, *p* = 0.214 | 63.7 → 278.0 | **×4.37, *p* = 0.018** |
| cost, scenario B *(diagnostic)* | 0.1873 → 0.1971 | ×1.05, *p* = 0.750 | 0.1386 → 0.4759 | **×3.43, *p* = 0.018** |

`sonnet-4-6` reproduced to within 3% on every token and call measure. `sonnet-5` did not, on all of
them, at *p* = 0.018 — which at 5 versus 3 is again the floor (there is no complementary split at
unequal group sizes, so 1/C(8,3) = 1/56 is attainable), i.e. **complete separation on every
measure**. The rig held; one model's behaviour in this cell did not. The last two rows are marked
diagnostic for a reason established further down: cost tracks the cache tier split and wall time
tracks machine load, so neither is evidence about a model on its own. Here they merely follow the
volume rows.

Three things keep that from being a wire-counting artefact or a quality trade:

* **Two independent sources agree.** `llm_calls` is counted off the wire by Cortex; `tool_calls` is
  parsed out of the transcript. They rose ×3.37 and ×3.64 together. A miscount in one would not
  move the other.
* **The deliverable is identical.** All 16 repetitions passed, 0 confounded, and every produced
  workbook has one sheet with 12–19 populated cells — the 09-09 `sonnet-5` outputs (14, 14, 13)
  sit inside the range its own 09-08 outputs already spanned (13–19). The extra ×3.4 in spend
  bought nothing: this is not a speed/quality trade, it is the same output reached the long way.
* **Nothing we control changed**, and the wire only echoes the alias we sent. That leaves two
  explanations: (a) a gateway-side change in what `claude-sonnet-5` resolves to, or (b) a genuinely
  fat tail in this cell that n=5 happened to miss. `sonnet-5`'s pooled cost CV here is **0.85**
  (SD $0.2245 on a $0.2651 mean; range $0.1039–$0.7712) against `sonnet-4-6`'s **0.17**. A second
  probe, below, separates the two.

**A second cell separates (a) from (b).** The two explanations predict different things about
*other* cells: a gateway-side substitution moves every cell using the alias, a fat tail moves only
this one. So the same probe ran on `cortex-pyfix-001`/ON — the cheapest cell in the grid (6
invocations, $0.54 at scenario-B prices) and the only one whose cost gap §7.3.1 calls established.
Both sonnets reproduced there:

| Measure | `sonnet-4-6` 09-08 → 09-09 | | `sonnet-5` 09-08 → 09-09 | |
|---|---|---|---|---|
| LLM calls | 5.8 → 6.0 | ×1.03, *p* = 1.000 | 5.0 → 5.0 | ×1.00, *p* = 1.000 |
| tool calls | 6.4 → 6.7 | ×1.04, *p* = 1.000 | 6.0 → 6.0 | ×1.00, *p* = 1.000 |
| total tokens | 190,232 → 197,141 | ×1.04, *p* = 0.554 | 200,808 → 200,619 | ×1.00, *p* = 0.125 |
| cost, scenario B, warm repetitions | 0.0825 → 0.0861 | ×1.04, *p* = 0.238 | 0.0589 → 0.0589 | ×1.00, *p* = 0.952 |

The head-to-head reproduces with it: `sonnet-5` is **30.6%** cheaper on median profile in the second
session against **29.9%** in the grid (28.1% against 28.6% on means).

**One repetition per run was expensive, and it was the cache, not the model.** Taken at face value,
*mean* cost on pyfix rose ×1.28 (`sonnet-4-6`) and ×1.29 (`sonnet-5`) — which is how an earlier pass
of this analysis misread the cell as having drifted as well. All of it sits in **repetition 1 of each
run**, whose cache was cold. In `sonnet-5`'s rep 1, 29,119 prompt tokens left cacheRead and 29,115
arrived in cacheWrite, at a token total unchanged to within 4 tokens; scenario B bills cacheWrite at
1.25× the input rate and cacheRead at 0.10×, so that reallocation alone predicts 29,119 × 1.15 ×
$1.52/M = **$0.0509** of excess against an observed **$0.0509**. Repetitions 2 and 3 cost $0.0589
each against the grid's $0.0586–$0.0595. The same signature appears in the font-clean *control*
(`sonnet-4-6` rep 1 at 12.1% cacheWrite share of prompt tokens against a 5.2% median, warm-only cost
×0.94) and is **absent** from font-clean `sonnet-5`, whose cacheWrite share went *down* (4.6% median
→ 1.7%, 1.9%, 5.8%) while its bill tripled. The cache therefore explains the pyfix cost move completely and
the font-clean one not at all.

Two things follow. **Cost is not a measure of what a model did** — it follows the cache tier split,
which follows run order; `tools/stability_probe.py` now decides reproduction on volume measures only
(LLM calls, tool calls, tokens) and prints cost as a diagnostic beside them. **Nor is wall time**: in
the pyfix probe it rose ×1.51 (`sonnet-5`) and ×1.75 (`sonnet-4-6`) across all repetitions, and still
×1.34 and ×1.81 on the warm repetitions alone, on identical token and call counts. A loaded laptop,
not a model — and note how far apart those four ratios are for two models doing provably identical
amounts of work, which is the measure telling you not to read it.

**Verdict: cell-specific, not gateway-wide.** Reading (a) is out. A substitution behind the alias
would have moved pyfix too, and there `sonnet-5` reproduced to within 0.1% on every volume measure
(the `sonnet-4-6` control moved 3–4%, so the tighter of the two is the model in question). The alias
was serving the same thing in both sessions, and `xlsx-fin-font-clean` is a task whose cost carries a
tail n=5 did not sample. That cuts both ways: the one **established** cost finding of §7.3.1 (pyfix,
*p* = 0.008) now has a second session behind it and holds — but because the failure mode is per-cell,
one cell reproducing licenses nothing about the other 18. Each needs its own probe before its σ, and
any reps-to-power figure derived from it, can be trusted.

**Why the probe is excluded from the published grid rather than pooled into it.** Pooling would make
this one cell a two-session mixture while every other `sonnet-5` cell stays pure 09-08. The
comparisons in §7.3–§7.6 — and the tokens-per-LLM-call constant in §7.2 — all rest on every cell
having been measured under one set of conditions. Buying it for one cell at the price of that
property would trade a stated limitation for a hidden confound. Both files stay on disk and are
named in `results/profile-manifest.json` under `excluded`, with this reason recorded; the exclusion
is here to keep the two conditions separable, not to suppress a result that contradicts a published
prognosis.

**What this changes.** `xlsx-fin-font-clean` moves from "marginal, ~3 more reps would settle it" to
**not established, and not settleable by more repetitions while the cell drifts between sessions**.
Note that the falsified claim was not the measurement — every figure the 09-08 grid produces still
reproduces exactly, the only change to the published profile artefact being its exclusion-count
line — it was the *forecast* built on it. Any power calculation on 5 repetitions estimates σ from
those 5 repetitions, and here `sonnet-5`'s per-rep cost SD went from **$0.0453 (n=5, CV 0.33) to
$0.2245 (n=8, CV 0.85)** once the probe was included — understated ~5×. Because required n scales
with σ², the "~8 reps per cell" prescription understated the requirement by roughly **25×**, and
that is the optimistic reading, the one where a stable distribution merely has a tail we had not
sampled. The lesson is cheap and general: a reps-to-significance figure is only as good as its
stationarity assumption, and the way to test that assumption is a re-run with a control model, not
a larger n.

### 7.3.3 Two cost estimators, and why both appear above

Two different numbers can be called "the cost of a cell", and they are not interchangeable:

| | How | Used for |
|---|---|---|
| **median profile** | take the median of each token column (uncached / cache-read / cache-write / output), *then* price it | **every published dollar figure in §7.3** — it is the cell's typical token profile, priced |
| **per-rep** | price each repetition, *then* take statistics | SDs, Cohen's *d*, permutation tests — anything needing spread |

They disagree, because the median of a sum is not the sum of the medians: on `xlsx-fin-font-clean`
the same 5 versus 5 data gives a 33.5% saving one way and 26.0% the other. Quoting one beside the
other's *p*-value without saying so is how a table goes stale, so `tools/cost_significance.py`
prints both columns and every table above labels which it is using. The disagreement widens with
skew — in the pooled row of §7.3.2 the two estimators do not even agree on the **sign**, which is
itself a symptom of the right tail described there.

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
| `sonnet-4-6` | 196,634 | 2nd | 0.0839 | 3rd |
| `sonnet-5` | 200,732 | 3rd | 0.0588 | 2nd |
| `haiku-4-5` | 204,034 | **4th** | 0.0313 | **1st** |

**`opus-5` is the most token-efficient and the least cost-efficient model tested.** Quoting a
single number and calling it "efficiency" picks the answer by accident. Where the two are
reported together in this document, the measure is always named.

### 7.5 A subagent's calls land in the totals — and can't be separated out

An LLM call can trigger further LLM calls: a subagent (`Agent`) runs its own agent loop.
**Cortex counts those**: the child's `HTTPS_PROXY` is inherited by its subprocesses, so a
subagent's traffic crosses the same proxy and lands in the measurement window as ordinary
response events. For cost that is correct — those calls are real and billed.

A **background task** (`TaskOutput`/`TaskStop`) is not the same thing and issues no LLM calls of
its own: it is an asynchronous *shell* command whose output the main loop reads later. Its
tokens are the main loop's. The distinction matters because conflating the two produced a
6-fold error in a published figure, corrected below.

**They are not attributable, though.** On the wire a subagent's call looks exactly like the
main loop's, so:

| Measure | Effect |
|---|---|
| total tokens / dollars | **correct** — the calls really happened |
| tokens per LLM call | **unaffected** — still that model's per-call average |
| LLM calls per task | **inflated** — the "task" is no longer a single agent loop |
| skill-overhead ratios | **invalid** — compares two different amounts of work |

Measured impact of a **genuine subagent spawn**, against the other repetitions of its cell:

| Cell | with a subagent | without |
|---|---|---|
| `select-deck` SELECT | 46 calls / 2,485,834 tok (`Agent`×2) | 7, 7 calls / 0.31M, 0.29M tok |

That is **6.6×**, which is why such a repetition must be flagged rather than averaged in. It is
the only one in the dataset.

An earlier version of this table also listed two `pptx` repetitions at 2.7×–8.2×. They are not
in fact contaminated — they used a background *shell* task, not a subagent — and the table
overstated the case by comparing them against a median drawn from the *other* mode of a bimodal
cell. Both rows are withdrawn; see the correction immediately below.

**This detector was broken until 2026-09-09, and the first fix over-corrected.** It matched a
tool named `Task`, but this Claude Code build names the subagent tool `Agent`, so affected
repetitions were reported as clean. The fix added `Agent` — correct — but also made
`TaskOutput`/`TaskStop` a confound, which was wrong on both grounds:

- **Mechanically:** a background task here is a background *shell* command. It issues no LLM
  calls of its own, so every token still belongs to the single agent loop under measurement.
- **Empirically:** in both `pptx` tasks the single most expensive repetition carries *no*
  background tool (1,324k tokens unflagged vs 1,278k flagged; 2,541k unflagged vs 1,275k
  flagged). The flag marked a *subset* of an expensive mode, not its cause, so excluding on it
  biased the median rather than cleaning it.

Only `Agent`/`Task` remains a confound. Exactly **one** repetition in the dataset qualifies —
`select-deck` rep 1, at 46 calls / 2,485,834 tokens against 7 / ~0.30M for reps 2–3 of the same
cell (6.6×). It is excluded per-rep in `results/profile-manifest.json` (`excluded_reps`), which
keeps its two clean siblings — the very reps that make it legible as contamination.

**The `pptx` overhead figure is withdrawn, not corrected.** It was published as 18×, then as
3.0×; both were membership artifacts. The ON arm is bimodal — three low and three high
repetitions per task (207k/254k/663k vs 1,234k/1,278k/1,324k; 364k/380k/603k vs
1,275k/2,338k/2,541k) — i.e. **≈2.3× in the low mode and ≈7.9× in the high mode** against a
164k OFF median. The median of six falls in the empty gap between the modes, which is why a
single membership change could move it 6-fold. At n=6 the mode frequencies are unknown, so no
point estimate is defensible. These are retired tasks; the fix is more repetitions if the
number is ever wanted, not a better choice of median.

**The cost profile in §7.1–7.4 is unaffected.** Verified directly rather than assumed: the
current detector was re-applied to all 160 pinned repetitions, and every hit falls in the
retired `pptx` tasks or a `select` task — **0 of the 100 cost-grid repetitions**. So every
model-selection conclusion stands.

### 7.6 Skill overhead is a property of skill × model

Skill-on ÷ skill-off, in **both** measures — they differ, because the input/output/cache mix
shifts between arms even at a fixed unit price:

| Task | Measure | `haiku-4-5` | `sonnet-4-6` | `sonnet-5` | `opus-5` |
|---|---|---|---|---|---|
| `xlsx-fin-colors` | tokens | 2.88× | 1.54× | 1.98× | **0.94×** |
| `xlsx-fin-colors` | **dollars** | 1.97× | 1.44× | 1.80× | **1.04×** |
| `xlsx-fin-font-clean` | tokens | 3.33× | 2.06× | 1.44× | **1.01×** |
| `xlsx-fin-font-clean` | **dollars** | 2.21× | 1.69× | 1.32× | **1.08×** |

In dollars the skill adds **4–8% on opus-5** and roughly **doubles the bill on haiku**. Note
opus-5's dollar overhead sits slightly *above* 1.0 even where its token overhead dips below —
so "the skill is free on opus-5" is too strong; "barely noticeable" is accurate.

"What does this skill cost" has no single answer. `opus-5` barely notices it because it is the
one model that makes **more** LLM calls without the skill than with it (10 OFF vs 8 ON on
`xlsx-fin-colors`) — and twice as many OFF-arm calls as `sonnet-4-6` makes (10 vs 5). The
guidance replaces exploration rather than adding to it, which is why its token ratio can dip
below 1.0 at all.

### 7.7 Skill selection works

All candidate skills present (`xlsx`/`docx`/`pptx`/`pdf`), prompt names none, verdict from
the transcript. `sonnet-4-6`, n=3: **12/12 correct, 0 confounded** — including a prompt that
never says "spreadsheet" (fired `xlsx` 3/3) and a negative case where firing nothing is
correct (fired nothing 3/3, so no over-eagerness).

---

## 8. Model selection recommendation

**Adopt `claude-sonnet-5` as the default.** 100% pass on every task, and **never dearer than the
incumbent `sonnet-4-6` with evidence behind it** — *despite being less token-efficient*. Its 2/3
unit price more than absorbs the 1.21× per-call context. Stated at the precision the data
supports (scenario B, §7.3.1):

| Cell | median saving | is it established? |
|---|---|---|
| no-skill canary `cortex-pyfix-001` | 30% | **yes** — complete separation at n=5, under scenario A too, and it **reproduced in a second session** 25 h later at 30.6% (§7.3.2) |
| `xlsx-fin-font-clean` | 33% | **no** — *d* = 1.42, p = 0.056, and the 3 extra reps/cell that was meant to settle it instead **reversed the sign** in a fresh session (§7.3.2). Unresolved, and more reps will not resolve it |
| `xlsx-fin-colors` | 8% | **no** — 0.25 SE, p = 0.78. A tie; ~617 reps/cell to resolve |

Earlier drafts of this document said "more cost-efficient in all 3 cells", which read as three
independent confirmations when it was really one confirmation and two unresolved cells. **The
recommendation is unchanged, and it is worth being precise about why it survives:** it rests on
`sonnet-5` never being *established as dearer* anywhere, plus its 100% pass rate and the one cell
that does separate. A tie is not a loss. But two of the three cells should not be counted as
support, and on `xlsx-fin-font-clean` the honest statement is stronger than "unresolved" — that
cell drifted ×3.4 in cost between sessions for `sonnet-5` while `sonnet-4-6` held to within 5%, so
it currently supports **neither** direction. Note also that the scenario-A "swap" on
`xlsx-fin-colors` is not established either (p = 0.397), so that cell is better described as
*unresolved under both scenarios* than as *scenario-dependent*.

**Use `claude-haiku-4-5` only behind a validator.** Most cost-efficient in every cell, by 1.5–4.2×
over the next cheapest model — the narrow 1.5× is on `xlsx-fin-font-clean`, the cell where its 0.52
pass rate is already being charged for — and fastest (14–39 s vs 59–78 s). But it passed the harder
compliance task only **52%** of the time (n=29) *with the skill supplied*. This is the one cell
taken to n≈30, so the failure modes are the best-characterised part of the profile. Re-running the
verdict against all 14 retained failing workspaces gives the full taxonomy — 15 assertion failures,
because one repetition failed two:

| Failure | Count | Detectable without the skill's rules to hand? |
|---|---|---|
| mixed fonts across cells — `['arial', 'calibri']` (7×), `['calibri', 'cambria']` (1×) | 8 | maybe, on close inspection |
| wrong font — plain `calibri`, not on the approved list | 4 | **no** — needs the approved list |
| **hardcoded values instead of formulas** (0 formulas where ≥2 required) | 3 | **no — the numbers are correct** |

The shape of that distribution is the finding, not the pass rate. **Two thirds of the failures
(7 of 15 in the second and third rows) are undetectable by inspection** — you cannot see that
`calibri` is off-list without the list, and you certainly cannot see a hardcoded number. The
hardcoded-formula mode is the worst of them: the spreadsheet *looks* right and reports the right
figures, then breaks silently the first time an input changes. At n=5 it appeared once and could
have been dismissed as a fluke; at n=29 it recurs 3 times (~10% of all runs), so it is a
reproducible mode of this model on this task, not an outlier.

So the precondition for using haiku here is not tolerance of retries but **the ability to detect
the failure programmatically** — the same verdict the benchmark uses. Without a validator in the
pipeline you do not get retries, you get silent defects, and 7 of 15 of them would survive review.
With one, haiku's economics survive its failures on these tasks (cost per *solved* task already
charges for them, and the n≈30 re-run improved that figure, not worsened it); that will not hold
as tasks harden.

**Do not default to `claude-opus-5` where the bill is the constraint.** Least cost-efficient
in all three cells (1.7–2.0× `sonnet-5`) with no pass-rate advantage. But note the measure
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
2. **A deliberately uneven grid: 18 cells at n=5, 2 at n≈30** — 149 repetitions, some CVs up to
   0.85, so individual cost figures are indicative rather than tight. **Read the *n* column; do
   not quote a single *n* for this profile.** The tokens-per-LLM-call constants are trustworthy
   because they reproduce across five structurally different cells; a single cell's median is
   not.

   The unevenness is a spending choice, and the two cells chosen are the only two pass rates in
   the profile that are neither 0 nor 1 — the only two where sampling error could change a
   conclusion. Both moved when *n* grew (haiku `font-clean`/ON 0.40→0.52, opus `colors`/OFF
   0.20→0.37) and both 95% Wilson intervals roughly halved (0.65→0.34, 0.59→0.33), so the n=5
   readings were pessimistic rather than wrong. A **uniform** n=10 was considered and rejected:
   ~$14 and ~84 minutes to halve nothing that matters, since 16 of the 20 cells are already
   saturated at 0 or 1 and the one genuinely contested cost comparison (`sonnet-5` vs
   `sonnet-4-6` on `xlsx-fin-colors`, a ~0.25-SE difference) would need ~617 repetitions per cell
   at 80% power. Spending 50 repetitions on the two cells the headline claims rest on buys more
   than spending 100 spread evenly.

   Note also that this grid was *accidentally* uneven earlier, which is a different and worse
   thing: pooling by (task, arm, model) had swept in the same-day development sweeps, which
   existed only for `sonnet-4-6` and `sonnet-5`, so those two models sat at n=7–11 while haiku
   and opus sat at 5 — an uneven grid reported as a flat "n=5". Those 33 repetitions are now
   excluded by name, each with its reason, in `results/profile-manifest.json`; they remain on
   disk. Excluding them tightened the tokens-per-call spreads (`sonnet-5` 0.11→0.05, `opus-5`
   0.08→0.05) and moved no pass rate. The distinction that matters: unevenness is fine when it is
   chosen and labelled, and a defect when it arrives through a glob.
3. **Cache billing unverified** — the largest single uncertainty (4–5× on absolute cost). It does
   not change the conclusions that matter: `haiku-4-5` is cheapest and `opus-5` dearest in every
   cell under both scenarios, and the token/cost inversion holds either way. Do not quote an
   absolute dollar figure without settling it against a real invoice.
4. **Not every cost gap in §7.3 is a finding.** The tables are medians over n=5 and the
   per-repetition spread is wide, so §7.3.1 tests each gap that a conclusion rests on. One result
   is worth carrying: **the two sonnets are not resolved on `xlsx-fin-colors` under either
   scenario** (B: 8% apart, p = 0.78; A: 25% apart the other way, p = 0.40). It had been reported
   as a thin-but-real margin under B that "does not survive scenario A", which framed an absent
   answer as a scenario-dependent one. ~617 repetitions per cell would settle it; that is the one
   comparison in this profile where the honest move is to stop quoting it rather than to buy more
   reps. This report previously added that `xlsx-fin-font-clean`, at p = 0.056, needed only ~8 reps
   per cell and was therefore the cheapest available improvement. **That prediction was tested and
   is wrong** — see limitation 5.
5. **One cell is not stationary across sessions, and the instability is cell-specific.** Re-running
   `xlsx-fin-font-clean`/ON ~23 h later with everything we control held constant reproduced
   `sonnet-4-6` to within 3% on every measure but gave `sonnet-5` ×3.4 the cost, ×3.4 the LLM calls
   and ×4.1 the tokens for a byte-comparable deliverable, at the exact-test floor on every measure
   (§7.3.2). A second probe on `cortex-pyfix-001`/ON rules out a gateway-side change behind the
   `claude-sonnet-5` alias — `sonnet-5` reproduced there to within 0.1% on every volume measure, the
   `sonnet-4-6` control to 4% — which leaves a fat tail in the font-clean cell that n=5 missed.
   Three consequences.
   First, **a reps-to-significance forecast is only as good as its stationarity assumption** — the
   power figures in §7.3.1 estimate σ from 5 repetitions, and here σ was understated ~5×, which is
   ~25× in required repetitions. Second, **stability does not generalise across cells**: 2 of 20
   cells now have a two-session control, one held and one did not, so the other 18 carry drift we
   have not sampled either way. Third, **cost alone cannot detect drift** — pyfix's mean cost rose
   ×1.29 on an unchanged workload purely because one repetition's cache was cold, and reading that
   as instability was an error this report made and corrected. Volume measures are the test; cost
   and wall time are diagnostics. The generalisable fix is not a larger n, it is a re-run with a
   control model — cheap, and it is what turned an unexplained number into a located one here.
6. **Two tasks in one narrow genre.** Both discriminators are financial-spreadsheet
   formatting. This is not a general coding benchmark.
7. **`aws/` vs bare alias pricing** assumed identical; unprovable with a non-admin key.
8. **Wall-clock is gateway-dependent** and was not load-controlled; treat it as indicative.

**What would change the conclusion:** if the gateway does *not* discount cache reads,
absolute costs rise ~4–5× and cache-heavy agentic use becomes far more expensive in
aggregate — the ranking survives but budget planning changes materially. If harder tasks were
added, `haiku`'s reliability gap would likely widen and `opus-5` might start earning its
premium.

---

## 10. Reproducing

```bash
uv venv --python "$(cat .python-version)"   # 3.14.3 -- the apparatus, see below
uv pip sync requirements.lock
abctl service start                       # Cortex, forward + tls_bridge
python3 -m pytest -q                      # the harness's own tests (confound detector)
python3 tools/negcontrol_confound.py      # prove the detector fires; exits non-zero if not
python3 profile.py --run --reps 5         # the grid (~2.5 h, 100 invocations)
python3 profile.py --freeze               # pin exactly which reps the profile is built from
python3 profile.py --report               # recompile from the manifest, no invocations
python3 pricing.py                        # the rate card
python3 tools/cost_significance.py        # §7.3.1/§7.3.3: which cost gaps are established
python3 tools/stability_probe.py          # §7.3.2: which cells reproduced across sessions (--task)
```

**The apparatus matters to this list.** The venv runs the verdict that decides passed/failed,
and `harness.py` puts its `bin/` on the agent's `PATH`, so it is inside the experiment rather
than around it. Every repetition below was measured on **Python 3.14.3, pytest 9.1.1, openpyxl
3.1.5** — one apparatus throughout, the venv having been created a minute before the first
recorded row. `.python-version` and `requirements.lock` pin that; a reproduction on a different
openpyxl can move a compliance pass rate with no model involved. Rows recorded after
2026-09-21 carry `py_venv` and `venv_packages` and can be checked directly; the 193 here
predate those fields.

The last two exist so that no *statistic* in this document is retyped either. Both read the frozen
manifest through `profile.load()`, so a membership problem makes them shout in the same way
`--report` does, and every *p*, Cohen's *d* and power figure quoted above is one line of their
output.

Raw per-repetition records are in the gitignored `out/runs/` and `out/runs-archive/` — 256
repetitions across 66 files. Which of them belong to this profile is pinned in
`results/profile-manifest.json` (48 files, 210 rows with a sha256 each, 209 counted; of those, 24
grid files supply 150 grid repetitions — 149 after the confound filter — for §7's tables, and the
rest are the phase 2–3 task records). Membership is excluded at two granularities: **18 files** by
name (13 pre-grid development sweeps, one preflight canary and the 4 stability-probe runs of
§7.3.2) and **1 single repetition** keyed
`basename#rep`. The per-rep granularity exists because the `select-deck` sonnet-4-6 file holds one
contaminated repetition (46 LLM calls via a real subagent) beside two clean ones (7 calls each);
excluding the whole file would have destroyed the very comparison that makes the contamination
legible, and keying on `basename#rep` leaves the file's sha256 valid so integrity still covers the
bytes actually read. A rep exclusion matching no row is reported as `STALE REP EXCLUSION` rather
than silently doing nothing. `--report` reads only the manifest and says so
loudly if a file went missing or changed. Membership used to be a glob of both directories,
which meant any later harness invocation silently joined a published cell; a one-rep canary on
2026-09-09 did exactly that and moved a median. `--report` also asserts two token identities per
cell — `prompt == uncached + cacheRead + cacheWrite` and `total == prompt + completion` — and
quarantines any cell that fails them. None did: 0 violations across all 209 counted
repetitions, excluded ones included.
