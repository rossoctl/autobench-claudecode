# docx / pptx candidate gate — OFF arm only, 2026-09-21

**Model:** `claude-sonnet-4-6` · **Arm:** off (no skill) · **Repetitions:** 3 per task ·
**Skills:** `as-installed`, at the `skills/MANIFEST.json` digests · **Rows:**
`out/modelskill/*.ndjson` (outside `profile.RUN_DIRS`, so none of this can join the published
grid) · **Spend:** **$2.72 over 21 repetitions** (plan estimated ~$1.60, worst case ~$4)

The question this gate answers is the only one worth money before an ON arm: **does the model
already satisfy the rule without the skill?** A task that passes unaided cannot measure a skill
at any number of repetitions.

## Result

| task | OFF pass | fails on | outcome |
|---|---|---|---|
| `docx-brand-arial-black` | **0/3** | the rules: 11pt body 3/3, non-black headings 2/3 | **keep** |
| `pptx-dark-sandwich` | **0/3** | the rule: all five slides dark, `#0D1B2A`, 3/3 | **keep** |
| `docxjs-table-dxa` | 1/3 | the rule: `<w:tblW w:type="pct"/>` 2/3 | **keep**, marginal |
| `pptx-no-accent-lines` | 1/3 | the rule: 0.03–0.04in bars under titles 2/3 | **keep**, marginal |
| `docxjs-us-letter` | 2/3 | the **guard**, not the rule — page size passed 3/3 | **discard** |
| `docxjs-native-bullets` | 3/3 | nothing | **discard** |

Discards carry a `DISCARDED.md` in `tasks-retired/`. Of the eleven docx/pptx tasks written
across both rounds, four now survive a pre-screen.

## What the unaided model actually does

Worth recording, because each of these is a fact about the model and not about a task:

* **All-dark decks, three times, at the same hex.** Every `pptx-dark-sandwich` repetition set
  all five slides to `#0D1B2A`. The skill offers dark-throughout as its *other* option, so this
  is not a rule violation the model "nearly" avoided — it is a strong default aesthetic, which
  is exactly the headroom the sandwich rule needs.
* **Accent bars under titles.** 4.2in × 0.03in and 5.2in × 0.04in rectangles sitting 0.02–0.13in
  under the title — the "hallmark of AI-generated slides" the skill forbids by name, produced
  unprompted in 2 of 3 repetitions.
* **Unstyled documents.** Every docx repetition wrote every paragraph as `Normal` and made
  headings with direct formatting (bold Arial Black, 20–24pt). This broke the first version of
  the `docx-brand-arial-black` guard; see commit "Find docx headings by shape".
* **Arial, but 11pt.** The model reaches for Arial unprompted and sizes the body at 11pt — the
  Word default — in 6 of 6 repetitions. Heading colour was `000000` in three, `1A1A1A` in two
  and `0057FF` in one.
* **Page size follows the audience, not the library.** With docx-js forced (A4 by default), all
  three repetitions set US Letter, one of them citing "our US offices … will be printed" from
  the prompt.

## The forced-library experiment

The three retired `docx-*` tasks died of path dependence: their rules correct docx-js footguns,
and the unaided model uses python-docx, whose defaults already comply. The `docxjs-*` round
named the library in the prompt so both arms meet the footgun. Verdict on the hypothesis:
**right about the mechanism, wrong about the yield.** One of the three rules (table widths in
`dxa`, not `pct`) became a discriminator; the other two are things the model does correctly
whichever library it is handed.

## Costs, for planning the ON arm

| task | tokens (median) | wall (median) | LLM calls | $/rep (median) |
|---|---|---|---|---|
| `docx-brand-arial-black` | 261,490 | 43.9s | 7–9 | $0.135 |
| `docxjs-table-dxa` | 193,943 | 32.8s | 5–6 | $0.084 |
| `pptx-no-accent-lines` | 171,085 | 55.5s | 4–5 | $0.122 |
| `pptx-dark-sandwich` | 208,278 | 133.2s | 4–6 | $0.235 |

`pptx-dark-sandwich` is 3× the wall time of the docx tasks on the **control** arm, before any
of the skill's mandatory render-inspect-fix loop. The recorded pptx ON rows from the first round
ran 47 calls and 2.5M tokens; that loop is what `skills/pptx-v2` bounds, and the two arms of
that comparison are the reason this task is worth keeping despite being the dearest of the four.
