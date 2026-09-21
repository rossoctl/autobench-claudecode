# Discarded 2026-09-21 — the rule passed 3/3 on the OFF arm with docx-js FORCED

Skill-OFF pre-screen, `claude-sonnet-4-6`, 3 repetitions, `as-installed` skills
(`out/modelskill/docxjs-us-letter-off-claude-sonnet-4-6-20260921130538.ndjson`). The summary
line reads 2/3, and that number is misleading in a way worth recording:

| repetition | `test_page_size_is_us_letter_not_a4` | `test_memo_addressed_and_dated` |
|---|---|---|
| 1 | **pass** | fail — wrote "all US offices", not "All Staff" |
| 2 | **pass** | pass |
| 3 | **pass** | pass |

**The rule under test passed 3 of 3.** A default docx-js document is A4 (11906 × 16838 twips,
measured against `docx@9.7.1`), so the footgun was genuinely in front of the model — and all
three repetitions set `size: { width, height }` to US Letter unprompted, in one case explicitly
because the prompt says "This is for our US offices and will be printed". Naming the library
removed the path dependence that killed the retired `docx-us-letter`; it did not create any
headroom, because page size is something the model decides from the audience rather than from
the library default.

The single failure was the **structure guard**, and it was too literal: it required the string
"all staff" when the prompt says "Address it to All Staff", and a memo addressed "To: All US
Offices" satisfies the brief. Left as written rather than repaired, because fixing the guard
would produce 3/3 and a cleaner discard, not a task.

Two lessons carried into the developer guide:

* A summary pass rate does not say *which* assertion failed. A 2/3 whose failures are all in
  the structure guard is a 3/3 on the rule — i.e. no headroom — and reading it as "marginal,
  worth an ON arm" would have bought three ON repetitions (~$1.30) to measure nothing.
* A structure guard should test that the artifact IS the briefed document, not that it quotes
  the brief. Token checks on content words ("retention", "privilege") survive rephrasing;
  token checks on a salutation do not.

Cost of establishing that: 3 repetitions, $0.26, 5 LLM calls each, ~28s wall each.
