# docx / pptx ON arm + baseline top-ups, 2026-09-22

**Model:** `claude-sonnet-4-6` · **Skills:** `as-installed`, at the `skills/MANIFEST.json` digests ·
**Rows:** `out/modelskill/*.ndjson` (outside `profile.RUN_DIRS`) · **Spend:** **$5.31 over 12
repetitions**, against a $3.10 estimate — see *Why this cost 1.7× the estimate* below.

Round 1 ([`docx-pptx-gate-20260921.md`](docx-pptx-gate-20260921.md)) established only a
precondition: four tasks whose rules the unaided model gets wrong often enough to leave headroom.
This round asks the question that headroom exists for — **does the skill close it, and what does
that cost?** — on the two tasks that were 0/3 unaided, and firms up the two that were 1/3.

## Result

| cell | pass | median $/rep | median tokens | median wall | LLM calls |
|---|---|---|---|---|---|
| `pptx-dark-sandwich` off | 0/3 | $0.235 | 208,278 | 133.2s | 5 |
| `pptx-dark-sandwich` **on** | **3/3** ⚠ confounded | **$1.168** | **2,182,760** | **561.6s** | **34** |
| `docx-brand-arial-black` off | 0/6 | $0.112 | 260,590 | 41.6s | 8 |
| `docx-brand-arial-black` **on** | **0/3** | $0.147 | 318,009 | 47.7s | 8 |
| `docxjs-table-dxa` off | 1/6 (was 1/3) | $0.097 | 194,623 | 27.9s | 6 |
| `pptx-no-accent-lines` off | 2/6 (was 1/3) | $0.166 | 172,830 | 89.5s | 5 |

`skill_on_wire` is `True` on every ON row and `False` on every OFF row, so the skill text
demonstrably reached the model in the arm that claims it. Every failure above is on the rule under
test — confirmed by re-scoring the surviving workspaces, not by reading a pass rate:

| cell | failing assertion, all reps |
|---|---|
| `docx-brand-arial-black` on | `test_body_text_is_arial_12pt`, `test_heading_text_is_black` |
| `docxjs-table-dxa` off | `test_table_width_uses_dxa_not_percentage` |
| `pptx-no-accent-lines` off | `test_no_accent_line_under_a_title` |

## The pptx skill works, and it is expensive

0/3 → 3/3, cleanly, on a rule the unaided model broke identically three times. That is the first
demonstration that a skill *other than* `xlsx` changes an outcome here.

The price is the finding, though. Against its own control arm, on the same task and model:

| | OFF | ON | ratio |
|---|---|---|---|
| tokens | 208,278 | 2,182,760 | **10.5×** |
| cost | $0.235 | $1.168 | **5.0×** |
| wall | 133.2s | 561.6s | **4.2×** |
| LLM calls | 5 | 34 | **6.8×** |

**⚠ All three ON rows are `confounded: subagent_invoked`.** The plan for this round asserted that
`ALLOWED_TOOLS` does not permit subagents, so the skill's `⚠️ USE SUBAGENTS` instruction could not
execute. **That assumption is false** — `--allowedTools` did not block `Agent`, and the model
spawned one or two per repetition. Consequences, both real:

1. The 3/3 cannot be attributed to the skill's *rules*. Part of it is a subagent performing the
   visual QA pass, and subagent calls are counted in the totals above but are not attributable to
   any particular instruction.
2. The 10.5× token figure is the cost of *the whole QA apparatus*, not of stating a rule.

Separating those two is precisely what `skills/pptx-v2` was written to do: it replaces the subagent
instruction and the open-ended `Repeat until a full pass reveals no new issues` with a single
bounded render-and-check cycle. Before this round that was a plausible experiment; it is now the
only way to interpret the number above.

## The docx skill does not help — and moves one rule the wrong way

0/6 unaided, **0/3 with the skill on the wire**, failing the same two assertions every time. The
effective formatting resolved from each artifact (run → paragraph style → `docDefaults`/theme):

| arm | heading colour | primary body size |
|---|---|---|
| off, 6 reps | `000000` ×3, `1A1A1A` ×2, `0057FF` ×1 | 12pt ×2, 11pt ×4 |
| **on, 3 reps** | **`1F3864`, `1A1A2E`, `1A1A2E`+`1F4E79`** | **12pt ×2, 11pt ×1** |

Read the columns separately, because they move in opposite directions:

* **Heading black got strictly worse: 3/6 exactly black → 0/3.** With the skill on, the model
  switched to a dark-navy palette every time. The docx skill *does* contain the rule — *"Keep
  titles black for readability"* — but only inside a docx-js code comment, and the model wrote
  navy titles anyway while that text was in its context.
* **Body size slightly improved: 12pt in 2 of 3 versus 2 of 6.** Both of those repetitions then
  added a 10pt caption line (`666666`, `888888`), which the verdict counts as body, so the
  assertion fails regardless.

This is the `skills/docx-v2` hypothesis surviving its first real test: the rules are stated only
where a docx-js user would meet them, and stating them as properties of the *document* instead may
be what makes them apply. The v2 overlay now has a measured reason to exist rather than an argued
one. Note also that the skill is not free even when it does nothing: +22% tokens, +31% cost.

**Candidate refinement, not yet applied:** `test_body_text_is_arial_12pt` treats every non-heading
paragraph as body, so a deliberate 10pt caption fails it. That is defensible for a brand rule that
admits no exceptions, but it means the body assertion is currently the stricter of the two rules by
accident rather than by design. Worth a decision before the v2 comparison runs, because otherwise
v2 could fix the heading rule and still score 0/3.

## The price of compliance is not a property of "skills"

Same model, same measurement, three skills:

| task | skill | verdict | cost | tokens | wall |
|---|---|---|---|---|---|
| `xlsx-fin-colors` | xlsx | 0/8 → 9/9 | 1.46× | 1.50× | 62s → 71s |
| `xlsx-fin-font-clean` | xlsx | 0/8 → 11/11 | 1.80× | 2.08× | 44s → 80s |
| `docx-brand-arial-black` | docx | 0/6 → 0/3 | 1.32× | 1.22× | 42s → 48s |
| `pptx-dark-sandwich` | pptx | 0/3 → 3/3 | **4.96×** | **10.48×** | 133s → 562s |

The two xlsx tasks buy a full conversion for roughly a 1.5–2× premium. The pptx skill buys the same
conversion for 5× the money and 10× the tokens, because its QA section is a loop rather than a
statement. The docx skill charges 1.3× and converts nothing. Whatever "the cost of using a skill"
means, it is a property of how an individual skill is *written*, not of the mechanism.

## The two marginal baselines

Both were topped up from 3 to 6 OFF repetitions at $0.10–$0.17/rep, on the reasoning that firming a
thin baseline on the cheap arm beats buying an ON arm against one:

* **`docxjs-table-dxa`: 1/3 → 1/6.** The second batch went 0/3, all three failing
  `test_table_width_uses_dxa_not_percentage`. Real headroom; promote it to the ON arm next.
* **`pptx-no-accent-lines`: 1/3 → 2/6.** Still marginal, and 2/6 is the least informative place a
  cell can sit. Given the cross-session non-stationarity already measured on a marginal cell, more
  repetitions inside one session will not settle it; a different session will.

That decision is also now retroactively justified: had these two gone to the ON arm at pptx rates,
they would have cost more than everything else in this round put together.

## Why this cost 1.7× the estimate

Budgeted $3.10, spent **$5.31**. The whole overrun is `pptx-dark-sandwich` ON at **$1.168/rep**
against a projected $0.42. The projection came from the retired pptx ON rows
(`pptx-size-contrast`, `pptx-body-left-aligned`: ~20 calls, ~0.94M tokens); this task drives 34
calls and 2.18M tokens, because the QA loop's length depends on what the deck looks like, not on
the task's size. **A per-rep cost taken from a different task in the same skill is not a budget for
a skill whose cost is a loop.** For the record, the four cells cost $0.36, $0.89, $0.47 and $3.59.

## What follows, and what it costs

| next | reps | est. | buys |
|---|---|---|---|
| `pptx-dark-sandwich` ON with `pptx-v2` | 3 | ~$1.50–3.50 | splits "the rules" from "the QA loop" — the one number this round cannot produce |
| `docx-brand-arial-black` ON with `docx-v2` | 3 | ~$0.45 | tests placement-vs-content directly, against a 0/3 baseline |
| `docxjs-table-dxa` ON, `as-installed` | 3 | ~$0.45 | a third docx cell, now that its baseline is 1/6 |

The `pptx-v2` estimate is a range on purpose: if bounding the loop works, the reps are cheaper than
the `as-installed` ones, and that reduction *is* the result.
