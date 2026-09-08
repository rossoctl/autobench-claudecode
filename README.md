# AutoBench for Claude Code

Automated benchmarking for Claude Code. The **subject under test is the Claude Code agent
itself**: a benchmark run is a set of tasks, each task is one headless `claude -p` session
in a fresh workspace, scored by a programmatic verdict.

There is no LLM judge. A task passes when a command exits 0 — that is the whole point, and
it is what separates a benchmark from a load generator.

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
hypothetical: **2 of the first 5 xlsx tasks died this way** — `claude-sonnet-4-6` already
writes `=prev*(1+$cell)` instead of hardcoding a growth rate, and already applies
`$#,##0`/`0.0%`/`0.0x` unprompted. They are kept in `tasks-retired/` with the reason, because
a discarded task is a result. Run `sweep.py --arm off` before ever believing an ON arm.

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

## Security

`out/` is gitignored and must stay that way. The Cortex session API is **unauthenticated**
and its events carry `inference.messages` and `inference.completion` — full prompts and
model output. The NDJSON therefore stores a **field whitelist**; skill verification matches
its marker in memory and emits only a boolean.

## License

Apache 2.0 — see [LICENSE](LICENSE).
