# Check — SharedTool policy-bound implementation (provenance block)

- Decision: block
- Reviewer: independent `gpt-5.6-terra` / max, read-only
- Date: 2026-08-12

The implementation behavior is green: SharedTool policy is bounded at 500,
501 rejects at `$.error_policy`, ordering remains 500, compensation remains
160, Direct has no Skill/tools/workspace, focused tests report 55 passed, Ruff
and mypy pass, and production Python is 10,318 lines.

The block is evidence-only: `agent_world/design.py`,
`tests/test_design_semantics.py`, and the task node card are cleanroom files
still untracked against the old baseline, so plain `git diff` returned no
named-file delta. The reviewer requested an explicit stated pre-repair base and
the exact before/after change before deciding minimality. No code correction is
requested or permitted by this block.

Next: give the same reviewer the prior deterministic checkpoint as base and
the exact policy-only delta already authorized by plan digest
`1253f873e087b5ab822d5d844718020926cd9d0b3e52615bb283d692c53e99f8`.
Re-review current code and tests; do not change product files or run a live
proof before `allow`.
