Discarded 2026-09-08. Passed on BOTH arms once the verdict was corrected:
OFF 2/2, ON 3/3. The unaided model already builds a real size hierarchy
(measured 58pt display / 34pt slide titles / 14-22pt body), so the rule
cannot discriminate.

FIRST SCORED WRONG, and the correction matters. The original verdict keyed off
`slide.shapes.title`, which is None when a deck is built from blank layouts with
plain text boxes -- which is what the skill's own pptxgenjs path does. It
therefore failed a compliant deck and reported ON 0/3, i.e. "the skill does not
help", when the truth was "my test measured placeholders, not size contrast".
The shipped verdict is placeholder-independent and re-scoring the same
artifacts flipped the result to 3/3.

Cost, for the record: ON 2,338,340 tokens / 393s versus OFF 132,499 / 35s --
about 18x tokens and 11x wall for no verdict difference.
