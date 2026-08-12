# Diagnosis — SharedTool error policy still echoes framework cardinality

- Date: 2026-08-12
- Real run: `run_bb6693c8de48462b992686c4272f0439`
- Boundary: `design/shared_tool_semantics[1-2-3-4-5-6-7]`
- Owner/kind/model: `designer` / `direct_llm` / `gpt-5.6-luna`

## Expected behavior and ownership

SharedToolSemantics freezes one compact shared contract before per-tool Rule
drafts. Direct LLM owns the meaning of shared atomicity, concurrency,
idempotency, ordering, compensation and shared error handling. Framework owns
the already-frozen ordered tool group, exact validation, coordinates, compiled
contract/digest, Work/Artifact and release. This node has no Skill, tool or
workspace and must not become an Agent.

## Observed chronology

1. The repaired immutable-parent proof reused the exact Evidence and
   Architecture bytes from `run_1bec958e41ae4207beb4a7b40149f9c0`.
2. Both Luna calls returned parseable JSON through the primary route.
3. Both were rejected at `$.error_policy` with expected category `array` and
   `array must use the declared cardinality`; the second saw that correction.
4. Observe reports one failed Direct Work/Finding, no SharedTool output, no
   ToolSemantics call and `release=not_published`.

Safe evidence is under
`config/.agent-world-runs/runs/run_bb6693c8de48462b992686c4272f0439/`.

## Root cause

The source draft removed explicit tool indexes but still requires the model to
repeat one policy string per frozen tool in exact order. That is a mechanical
coordinate/cardinality echo, not additional shared business semantics. The
canonical design describes a shared error policy that covers the group; local
tool-specific errors are already owned by each later ToolSemantics shard.

Transport, parser, model route, correction bound and compiler fail-closed
behavior are healthy. Adding another cardinality example would retain the
wrong ownership and leave the same avoidable failure surface.

## Smallest causal repair

Make `error_policy` one nonempty bounded shared-policy string in the Direct
source draft. Framework deterministically binds that exact text to every member
of the frozen ordered group when constructing the existing
`SharedToolContract.error_policy` tuple and digest. Do not change the compiled
contract, fields, graph, retries or downstream consumers.

This is not framework-authored semantics: Luna supplies the policy text;
framework only repeats it across coordinates it already owns. Per-tool semantic
exceptions remain expressible in each ToolSemantics `errors[]` section.

## Falsifiable proof

After deterministic and independent checks, the same immutable-parent suffix
must commit SharedTool within two calls, then commit only
`tool_semantics[register_member]` before the harness stops. A new terminal begins
a new diagnosis. No suffix result proves complete Design, Candidate, Judge,
Registry, Direct E2E, Repair, Expand or Consumer/SFT/RL.

