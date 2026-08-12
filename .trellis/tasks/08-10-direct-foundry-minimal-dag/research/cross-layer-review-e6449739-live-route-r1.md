# Cross-layer review: e6449739 live route R1

- Query: Independent read-only review of repair-plan revision R1 for the failed first Direct `world_architecture` proof.
- Scope: mixed (persisted live evidence, configuration/adapter consumer path, C8 provenance, and parent-child contract seams)
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest (SHA-256): `e6449739e5214ec150bbac3f0776493154abb9dedacae3e324f41696738677c0` (independently recomputed from the complete current plan; matches).
- Plan revision: R1, `direct-live-route-repair-plan.md`.
- Revision count: 1 for the diagnosis/plan lineage; this addresses the retained revision-0 `block`.
- Scope classification: coordinated configuration-to-Direct-invocation boundary change. It changes the checked-in default consumed by the real Direct node, but preserves the existing route contract, all graph contracts, and all later handoffs.

## Product target and trigger

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The observed proof `run_f661a25e29be4764a6bcacc0c778c9a4` stopped at the Direct provider boundary before any model output: HTTP 403, a committed failed WorkRecord, no outputs, and `release=not_published`. The persisted Diagnosis Record limits the cause to provider/configuration; Direct prompt/input assembly, Direct's no-Skill/no-tool/no-workspace invariant, compiler, candidate, Judge, Registry, and later consumers were not reached.

The predecessor correctly blocked an unsupported claim that `/zen/go` was malformed. R1 closes that causal gap: identical credential-safe controls returned HTTP 403 for both official OpenCode Go and Zen endpoints, while the same safe localhost chat-completions control returned HTTP 200 for `gpt-5.3-codex-spark` and `gpt-5.6-luna`. The user explicitly selected Spark primary and Luna fallback, both with `OPENAI_API_KEY`. This is a supported default-selection decision, not an inference about OpenCode entitlement or endpoint validity.

## Plan revision and impact chain

R1 makes exactly four linked actions:

1. Change only the existing Direct primary/fallback literals in `config/agent-world.example.toml` to Spark then Luna at `http://localhost:8317/v1/chat/completions`, both with `OPENAI_API_KEY`.
2. Synchronize the two existing route descriptions in `docs/direct-rewrite-execution-map.zh.md` and the complete-v1 parent design.
3. Add one example-load regression assertion in `tests/test_agent_route_config.py`.
4. Run deterministic checks, then rerun the frozen `world_architecture` proof and read its terminal Observe scene.

Impact chain:

```text
example Direct route literals
  -> load_settings / immutable ChatRoute
  -> existing DirectChatBackend request and unchanged retryable-only fallback rule
  -> world_architecture Direct LLM proposal
  -> existing Designer validation and WorkRecord
  -> unchanged Design -> Candidate -> Integration -> Judge -> Package -> Registry -> Observe chain
```

`load_settings` continues to accept only the three `ChatRoute` fields and projects the two Direct routes unchanged (`agent_world/config.py:72-79`, `116-128`). The selected base URL already ends in `/chat/completions`, so the existing adapter sends it as-is (`agent_world/invocation.py:62-67`). `DirectChatBackend` still invokes fallback only after a typed retryable failure (`agent_world/invocation.py:88-101`); R1 neither widens retryability nor changes fallback order/authority.

## Owners, consumer compatibility, and preserved seams

- `ChatRoute`/settings loading and `DirectChatBackend` remain the only transport owners. The plan adds no provider discovery, adapter path, profile, permission/capability system, retry policy, or public composition root.
- The Designer remains the owner of the prompt-only Direct semantic node. Spark and Luna remain Direct LLM routes; neither is promoted to the Codex Agent route, given a Runtime Skill, tools, workspace, or release authority.
- C8 provenance is unaffected: the plan does not alter `ArtifactEnvelope.output_ports`, `NodeSpec`/`EdgeSpec`, graph runner bindings, WorkRecord inputs, dossier/telemetry/package refs, Registry cold-read, or the five component owners. The C8 closure remains the relevant unchanged compatibility fact.
- Bounded Repair's future consumers still receive the same immutable WorkRecord/Finding provenance; R1 creates neither a Finding schema change nor a route/control field.
- Expand's future CandidateGraph and lineage/package-use seams remain unchanged because Direct still supplies the same origin-neutral compiled Design and its Direct package continues to use framework-owned `origin=direct` with empty parent refs.
- Consumer/SFT/RL remains unchanged: it consumes exact released package/receipt and package DifficultySchema seams only, none of which is modified by a pre-Design route literal.

No unproved later consumer is being claimed compatible by execution evidence: only structural compatibility follows from the absence of a contract change. CandidateBuild, Integration, Judge, Package, Registry, Repair, Expand, and Consumer remain unexecuted in this live lineage.

## Smallest permitted implementation and proof

Implementation is limited to the three named documentation/configuration files and the one focused regression in the existing route-config test module. The regression must load the checked-in example and assert both exact Direct `ChatRoute` values, including the shared localhost chat-completions endpoint and `OPENAI_API_KEY`; it must not test network reachability or alter fallback behavior.

After the focused regression and the existing deterministic C8 quality gate pass, run the same frozen `world_architecture` proof using the updated primary route. Read Observe at its terminal state. A new route/model/response failure is a new scene: stop, read Observe, and begin a new diagnosis rather than modifying prompt, schema, Skill, compiler, retry, or route logic.

## Deterministic checks, true-boundary proof, and non-claims

- Deterministic checks: the focused checked-in-example load assertion, existing route validation tests, and the existing C8 deterministic quality gate.
- True-boundary proof: the unchanged real Direct `world_architecture` invocation through the selected Spark primary, followed by its safe Observe scene. The preceding localhost HTTP-200 controls establish request reachability only; they do not prove a valid structured semantic proposal.
- Non-claims: this allow does not prove a Direct model output, a Codex Agent Skill surface, live research, CandidateBuild, isolated Runtime/Integration, independent Judge, Package/Registry release, Observe release projection, repair, Expand, Consumer/SFT/RL, or an end-to-end `EnvironmentPackage`.

## External references and caveats

- [OpenCode Zen endpoints](https://opencode.ai/docs/zen) and [OpenCode Go endpoints](https://opencode.ai/docs/go/) remain relevant only to the predecessor correction: both official paths are valid products, so neither is retained or probed as R1's fallback.
- The HTTP terminal facts are credential-safe evidence recorded in `diagnosis-direct-proof-1-opencode-route.md`; this review did not rerun requests or inspect credential values.
- `config/agent-world.example.toml:4-12` is the sole current checked-in Direct default. `tests/test_agent_route_config.py` currently covers strict agent-route loading and is the intended minimal location for the new checked-in Direct-example assertion.

## Next permitted gate

Implement exactly R1, then conduct the prescribed deterministic check and real frozen-node proof. This allow expires if the plan digest, selected Direct route contract, or the next relevant Observe scene changes.
