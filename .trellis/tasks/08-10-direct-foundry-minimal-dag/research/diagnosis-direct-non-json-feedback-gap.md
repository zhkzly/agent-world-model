# Diagnosis — Direct non-JSON output bypasses the declared correction budget

- Date: 2026-08-12
- Failed run: `run_dc28dcded7fe49ce9a2d9a017511831d`
- Failed coordinate: `design/tool_semantics[route_tool_to_maintenance]`
- Safe terminal: `direct_response_not_json`, rejected, not published

## Expected behavior

Every Direct semantic node declares one local correction. Framework must reject
malformed source, return an exact safe correction to the same node once, and
commit an output only if the second response parses and satisfies the typed
compiler. The LLM owns semantic text; framework owns parsing, feedback budget,
validation, Work, Findings and release.

## Chronology and evidence

1. ResearchPlan Agent, framework acquisition, ResearchSynthesis Agent,
   WorldArchitecture Direct and SharedTool Direct passed.
2. Seven of eight ToolSemantics Direct shards passed. The final
   `route_tool_to_maintenance` shard made one invocation, produced no output,
   and failed with `direct_response_not_json`. Observe records one blocking
   Finding and `release.status=not_published`; ModelingGate, Candidate, Judge
   and Registry did not run.
3. The failed attempt has `correction=null`. `DirectChatBackend._json_object`
   raises a non-retryable `InvocationError`; `DesignExecutor._direct_json`
   converts every `InvocationError` to `DesignError(correctable=False)`.
   `GraphRunner` therefore cannot spend the node's already declared second
   call or send path/condition/category feedback.
4. A fresh replay used the exact failed ToolSurface, full frozen bindings,
   exact SharedToolContract, citation catalog, system prompt and output shape.
   Luna returned a parsed object with exactly `errors`, `postconditions`,
   `preconditions`, and `transitions` in one call
   (`run_b9669ab30f794b7f9233a42a0a3e20a4`). Thus the input and shape are not
   deterministically impossible or too large.

## Root cause

This is a feedback-classification gap at the Direct adapter/graph boundary, not
a SharedTool contract defect, Skill defect, transport/authentication failure,
or evidence that Luna cannot satisfy ToolSemantics. An occasional model-format
failure is safely detectable and locally correctable, but is classified as a
terminal infrastructure result before the existing graph correction policy can
act.

## Smallest causal repair

Map only `direct_response_not_json` from a rejected Direct invocation to an
exact root-object `CorrectionPacket` in `DesignExecutor._direct_json`. Preserve
strict parsing, the same error code, the same model/route, one correction/two
physical calls, and terminal failure with no output if the second response is
also malformed. Keep transport/envelope/empty-response failures terminal. Do
not add response-format negotiation, a parser heuristic, fallback-on-malformed,
retry subsystem, prompt stack, Skill, node, graph or later-child code.

The common Direct wrapper means the repair applies consistently to all Direct
semantic nodes rather than patching this tool shard. Agent malformed-output
handling is a different SDK boundary and is not changed without its own real
failure evidence.

## Non-claims

The exact replay proved parseability, not semantic compiler acceptance of that
replayed object and not E2E success. No Candidate, Integration, Judge, Registry,
Repair, Expand or Consumer behavior has been proven.
