# Minimal repair plan R1 — disclose the complete existing WorldArchitecture contract

This revision addresses the actionable block in
`cross-layer-review-7beeb872-architecture-contract.md`. It remains local and
does not absorb the unproved risk in later Direct nodes.

## Goal

Let the Direct producer satisfy the framework's existing
`WorldArchitecture` compiler contract without adding authority, retries,
normalization, compatibility, or another abstraction.

## Exact implementation

1. Change only the `output_shape` argument used by
   `DesignExecutor._direct_architecture`. Do not add a schema class or alter
   `_direct_commit`. Its exact canonical value must be:

   ```text
   Exactly one object with keys name, summary, tools. name: 2-80 chars matching [a-z][a-z0-9-]{1,79}. summary: nonempty text, max 500 chars. tools: 1-4 items with unique names. Each tool is exactly one object with keys name, description, arguments, result_fields. Tool name: 1-60 chars matching [a-z][a-z0-9_]{0,59}. description: nonempty text, max 500 chars. arguments: 0-6 unique nonempty strings, max 60 chars each. result_fields: 1-6 unique nonempty strings, max 60 chars each. No hash, digest, manifest, gate, judge, release, reward, termination, or seed fields.
   ```

   This is a single bounded instruction string describing only conditions the
   current compiler already enforces.
2. Add one focused test using the real `_direct_architecture` transaction with
   a capturing Direct stub. Assert exact equality with the canonical string
   above—not keyword containment—then return a valid first proposal and assert
   one invocation plus the exact existing compiled Artifact payload. This
   proves root/tool closure, authority exclusion, text/name bounds, identifier
   patterns, unique tool names, argument emptiness/uniqueness/item bounds, and
   result-field nonemptiness/uniqueness/item bounds are all disclosed together.
3. Run deterministic checks. Then run the same frozen real Luna
   `world_architecture` proof and immediately read Observe.

## Cross-layer compatibility

- Producer changed: only the pre-invocation semantic instruction for
  `world_architecture`.
- Compiler and owner unchanged: Designer/framework still validates and commits
  the same authority-free object; the model gains no routing or release power.
- Consumers unchanged: `shared_tool_semantics`, sharded `tool_semantics`,
  `world_rules`, `curriculum_plan`, `task_requirement`, and `modeling_gate`
  receive the same compiled fields and identifier forms they already require.
- Artifact envelope, ports, WorkRecord, CandidateGraph, Package, Registry,
  Observe, Repair, Expand parent handoff, and Consumer package handoff remain
  unchanged.
- The similarly terse contracts of later Direct nodes are an explicit static
  risk but not an affected consumer or a failure proven by this diagnosis;
  this repair neither changes nor claims them.

## Explicit non-goals

No retry/model/route change, output normalization, compiler relaxation, generic
Prompt/schema builder, new node/edge/graph, Skill, Agent, Candidate, Repair,
Expand, Consumer, package, Registry, Observe, or historical-run mutation.

## Acceptance

- Every format rule currently enforced by the architecture compiler is
  available before the first model proposal through the exact canonical
  string above.
- A valid proposal still compiles and commits exactly the existing output
  contract in one invocation.
- Existing deterministic gates remain green.
- A fresh real node WorkRecord passes, or a new exact safe failure begins a new
  diagnosis. Neither result alone is E2E or product completion.
