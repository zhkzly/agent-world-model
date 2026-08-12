# Diagnosis — WorldArchitecture field contract was not model-visible

## Expected behavior

One fresh `world_architecture` Direct transaction should receive the frozen
need/evidence projection and a complete compact output contract, return source
semantics, pass the Designer compiler, and commit one architecture Artifact and
passed WorkRecord. It must not rely on retries to discover undisclosed schema
rules.

## Real scene

- Run: `run_5c648fca95e64bc08107b70a48127854`
- Node: `design/world_architecture`, `direct_llm`
- Route/model: configured primary `gpt-5.6-luna` through localhost; no fallback
- Result: failed WorkRecord, `world_architecture_invalid`, no output, no release
- Observe Finding: `finding_a5b1003e8e5a8fc8`, owner `designer`,
  `block_release`

Chronology:

1. The first real response was valid JSON and reached the compiler. It failed
   at `$.entities[0].fields[0].values`: an enum/list field did not satisfy the
   required cardinality. Framework returned the one authorized exact
   correction packet.
2. Luna produced a second complete object and moved beyond that field. It then
   failed at `$.entities[1].fields[3].values` because the finite domain was not
   unique.
3. The one local correction was consumed, so GraphRunner persisted both
   attempts, both real-operation usage records, Validation, a route-free
   Finding and a failed WorkRecord with no output. Downstream edges could not
   receive WorldRules input.

## Actual recipient view at the cutoff

The Direct recipient had no Skill, tools, workspace, Hook or release
authority. It saw the generic Direct system instruction, the need/evidence
projection, and this field portion of `output_shape`:

```text
fields[1..24]{name,category,required,values,entity_ref}
```

Tool `argument_fields` and `result_fields` were named but did not disclose the
same nested field shape. The recipient could infer the five keys, but not the
closed category set, boolean requirement, conditional `values` cardinality,
uniqueness rule, empty-values rule, reference rule or owner-local uniqueness.
Those rules existed only in the framework compiler/task documentation, neither
of which is model input.

The route used `temperature=0`, `max_tokens=4096`, a 120-second timeout and
returned usage for both real calls. The provider, JSON parser and adapter are
therefore not the failing boundary.

## Causal attribution

The supported cause is an incomplete Direct output-shape disclosure. The two
independent compiler paths are both rules absent from the rendered model view;
the precise first correction was followed, which weakens a Luna instruction-
following hypothesis. Upstream evidence cannot supply structural JSON rules,
and adding retries would merely reveal hidden constraints one at a time.

Rejected remedies:

- do not switch model or route;
- do not increase local corrections/provider retries;
- do not weaken the compiler or accept duplicate/empty finite domains;
- do not attach a Skill/tool/workspace to this Direct node;
- do not add a schema framework, profile, callback or compatibility path.

## Repair boundary

Make the existing `world_architecture` `output_shape` a compact but complete
description of the already-enforced field/tool/reference rules and test the
actual rendered recipient view. Keep compiler semantics, graph edges,
correction budget, backend and downstream contracts unchanged. A fresh real
node proof is required; this diagnosis itself authorizes no edit or retry.

