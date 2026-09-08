Discarded 2026-09-08 by the skill-OFF pre-screen: passed 3/3 WITHOUT the xlsx
skill (model claude-sonnet-4-6), so it cannot measure the skill's contribution.

- assumption-refs: sonnet already writes =prev*(1+$cell) rather than hardcoding 1.065.
- numfmt: sonnet already applies $#,##0 / 0.0% / 0.0x unprompted.

Keeping the task would have manufactured a false positive in the ON arm.
