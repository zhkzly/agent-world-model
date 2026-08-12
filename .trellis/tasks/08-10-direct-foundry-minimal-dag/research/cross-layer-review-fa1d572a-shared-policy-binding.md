# Research: cross-layer review — shared policy binding

- Query: Independently review plan `shared-tool-policy-binding-plan.md` at exact SHA-256 `sha256:fa1d572a39fe6c1fd23e4e2a1f67e625cf11e06bcc3030dcff51f7a76fd247ca`, revision 1/2, after the Direct SharedTool suffix failure `run_bb6693c8de48462b992686c4272f0439`.
- Scope: internal
- Date: 2026-08-12

## Decision

Decision: allow

- Plan digest: `sha256:fa1d572a39fe6c1fd23e4e2a1f67e625cf11e06bcc3030dcff51f7a76fd247ca` (recomputed from the complete plan file).
- Plan revision: 1/2.
- Scope classification: coordinated Direct producer/compiler-to-consumer compatibility slice.  The implementation is local to the existing SharedTool source/compiler boundary, but it changes a model-facing source contract and therefore must retain the named compiled-ABI consumers together.
- Trigger and evidence: safe Observe for `run_bb6693c8de48462b992686c4272f0439` reports one failed `design/shared_tool_semantics[1-2-3-4-5-6-7]` Direct work, its blocking Designer Finding, no output Artifact, and `release=not_published`.  Both physical calls reached the typed compiler; the first received the exact `$.error_policy`/`array` correction and the second failed with the same safe code.  See the safe scene and stored attempts at `config/.agent-world-runs/runs/run_bb6693c8de48462b992686c4272f0439/run.json:1` and its `control.attempt` Artifacts.
- Affected trust boundary: Direct LLM group-level source semantics -> framework-owned frozen-coordinate binding and typed compilation -> immutable SharedTool Artifact/digest -> ToolSemantics -> Modeling Gate -> Candidate/package/Registry -> safe Observe.

## Product Target and Scope

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This allow advances only the failed Architecture/Evidence-to-SharedTool source handoff.  It does not treat a graph commit, deterministic regression, or suffix result as proof of the complete Direct product path.

The smallest coherent change is the proposed one: replace the source-level repeated `error_policy` array with one bounded shared-policy string and have framework pair that exact model-authored value with the already frozen ordered members.  Do not add another prompt paragraph, a union/override representation, normalization, a helper/module, route/retry change, node, Agent, or downstream-child implementation.

## Findings

### Shared meaning versus mechanical binding

Canonical Direct flow calls this transaction `SharedToolSemantics` and assigns it one shared error policy; after it commits, each `ToolSemantics` shard implements exactly one tool and its shared contract (`docs/agent-world-environment-generation.zh.md:601`).  The same canonical section reserves business-field meaning for the model while framework owns frozen mechanical identifiers; it requires exact group partitioning for atomicity/concurrency/idempotency and only requires error policy to cover the full group (`docs/agent-world-environment-generation.zh.md:603`).  The execution map independently identifies SharedTool error policy as a Direct group draft and per-tool error/transition semantics as the next Direct shard (`docs/direct-rewrite-execution-map.zh.md:71-76`).

Therefore this is the correct authority split for the Direct source producer:

- Direct LLM owns the one group-wide policy text and the remaining shared business semantics.
- Framework owns the frozen member coordinates, deterministic repetition into the compiled tuple, validation, Artifact/Work identity, digest, Gate, and release.
- Per-tool exceptions remain semantic, not mechanical: they belong in each `ToolSemantics` source `errors[]` and compile into that tool's `ToolDraft` (`agent_world/design.py:1450-1489`).

The change is not semantically weaker relative to this canonical split.  It intentionally stops Direct source output from expressing divergent per-member free-text policies under a field named `shared` policy.  It must **not** globally tighten `SharedToolContract` to require equal tuple values: its existing compiled ABI can still represent valid per-member pairs for non-Direct construction/fixtures (`agent_world/contracts.py:684-734`; `tests/test_graph_contracts.py:99-108`).  A future request to give Direct SharedTool a distinct per-tool shared-policy semantic is a new product-contract decision, not a reason to smuggle an exception array or prompt stack into this repair.

### Compiled ABI and downstream compatibility

Today the compiler accepts an exact-length source array, zips it to the frozen `members`, and persists the per-member `{tool_index, policy}` digest payload (`agent_world/design.py:1300-1358`).  The allowed edit changes only the source parse to one `_text(..., path="$.error_policy")` value and constructs the same `tuple((member, policy) for member in members)`.  The following must remain byte-shape compatible:

1. `SharedToolContract.error_policy` remains the ordered per-member tuple and keeps the same digest payload/validation (`agent_world/contracts.py:684-734`).
2. Every member's `ToolDraft` still binds the selected shared-contract digest; the whole compiled contract remains the visible input to each ToolSemantics shard (`agent_world/design.py:1471-1517`).
3. Modeling Gate accepts the same `shared_tools` port and passes the typed contracts into `DesignContract`, which verifies group order and each ToolDraft reference (`agent_world/design.py:2072-2119`; `agent_world/contracts.py:985-1042`).
4. Candidate projections and `world/rule_ir.json` serialize compiled shared contracts, not the Direct source JSON (`agent_world/candidate.py:304-322`, `agent_world/candidate.py:752-763`, `agent_world/candidate.py:2092-2100`).
5. Registry cold-read recomputes the same compiled shared-contract digest from the same per-member list (`agent_world/candidate.py:2536-2564`).  No Registry code change is warranted.
6. Observe projects Work/Finding/release facts and never projects the source policy itself (`agent_world/observe.py:498-536`).  No Observe change is warranted.

The graph semantic revision must change because the effective Direct output shape changes (`agent_world/design.py:584-626`; `agent_world/graph.py:442-460`).  Conversely, a prior repeated-array proposal containing the same policy text can compile to the identical `SharedToolContract` payload and digest.  That digest continuity is correct ABI preservation, not permission to reuse a stale SharedTool Work under the new source contract.

Future Expand is compatible only at the frozen compiled-ABI seam: canonical Expand must enter the same full Design/Build/Judge/Release path (`docs/agent-world-environment-generation.zh.md:96-125`; `docs/direct-rewrite-execution-map.zh.md:30-47`).  This allow neither implements nor proves Expand, Consumer, or any cross-child behavior.

## Implementation Guardrails and Checks

The implementation allowed by this record is exactly plan items 1--3.  The check must make the following facts explicit:

1. A one-string valid source proposal compiles to `((member_1, policy), ..., (member_n, policy))` in frozen group order; the compiled payload remains the existing list of `{tool_index, policy}` objects and its digest matches the existing formula.
2. Array, blank, and overlength source values fail at `$.error_policy` as a `string` contract error.  The existing one-correction/two-call ceiling stays unchanged; a second invalid result commits no SharedTool output and permits no third call.
3. The model-visible SharedTool shape no longer asks it to echo a policy once per member, while the frozen indexes remain visible for the three true partition dimensions.  Node ID, ports, edges, owner, Direct route, no-Skill invariant, and correction topology remain unchanged.
4. A two-member or larger compiled group still gives every ToolDraft the same selected shared-contract digest, while independently authored local `errors[]` can differ per tool.  Modeling Gate accepts the unchanged typed contract closure.
5. Existing package/Registry cold-read coverage continues to accept the unchanged compiled representation and to reject a mutation of its policy list/digest.  Preserve the existing hand-constructed distinct-pair compiled fixture; do not turn this source-only change into a global equal-values invariant.
6. Run the named focused SharedTool/Design and package/Registry tests, then the plan's full pytest, firewall, Ruff, mypy, compileall, diff, and production-line-ceiling checks.  These are deterministic regressions, not real-node proof.

## Smallest True-Boundary Proof

After implementation and its independent check, run only the same immutable-parent suffix:

1. Reuse the exact frozen Architecture and Evidence Artifact bytes/refs already demonstrated by the diagnosis: `design.world_architecture:8b0f1bcda8f37a24` and `design.evidence_graph:8cea941a9168ce53`, matching parent `run_1bec958e41ae4207beb4a7b40149f9c0`.  Prove digest/ref equality; do not rerun, rewrite, adopt, or broaden Research or WorldArchitecture.
2. Invoke only real Luna `shared_tool_semantics[1-2-3-4-5-6-7]` against that immutable input.  It may use its existing one local correction (at most two calls), then must commit the compiled SharedTool Artifact with all seven framework-bound pairs and a new SharedTool semantic revision.
3. Invoke only the first downstream shard, `tool_semantics[register_member]`, against that committed contract, and stop after it commits.  Do not continue WorldRules, Curriculum, TaskRequirement, Candidate, Judge, Package, Registry, Repair, Expand, or Consumer.
4. Read safe Observe for the diagnostic run.  Its permitted evidence is the exact suffix Work/Artifact/Finding facts and `not_published`; it is non-resumable, non-adoptable, and non-publishable diagnostic evidence.  Any new failed scene begins a new diagnosis rather than a retry or prompt escalation.

## Non-Claims

- This does not prove that every Luna response will supply valid group semantics.
- This does not prove complete Design, Candidate, Integration, Judge, Package, Registry, public Direct E2E, Repair, Expand, or Consumer/SFT/RL.
- It does not authorize a model switch, response-format change, parser change, fallback/retry change, group split, relaxed validator, or new source compatibility path.
- It does not make the safe Observe status of the diagnostic suffix (`running` with failed/passed suffix Work facts as applicable) into a normal Direct completion or release claim.

## Next Permitted Gate

Implementation of this exact digest is permitted, limited to the Direct source/compiler/card/test scope stated in the plan and guardrails above.  The next execution gates are: independent implementation check, the immutable-parent SharedTool-plus-one-ToolSemantics suffix proof, then one fresh public Direct E2E only if that suffix passes.  A changed digest, changed boundary, or new real scene expires this allow.

## Files Found

- `research/shared-tool-policy-binding-plan.md` — reviewed plan; exact SHA-256 verified.
- `research/diagnosis-shared-tool-policy-coordinate-echo.md` — persisted real-scene diagnosis and bounded proof target.
- `docs/agent-world-environment-generation.zh.md` — canonical Direct shared-policy and framework/semantic-authority rules (§601/603).
- `docs/direct-rewrite-execution-map.zh.md` — Direct node ownership plus downstream Design/Candidate/Registry/Observe map.
- `agent_world/design.py` — SharedTool producer/compiler, ToolSemantics consumer, and semantic-revision input.
- `agent_world/contracts.py` — compiled SharedTool and Design contract ABI.
- `agent_world/candidate.py` — Candidate projection, Rule IR packaging, and Registry cold-read digest check.
- `agent_world/graph.py` and `agent_world/observe.py` — immutable Work semantic identity and safe observability boundary.
- `config/.agent-world-runs/runs/run_bb6693c8de48462b992686c4272f0439/` — latest safe Observe/attempt/Work/Finding evidence.

## External References

None needed; the canonical project contract and persisted local evidence are sufficient.

## Related Specs

- `.trellis/spec/guides/foundry-product-alignment.md`
- `.trellis/spec/guides/agent-llm-node-debugging.md`
- `.trellis/spec/agent_world/backend/index.md`

## Caveats / Not Found

- This is an independent, read-only development gate; it neither modifies the plan nor production/test files.
- The source contract card currently still describes the old array form (`node-contracts.md:352-375`); the plan's narrow alignment is required before the source change can be considered coherent.
- No full Direct E2E or downstream live proof was run in this review.  The latest evidence is a deliberately partial diagnostic suffix, so it cannot prove product completion.
