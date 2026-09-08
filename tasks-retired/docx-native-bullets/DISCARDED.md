Discarded 2026-09-08 by the skill-OFF pre-screen: passed 2/2 WITHOUT the docx skill
(claude-sonnet-4-6).

The reason is more interesting than "the model already knows the convention". The docx
skill's Critical Rules are corrections for footguns in the library IT mandates, docx-js:
docx-js defaults to A4, accepts WidthType.PERCENTAGE, and lets you type "* " as a bullet.
The unaided agent reaches for python-docx instead, whose defaults already satisfy all
three rules -- so it never meets the footguns and passes without needing the guidance.

The rules are real, but PATH-DEPENDENT: they only bite on the path the skill itself
recommends. Measuring them therefore requires forcing the docx-js path in both arms,
which is a different experiment (does the skill help you use docx-js correctly?) than the
one these tasks were built for.

Cost note from the ON arm: 24 LLM calls / 501s / 1.03M tokens versus 5 calls / 27s /
160k for OFF -- 6.5x tokens and 18x wall for the same verdict.
