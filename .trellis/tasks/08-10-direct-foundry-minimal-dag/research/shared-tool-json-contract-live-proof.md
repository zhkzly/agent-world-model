# SharedTool JSON contract live proof

Date: 2026-08-12

## Result

`allow` for one fresh public Direct E2E.

- Proof run: `run_11f4549f984443d08a77acf5b66227b0`
- Exact frozen parents from failed public run
  `run_4528cf8a411a4d8a82b6390465c6d138`:
  - Architecture `sha256:35f086360317dac4bb54e6da1c5baca7153510b2753968f5155ed1c350e9adca`
  - Evidence `sha256:7eb56be3ea7d336ed39744c78f3103c717b7242ff68333c86dc3c514379163b3`
- Node/shard: Direct LLM `shared_tool_semantics[1-2-3-4-5-6]`
- Model: `gpt-5.6-luna`; no Agent, Skill, tools, workspace, candidate
  process, response-mode change, or fallback
- Result: one attempt, zero correction; six atomicity, concurrency and
  idempotency domains plus six error policies compiled
- Artifact: `design.shared_tool_semantics:2ac8ec6e2555900c`
- WorkRecord: `passed`; Observe has no Finding and release `not_published`

Framework retained exact group/parser/compiler/Artifact/Work authority. This
proves only the repaired SharedTool boundary, not ToolSemantics, remaining
Design, Candidate, Judge, Registry, Repair, Expand or Consumer/SFT/RL.
