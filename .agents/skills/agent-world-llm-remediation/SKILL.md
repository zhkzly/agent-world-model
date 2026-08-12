---
name: agent-world-llm-remediation
description: "Explore and repair a runtime Agent/LLM generation or revision problem only after agent-world-debugging has established an observable real node event and kept the runtime Agent/LLM boundary as a live hypothesis. Use for Direct Prompt/input, one mounted Agent Runtime Skill, correction feedback, regeneration, model/profile behavior, or a bounded repair turn; not as the entry point for infrastructure failures."
---

# Agent World Runtime Agent/LLM Remediation

Enter only after agent-world-debugging has established a real, sufficiently
observable node event. This is not a generic response to every failed command.
The project-execution Agent view is not runtime model input.

## Reconstruct the actual recipient view

Freeze the node-facing evidence at the attempt cutoff:

- Direct LLM: rendered Prompt/input and authorized correction only; Skills,
  Hooks, tools, workspace, profile instruction fields, and outbound Provider
  instructions must be absent.
- Codex Agent: rendered Prompt/input, the actual mounted Skill, granted
  workspace/tools, frozen inputs, and authorized feedback.

Also identify model/route/response mode/budget, validation result, safe scene,
and whether fresh generation, correction, or only diagnostic execution is
authorized. Read
[references/reconstruct-runtime-view.md](references/reconstruct-runtime-view.md)
for the precise evidence and zero-event branch.

If the view cannot say what the model could infer, what it may have missed, and
what remains unknown, return to agent-world-debugging: the first repair is
feedback/observability, not another model turn.

## Choose a causal mechanism

Keep Prompt/input, Agent-only Skill, missing/misleading context, model/profile,
adapter/parser/validator/upstream input, and weak correction feedback as
competing explanations. A malformed object, missing field, refusal, timeout,
or failed test does not choose one automatically.

First exclude a cleanroom authority-firewall failure. If the observed path
loads or calls forbidden legacy control authority, it is a hybrid/cutover
defect, not an Agent/LLM remediation hypothesis.

Read [references/remediation-selection.md](references/remediation-selection.md)
before selecting regeneration, bounded correction, deterministic mechanics,
model/profile change, or retry. It also defines the recipient-safe feedback
route. Never ask a runtime model to repair path, route, timeout, adapter, or
authorization facts it cannot own.

## Submit remediation as a plan

This skill may turn a supported Agent/LLM hypothesis into a bounded remediation
proposal, but it does not execute a retry or edit a model-facing surface by
itself. Link the Diagnosis Record, target recipient view, selected mechanism,
rejected alternatives, retry bound, and expected proof in a repair-plan
revision. agent-world-cross-layer-critic must allow that plan before changing
Prompt, Runtime Skill, feedback, profile, adapter, retry policy, or code.

## Prove the selected change

Use agent-world-real-execution-proof: a real isolated Direct node for a Direct
claim; a real isolated Codex Agent node with the mounted bundle and tools for
an Agent claim; and the current authoritative graph route for repair-loop
claims.
Read the new scene after every real attempt. If the evidence changes, return to
agent-world-debugging rather than continuing the old hypothesis.
