---
name: agent-world-roleplay-debugging
description: "Apply the general $roleplay-debugging method to a real Agent World Direct LLM, Codex Agent, validator, feedback, or control-plane failure. Use only after locating the actual node-visible evidence; this project-local entrypoint maps Agent World terms to the generic chronological role-play method and is not a Runtime Skill."
---

# Agent World Roleplay Debugging

Use `$roleplay-debugging` for the general method. Its core is deliberately not
an Agent World workflow: trace what each participant could see, infer, decide,
and emit in time order, then repair the first causal deviation.

This local entrypoint adds only the repository-specific vocabulary. Do not make
an Artifact commit, Candidate, Integration, or LLM a required step in a trace.
Use whichever real handoffs exist in the case.

## State the expected behavior from project authority first

For this repository, derive the Expected Behavior Sheet from the source-of-
truth document, the relevant frozen WorkDefinition/input contract, and the
actual validator/gate policy. State the intended next outcome and observable
milestones before reading the failure backwards. A commit, repair, or downstream
consumer belongs in that sheet only when the selected path actually defines it.

## Map the execution view correctly

- **Direct LLM:** only rendered Prompt/input plus authorized correction; no
  Runtime Skill, tool, workspace, Hook, or profile instruction.
- **Tool-enabled Codex Agent:** actual Prompt/input, one discoverable mounted
  Skill, granted tools/workspace, and attached authorized feedback.
- **Deterministic validator/Integration:** its exact input projection, process
  boundary, gate, and feedback. Do not invent an Agent Prompt for it.
- **Control plane:** ownership, attempt, lease, lifecycle, and route facts;
  it authorizes paths but does not invent semantic corrections.

Freeze this view at the attempt/event's temporal cutoff. A future Integration
report can become visible to a new repair attempt only through an explicitly
attached safe feedback brief; it was not visible to the earlier producer.

## Use Agent World evidence without hindsight

Start from `observe scene`, then read the smallest safe attempt/profile/Prompt/
Skill/validator/control record needed to reconstruct the actual ordering. Use
attempt IDs, input fingerprints, commit refs, operation state, and telemetry
only where those concepts exist in the case. Preserve unknown gaps rather than
using repository/Judge access as if it had been mounted for a runtime role.

After locating the first deviation, return to `agent-world-debugging` for its
five-lens attribution and `agent-world-real-execution-proof` for the real
boundary proof. This entrypoint does not itself authorize retry, repair, or
release.
