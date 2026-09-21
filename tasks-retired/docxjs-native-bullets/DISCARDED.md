# Discarded 2026-09-21 — passed 3/3 on the OFF arm with docx-js FORCED

Skill-OFF pre-screen, `claude-sonnet-4-6`, 3 repetitions, `as-installed` skills:
**3/3 passed**, all three verdict assertions, no confounds
(`out/modelskill/docxjs-native-bullets-off-claude-sonnet-4-6-20260921125547.ndjson`).

The retired `docx-native-bullets` died of PATH DEPENDENCE: the rule ("never use unicode
bullets — use a real numbering definition") is a correction for a docx-js footgun, and the
unaided agent reached for python-docx, whose list styles already satisfy it. This task was the
fix: the prompt names the library (`docx` npm, pre-installed), so both arms meet the footgun.

**Forcing the library removed the path dependence but not the ceiling.** Handed docx-js and
asked for a list, the model reaches for `numbering: { reference, level }` on its own in every
repetition. The rule is good practice that the model already follows — the second of the five
ways a task dies (see the developer guide, "Why a task dies"), and the same death as
`pptx-size-contrast` and `pptx-not-text-only`.

Kept as evidence that the forced-library experiment was worth running: of the three `docxjs-*`
tasks it produced, this one has no headroom, `docxjs-us-letter` has none either, and
`docxjs-table-dxa` discriminates 2/3 — so the hypothesis was right about *which* rules the
library hides, and wrong about how many.

Cost of establishing that: 3 repetitions, $0.40, 6/5/7 LLM calls, ~30s wall each.
