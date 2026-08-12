# Shared Guidance

Do not reconstruct project plans from deleted Goal, Trellis task, journal, workflow, or research-note documents.

Use `docs/agent-world-environment-generation.zh.md` as the architecture source of truth.

- [Agent World debugging and real-execution loop](agent-llm-node-debugging.md): required
  causal process for every real failure; use its time-ordered role-play walk for any
  confusing Direct/Agent result, and use the LLM-specific branch only after it is a
  supported runtime hypothesis.
- [Foundry product-alignment checkpoints](foundry-product-alignment.md): required
  at every key graph/child/release boundary so StateGraph, tests, cleanup, and
  task progress remain subordinate to the natural-language-to-EnvironmentPackage
  product goal.
