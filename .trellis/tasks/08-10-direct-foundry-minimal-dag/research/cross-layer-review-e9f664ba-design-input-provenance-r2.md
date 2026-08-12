# Cross-layer review: ModelingGate shared-input provenance closure

- Decision: allow
- Date: 2026-08-11
- Plan digest: `sha256:e9f664ba3e6e27fcf30cd3c60cb3c0981c58f49fb13210f2cd23b4fa15c66137`
- Plan revision: `direct-design-input-provenance-plan.md`, revision 2/2
- Scope classification: coordinated cross-node, confined to the existing Direct `DesignGraph`

## Trigger, evidence, and product target

This is the final bounded review of the static provenance gap recorded in
`diagnosis-design-input-provenance-gap.md` and the same-pattern ModelingGate
finding in `direct-design-provenance-whole-diff-recheck.md`.  There is no real
proof terminal or Observe scene to reinterpret: the evidence is static source,
graph, contract, and prior deterministic-check inspection.

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
This plan advances only the Design provenance part of that chain.  It does not
claim Build, isolated Runtime, Judge, Release, Registry, Observe, Repair,
Expand, Consumer, or end-to-end Direct proof.

Affected trust boundary: framework-owned declaration and persistence of every
immutable Artifact that can affect `modeling_gate` compilation and its committed
`EnvironmentDesign`.  A direct in-memory value is not a substitute for its
declared NodeSpec port, graph edge, exact ArtifactRef input, WorkRecord
dependency, and semantic-revision material.

## Decision basis

`DesignExecutor._modeling_gate` already accepts `shared` and writes it into
`DesignContract.shared_tool_contracts` (`agent_world/design.py:1977-2114`).
That contract is subsequently projected to Builder and package/Registry
consumers.  The current `modeling_gate` NodeSpec and `DESIGN_EDGES` omit
`shared_tools`, and its `graph.execute` input map and semantic material omit
`shared_refs` (`agent_world/graph.py:202-211`, `agent_world/graph.py:341-347`,
`agent_world/design.py:2098-2121`).  ToolDraft digest transitivity does not
record the exact shared-group Artifact that ModelingGate directly consumes.

The proposed correction is the smallest coherent coordinated scope:

1. ModelingGate must explicitly declare the existing `shared_tools` input.
2. Exactly one existing-domain edge,
   `shared_tool_semantics.shared_tools -> modeling_gate.shared_tools`, is
   sufficient.  It carries the ordered tuple of existing group Artifacts; no
   duplicate per-group edge, new port type, node, graph, or routing rule is
   warranted.
3. Passing the exact `shared_refs` tuple to `graph.execute` and binding the
   ordered ref digests in semantic material makes both the committed dependency
   closure and stale-reuse identity cover the values the compiler consumes.
4. In a one-tool/zero-shared-group Design, `shared_tools=()` is the correct
   optional input.  It represents zero artifacts, not a missing synthetic
   output; no fake Artifact or WorkRecord may be created.
5. The optional-port exception must remain a literal closed allowlist of only
   `tool_semantics.shared_tools` and `modeling_gate.shared_tools`.  This is a
   deliberate graph-contract exception, not a generic optional-input facility.

## Impact chain, ownership, and compatibility

```text
shared_tool_semantics Artifact(s)
  -> modeling_gate.shared_tools (declared exact refs)
  -> framework ModelingGate / EnvironmentDesign
  -> existing BuildPlan + CandidateGraph consumers
  -> existing package + Registry cold-read consumers
  -> safe Observe facts
```

The Designer remains the sole owner of `shared_tool_semantics` and
`modeling_gate`; `GraphRunner` remains the sole transaction/Artifact/WorkRecord
owner.  Builder, Judge, Controller ReleaseKernel, Registry, Direct LLM and
Codex Agent authority do not change.  The plan retains the existing output
shape, compiler, route, Node IDs, edge abstraction, package metadata, and
later-child handoffs.  Current downstream consumers remain compatible because
they already consume the same compiled `EnvironmentDesign`; the correction only
makes its pre-existing shared-contract input explicit and immutable.

## Smallest permitted implementation and proof

Permitted production work is limited to the named in-place declarations and
bindings in `agent_world/graph.py` and `agent_world/design.py`, together with
the already-scoped ResearchPlan/Evidence provenance edits and the listed
contract/test updates.  Preserve a net non-increasing production LOC result.
Do not add a module, node kind, graph, framework, compatibility path, retry,
Artifact format, WorkRecord, or synthetic empty shared Artifact.

The minimum deterministic regression set is sufficient if it proves all of the
following:

- the closed two-entry optional-port allowlist rejects every other optional
  port;
- ModelingGate declares the port and has exactly the one specified source edge;
- a changed shared-group Artifact with unchanged other modeled inputs changes
  ModelingGate's direct WorkRecord dependency closure and semantic identity;
- a one-tool Design passes the explicit empty tuple through ModelingGate with
  no shared Artifact/WorkRecord; and
- existing full pytest, Ruff format/check, mypy, compileall, diff check, and
  legacy-firewall checks remain green.

These are deterministic graph-boundary regressions, not true-boundary or live
product proof.  After implementation, the next permitted gate is a fresh
independent whole-diff recheck against this exact digest and affected boundary.
Only its allow may resume the already-ordered real proof sequence; any new real
terminal requires Observe before another repair decision.

## Explicit non-claims

This allow does not prove any real Researcher or Direct call, provider/Skill
behavior, candidate-process isolation, Build, Integration, Judge verdict,
Registry publication, EnvironmentPackage release, Repair, Expand, Consumer,
or end-to-end product completion.  It does not authorize plan changes or work
outside the listed files.
