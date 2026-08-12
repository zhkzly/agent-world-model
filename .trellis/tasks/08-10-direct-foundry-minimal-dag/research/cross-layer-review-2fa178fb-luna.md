# Research: cross-layer review — 2fa178fb Luna selection

- Query: Fresh independent read-only cross-layer critique of the Spark semantic-rejection diagnosis and Luna-primary Direct-route plan.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest (SHA-256): `2fa178fb5725aaad7b09806cbea1066a809617a1ed13b3847dcd667a459950d5`, independently recomputed from the complete `research/direct-live-luna-selection-plan.md`; it matches the required digest.
- Plan revision: current unlabelled Luna-selection plan following Diagnosis Record `diagnosis-direct-proof-3-spark-contract.md`.
- Revision count: 0 for this new diagnosis/plan lineage; the prior route and usage reviews are completed predecessor lineages, not revisions of this plan.
- Scope classification: coordinated checked-in Direct-route selection/configuration change. It changes the model the existing Direct node invokes, while retaining the existing route schema, adapter, graph contracts, correction and transport-retry policy, and all later handoffs.

## Product target, trigger, and attribution

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, atomically publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The relevant real scene is `run_9b004e18777140cc8cdfded98a6933cc`. The Diagnosis Record and PAC-31 establish the bounded chronology: the fresh Spark `world_architecture` node used the same frozen need/evidence/node; attempt 1 parsed but violated the closed kebab-name condition at `$.name`; framework supplied its one safe local correction; attempt 2 parsed but failed `world_architecture_tool_invalid`; then framework committed a failed Designer WorkRecord/Finding with two canonical `assurance.operation` refs, exact request/evidence dependencies, no output, `status=rejected`, and `release=not_published`.

This supports attribution to Spark's compatibility with this unchanged Direct semantic transaction, not an assertion that the Prompt or contract is universally defect-free. The Direct projection/no-Skill/no-tool/no-workspace boundary, operation-evidence persistence, compiler rejection, route-free Finding, C8 provenance, and release block all ran and produced the expected safe facts. There is no retained raw response that would support speculative Prompt or tool-contract tuning, and the two allowed attempts already exercised the authorized local-correction mechanism. Luna's fresh proof is therefore the appropriate falsifier: a Luna semantic rejection must become a new Observe scene and new diagnosis, not permission to adjust Prompt, schema, normalization, or budgets.

## Authorization, impact chain, owners, and compatibility

Authorization is adequate for this narrow model-selection action. The prior live-route R1 record says the user explicitly selected Spark primary and Luna fallback after the same credential-safe localhost control returned HTTP 200 for both models; PAC-31 records the user's conditional selection for the observed Spark non-convergence. The plan changes only that already-authorized ordering, retaining `OPENAI_API_KEY` and the proven localhost chat-completions route. It neither requests a new provider/product, grants a new capability, nor changes the separate Agent route.

```text
checked-in Direct primary/fallback literals
  -> load_settings / immutable ChatRoute
  -> unchanged DirectChatBackend primary call and typed-retryable-only fallback
  -> Direct `world_architecture` proposal
  -> unchanged Designer parser/compiler/correction transaction
  -> WorkRecord + assurance.operation provenance
  -> unchanged Candidate telemetry / Package / Registry / Observe consumers
```

- `ChatRoute` remains the three-field immutable configuration contract and settings project the two Direct routes without semantic reinterpretation (`agent_world/config.py:16-20`, `72-79`, `116-128`).
- `DirectChatBackend` will call Luna first and only call Spark after a typed retryable failure; its condition and call shape remain unchanged (`agent_world/invocation.py:88-101`, `103-160`). A semantic validation rejection is outside that fallback condition, so the proposed swap does not mask Spark's diagnosis with an automatic fallback or add a retry.
- Luna remains a Direct LLM: it receives the existing chat payload only. It is not moved onto the Agent route, receives no Runtime Skill/tool/workspace, and receives no release authority. The execution map keeps those roles distinct (`docs/direct-rewrite-execution-map.zh.md:132-156`; `node-contracts.md:310-347`).
- C8 provenance remains compatible. The runner still persists one `assurance.operation` per successful invocation before compile, retains exact input/dependency refs, and either commits the same closed output envelope/WorkRecord shape or a failed WorkRecord/Finding (`agent_world/graph.py:459-568`, `645-741`). The only new provenance fact on a successful Luna invocation is the truthful existing `model` value, which the telemetry consumer already cold-reads through `OperationEvidence` (`agent_world/candidate.py:1693-1734`). No port, edge, Artifact envelope, Finding, owner, release decision, package lineage, or safe Observe projection changes.
- Future bounded Repair still receives the same immutable route-free WorkRecord/Finding provenance. Expand still receives the unchanged Direct Design and framework-owned `origin=direct`, `parent_package_refs=[]` contract (`agent_world/design.py:1230-1254`). Consumer remains downstream of exact released packages only. These consumers are structurally unchanged, but none is proved by the next single-node invocation.

## Smallest permitted implementation and proof

Implementation is limited to:

1. Swap the two existing **Direct** model literals in `config/agent-world.example.toml` to Luna primary and Spark fallback, preserving the localhost URL and credential handle.
2. Synchronize only the existing Direct route text/table in `docs/direct-rewrite-execution-map.zh.md` and `.trellis/tasks/08-11-foundry-complete-v1/design.md`; leave the Agent route unchanged.
3. Update the existing checked-in example-load assertion in `tests/test_agent_route_config.py` to the exact Luna-then-Spark order.

The smallest deterministic checks are the focused checked-in-example route assertion, existing Direct retry/fallback tests, and the established C8/provenance quality gate. The smallest true-boundary proof is one fresh, unchanged `world_architecture` invocation through the normal public Direct composition root followed by its terminal Observe read. It may establish a passing WorldArchitecture WorkRecord with Luna operation provenance, or honestly establish a new terminal failure. It does not establish CandidateBuild, Runtime/Integration, Judge, Package/Registry publication, Repair, Expand, Consumer, or end-to-end product completion.

## Non-claims and next permitted gate

- This decision does not claim Luna will satisfy the closed output contract; existing evidence proves only localhost transport reachability for Luna.
- It does not authorize Prompt/contract changes, tool or identifier normalization, a correction-budget increase, adapter/retry/fallback-policy changes, provider discovery, profile/capability work, graph/persistence/release changes, stale-run mutation, or any Repair/Expand/Consumer implementation.
- It does not relabel the Spark failure. Spark's attempted local correction remains part of its immutable failed WorkRecord/Finding, and Spark can only reappear as the unchanged typed-retryable fallback on a future Luna transport failure.

Next permitted gate: implement exactly the three listed configuration/documentation/regression updates; then run deterministic checks, one fresh Luna `world_architecture` proof, and Observe. This allow expires if the plan digest, Direct transport/fallback contract, or the next relevant Observe scene changes.

## Files found

- `research/diagnosis-direct-proof-3-spark-contract.md` — persisted Spark chronology, attribution, rejected repairs, and next-proof constraint.
- `research/direct-live-luna-selection-plan.md` — reviewed plan and digest input.
- `research/product-alignment-checkpoints.md` (PAC-31) — observed safe scene, conditional authorization, and explicit non-claims.
- `research/cross-layer-review-e6449739-live-route-r1.md`, `direct-live-route-r1-check.md` — prior credential-safe route authorization/control and unchanged Direct retry semantics.
- `research/cross-layer-review-91640dda-usage-r1.md`, `direct-live-usage-r1-check.md` — canonical operation-evidence closure and prior quality proof.
- `config/agent-world.example.toml`, `agent_world/config.py`, `agent_world/invocation.py`, `agent_world/graph.py`, `agent_world/candidate.py`, `agent_world/design.py`, and `tests/test_agent_route_config.py` — current route, consumer, provenance, lineage, and regression facts.

## Caveats / Not Found

- The persisted diagnosis/PAC describe the Observe facts for `run_9b004e18777140cc8cdfded98a6933cc`; no cold-readable local run directory was present in this worktree. This review relies on that durable diagnostic record and does not invent raw model output or a new Observe fact.
- No implementation, provider call, retry, proof run, task-context JSONL read, git operation, or production/spec edit was performed.
