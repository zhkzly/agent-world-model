---
name: agent-world-debugging
description: "Investigate a real Agent World failure or confusing result before changing code, Direct Prompt/input, an Agent-only Runtime Skill, profile, feedback, project Agent view, or retrying. Use after a failed/stalled node, weak scene, unexpected runtime behavior, or unclear real test result; establish five-lens attribution and one true-boundary proof first."
---

# Agent World Debugging

Use this Skill only from one real event. A patch, retry, pytest pass, or E2E
restart is not a diagnosis. Keep the project-execution Agent, a Direct LLM,
and a tool-enabled runtime Codex Agent separate:

- Project Agent: local task, scene, source, and on-demand paths.
- Direct LLM: rendered Prompt/input plus authorized correction only; no Skill,
  Hook, tool, workspace, or profile instruction surface.
- Runtime Codex Agent: rendered Prompt/input, one mounted Runtime Skill,
  granted workspace/tools, and authorized feedback.

## First establish an actionable observation

1. Read observe scene.
2. Read the smallest attempt, Artifact, Prompt, profile, Skill, source, or
   control record that explains its chronology.
3. State what ran, what is known, what remains unknown, and the one next read.

For a cleanroom Direct or Observe claim, establish this before the five lenses:
the public path, including composition root and process launch, did not load or
call forbidden legacy control authority. If it did, record a hybrid/cutover
failure and return to the authority boundary. Do not diagnose Prompt, Skill,
model, or candidate semantics from that run, and do not count it as a product
proof.

If those facts cannot distinguish two plausible causes or name a precise next
read, improve feedback/observability before changing semantics or retrying.
For the exact five-lens evidence and recipient-safe feedback route, read
[references/attribution-and-feedback.md](references/attribution-and-feedback.md).

## Attribute before selecting a repair

Mark each lens as **supported**, **weakened**, or **unknown**, with an exact
locator:

1. project-execution Agent view;
2. effective runtime Prompt/input;
3. Agent Runtime Skill, or Direct's no-Skill invariant;
4. code/execution boundary;
5. feedback/observability.

These lenses overlap. Repair only the first evidenced cause and directly
coupled surfaces; do not choose code merely because it is editable.

## Hand off a diagnosis, not a patch

Persist a Diagnosis Record in the active task research directory before
proposing a code, Prompt, Skill, profile, configuration, contract, test, or
retry change. Record the safe Observe facts, causal hypothesis and alternatives,
five-lens status, owner/boundary, rejected strategies, smallest next proof, and
what remains unknown.

This skill does not issue `allow`/`block` and does not authorize a repair. The
plan writer turns the Diagnosis Record into a repair-plan revision; only then
does agent-world-cross-layer-critic review the plan. For an observability
defect, the observability improvement is itself a repair plan and follows the
same gate. Do not move the critic ahead of diagnosis or retry while a plan is
blocked.

## Load detail only for the live case

- For a confusing Direct/Agent handoff, first use
  [agent-world-roleplay-debugging](../agent-world-roleplay-debugging/SKILL.md)
  against the evidence available at that time.
- For no-first-event, timeout, SDK startup, Provider, route, or cancellation,
  read [references/liveness-control-ladder.md](references/liveness-control-ladder.md).
- Before changing a Runtime Skill bundle, read
  [references/runtime-skill-bundle-design.md](references/runtime-skill-bundle-design.md).
- Before changing Prompt, Skill, feedback, deterministic code, retry policy, or
  test strategy, read [references/repair-and-proof.md](references/repair-and-proof.md).

Malformed JSON, missing fields, a failed test, or a timeout does not select a
remedy by itself. Preserve credible alternatives until a real boundary
weakens them.

## Prove, then chain

State the before/after falsifiable claim. Run the smallest real boundary that
can disprove it, then move to immediate Integration and only later to E2E.
Pytest, lint, typing, and structural checks are regression guards, not a live
node, repair-loop, Integration, or E2E proof. Stop at the first new terminal,
read its scene, and begin a new attribution.

Record the boundary, frozen-input provenance, five-lens status, chosen and
rejected strategies, proof result, safe evidence path, and what remains
unproven.
