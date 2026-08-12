---
name: challenge-agent-world
description: Propose bounded public verifier intent for a frozen design.
---

Use only the supplied complete public family/tool/recipe catalog, schemas, and
rule summaries. Return exactly one closed `checks` object. Every check contains
`task_family_index`, `tool_index`, `family`, `argument_index`, and `risk`; choose
indexes only from the supplied catalog and do not assume any singleton.

`family` is one of `unknown_seed`, `alternate_difficulty`,
`idempotency_key_variation`, or `argument_variation`. Only the final family may
name a one-based scalar public argument index. Propose public semantic risk, not
case IDs, seeds, keys, mutated values, expected results, partitions, verdicts,
Findings, Gates, or release decisions. Do not read candidate source or sealed
data.
