# Repair plan — disclose the existing ToolSemantics compiler contract

## Goal

Make the current per-tool Direct LLM boundary disclose every condition already
enforced by its compiler, with no retry, normalization, graph or downstream
change.

## Exact implementation

1. Replace only the `tool_semantics` output-shape string in
   `agent_world/design.py` with a complete bounded contract:
   - exact keys are `description`, `arguments`, `result_fields`,
     `success_result`;
   - description is nonempty text up to 500 characters;
   - arguments exactly echo `input.tool.arguments`, in order, as 0–6 unique
     nonempty strings up to 60 characters each;
   - result fields exactly echo `input.tool.result_fields`, in order, as 1–6
     unique nonempty strings up to 60 characters each;
   - success result has exactly those result-field keys and every value is a
     finite JSON scalar (`null`, boolean, number or string).
2. Add one focused transaction test that captures the actual Direct user
   payload for a four-argument tool and asserts the complete output contract is
   present. Keep the compiler and one-correction bound unchanged.
3. Run focused/full deterministic checks, an independent check, then one fresh
   real `tool_semantics` node proof before another full Direct E2E.

## Cross-layer claim

This plan intentionally does not alter the committed `ToolDraft`, WorldRules,
Curriculum, TaskRequirement, EnvironmentDesign, CandidateBuild, Integration,
Judge, Registry, Repair, Expand or Consumer contracts. It treats the current
compiler as authoritative and only makes its hidden conditions visible.

Because the task design describes richer per-tool RuleDraft semantics than the
current echo-oriented implementation, the critic must block this plan if that
unchanged output is not a sufficient semantic input for the executable
environment, independent Judge and future ToolSemantics Expand operator. Such
a block must identify the smallest coherent replacement contract rather than
request a generic rule engine or broad rewrite.

## Explicit non-goals

No third attempt, prompt framework, JSON Schema generator, model/route switch,
validator relaxation, output repair, node/edge change, generic Rule engine,
automatic Repair, Expand or Consumer implementation.

## Acceptance

- Exact shape disclosure and focused regression pass.
- Existing 101-test suite and all static gates stay green.
- One fresh real tool shard passes through the unchanged compiler.
- No Candidate, Judge, Registry or E2E success is inferred from that node proof.
