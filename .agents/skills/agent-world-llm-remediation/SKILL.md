---
name: agent-world-llm-remediation
description: "Explore and repair a runtime Agent/LLM generation or revision problem after agent-world-debugging has established a sufficiently observable real node event and identified the runtime Agent/LLM boundary as a live hypothesis. Use to reason about effective runtime instruction/input, loaded Runtime Skill, correction feedback, regeneration, model/profile behavior, or a bounded repair turn; do not use it as the entry point for every runtime or infrastructure failure."
---

# Agent World Runtime Agent/LLM Remediation

Use this only after agent-world-debugging has read a real event and made the
runtime Agent/LLM boundary a live hypothesis. It is not a universal handler for
any failed command.

The runtime role Agent's context is distinct from the **project-execution
Agent view**. The latter helps a Code Agent navigate this repository through
task summaries and local paths. It is not input to the model under repair. If
the Code Agent cannot orient itself, use agent-world-agent-view-stewardship;
if the model did not receive useful runtime context, diagnose that here.

## Re-enter the runtime Agent's actual situation

Read the real node-facing materials, not similarly named source files:

- rendered effective runtime instruction for this coordinate: Prompt plus
  runtime input projection;
- Runtime Skill actually loaded by the resolved profile;
- runtime role context projection and frozen inputs;
- resolved model, route, response mode, budget, and timeout;
- output, validation result, and safe observe scene;
- whether this runner permits a fresh generation, correction turn, or only a
  first-attempt diagnostic.

Describe what the model could reasonably infer, what it may have
misunderstood, and what evidence is still absent. If that cannot be stated,
return to agent-world-debugging and fix the feedback/observability boundary
before asking the model to do more work.

Name the coordinate and actual projection/Skill/profile paths or identifiers
beside each reading. Do not substitute a similarly named repository template
for evidence about what this invocation actually received.

## Preserve competing explanations

An invalid object, missing field, weak proposal, refusal, timeout, or malformed
JSON is evidence, not a diagnosis. Keep the explanations supported by the
scene alive:

- the effective runtime instruction/input makes a condition ambiguous, global
  when it is per-item, or easy to overlook;
- the Runtime Skill lacks a reusable method, check, or correction habit;
- the runtime role context lacks a needed fact or gives a misleading one;
- the model/profile/route/response mode/budget is unsuitable or unreliable;
- parser, schema, validator, scheduler, adapter, or upstream input owns the
  failure;
- correction feedback lacks enough story for a safe useful revision.

Do not call a Prompt or Skill defective merely because one model failed. Do
not call invalid JSON an adapter defect merely because parsing failed. Ask what
a bounded real experiment would weaken each explanation.

## Route the corrective information deliberately

The project-execution Agent receives the rich safe investigation narrative and
source navigation. The control plane receives only authorization and settlement
facts. The runtime role Agent receives a correction story only after a strategy
is chosen and repair authority exists.

Do not feed raw opaque provider output or an adapter error to the runtime model.
Do not ask it to solve profile, route, timeout, or authorization defects.

For an authorized bounded correction, the narrative can be prose:

> You produced a candidate for the same frozen task. Validation found that
> task_requirements[2].terminal_conditions is absent. Preserve valid task
> requirements unless consistency requires a change. Return one complete
> replacement object and no explanatory text.

Adapt this to the real failure. State what happened, what failed, what remains
frozen, what can change, and what complete success looks like. Include a prior
candidate only when disclosure is safe, useful, and authorized.

## Select a mechanism rather than a ritual

- **Improve guidance then generate:** change a proven runtime
  instruction/input, Runtime Skill, or model capability/profile cause; audit
  every live projection; then make a new generation.
- **Bounded correction:** use when a candidate is locally repairable, precise
  feedback can preserve valid work, and the runtime permits repair.
- **Formatting investigation:** malformed JSON or a wrong envelope may call
  for runtime-instruction/input or Runtime Skill self-checks, a format
  correction, response-mode or profile change, adapter extraction repair, or
  better feedback. Select from the evidence; never map the label to a mandatory
  hard-coded response.
- **Deterministic mechanics:** own IDs, wrappers, ordering, serialization,
  authorization, and known parser/validator defects in code. Keep semantic
  business reasoning with the model when that is the product's intended work.

Fresh generation is meaningful only after a causal change. A correction turn
is not a disguised retry: it needs an intact candidate, a bounded requested
change, useful feedback, and explicit authority.

## Prove the selected claim

Hand off to agent-world-real-execution-proof. Use a real isolated node for
runtime instruction/input, Runtime Skill, profile, or model-behavior claims.
Use the normal Scheduler path with actual repair authority for a repair-loop
claim; a diagnostic one-attempt runner proves only first generation and
validation. Read the new scene after each real attempt and return to
agent-world-debugging if the evidence changes the attribution.
