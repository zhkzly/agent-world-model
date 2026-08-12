# Research: cross-layer review — declared second Direct format Feedback

- Query: Independently review plan revision 2 for digest `85541065b75f17ec5509bb7cc7be2d61173365a7a58c414122f765e3345483a8`: honor a declared second local Direct correction after a format-first rejection without weakening parsing, secrecy, framework ownership, or downstream contracts.
- Scope: internal; coordinated cross-node control boundary limited to the two predeclared Direct nodes with `local_corrections=2` and their shared `GraphRunner` transaction.
- Date: 2026-08-12
- Decision: allow
- Plan digest: `sha256:85541065b75f17ec5509bb7cc7be2d61173365a7a58c414122f765e3345483a8`
- Plan revision / count: revision 2/2; count 2 as supplied by the dispatch. This allow expires if this digest, the affected correction boundary, or the relevant real scene changes.

## Decision and product target

**Decision: allow.** The plan is the smallest coherent repair for a framework-owned admission mismatch: a Direct node explicitly declared with two local corrections is stopped after one format Feedback even though the declared loop permits three proposals. It advances, but does not complete, the product target:

`EnvironmentRequest -> evidence-grounded Design -> executable Candidate -> independent Judge -> Registry-released immutable EnvironmentPackage -> safe Observe`.

The repair may let the blocked `tool_semantics[manage_maintenance]` Design shard commit; it does not make a Candidate, Judge verdict, Registry package, Direct E2E, Repair, Expand, or Consumer claim.

## Trigger, diagnosis, and safe Observe evidence

- Trigger: real public Direct terminal `run_6df6b3046ae64983847f44621ac81a1c`, coordinate `design/tool_semantics[manage_maintenance]`.
- Diagnosis: proposal 1 and its actionable same-conversation format Feedback completed; proposal 2 was again safely classified as `outer_content`; the framework then denied the remaining declared correction solely because both packets had `direct_response_not_json` ([diagnosis](diagnosis-direct-repeated-outer-content-budget.md):29-47, 70-80).
- Safe Observe evidence: persisted PAC-195 records two Direct operation/attempt refs, terminal `direct_response_not_json`, one blocking Finding, and `release=not_published`; it also records that no failed-shard semantic Artifact committed and no legacy authority participated ([product-alignment-checkpoints.md](product-alignment-checkpoints.md):4120-4142).
- The original live state root is not present inside this allowed cleanroom, so this review relies on the persisted safe scene and Diagnosis Record. That is sufficient for this plan gate, but not a substitute for the required post-change Observe read.

## Affected trust boundary and impact chain

The affected boundary is the framework's local Direct correction admission between a rejected proposal and the next same-contract user Feedback turn:

`DirectChatBackend strict result -> DesignExecutor._direct_commit ephemeral prior answer -> GraphRunner eligibility -> same Direct node -> compiler/Artifact commit or failed WorkRecord/Finding -> CandidateGraph/Judge/Registry/Observe`.

- **Producer unchanged:** `DirectChatBackend` still requests `response_format={"type":"json_object"}` and uses strict unwrapped-object parsing ([agent_world/invocation.py](../../../../agent_world/invocation.py):100-124, 204-227).
- **Changed handoff:** only `GraphRunner._eligible_local_correction` may admit ordinal two after a prior format packet. The bounded loop itself already permits only ordinals 1..3 for a node declaring two corrections ([agent_world/graph.py](../../../../agent_world/graph.py):494-569, 684-723).
- **Immediate consumer unchanged:** `DesignExecutor._direct_json` resends the frozen system/user contract plus exactly one prior assistant turn and framework-authored Feedback; `_direct_commit` replaces its in-memory prior value with the immediately preceding result ([agent_world/design.py](../../../../agent_world/design.py):597-630, 648-697).
- **Downstream compatibility:** Artifact envelopes are created only after a complete successful compile; a terminal still creates the same safe failure evidence, WorkRecord, and route-free Finding ([agent_world/graph.py](../../../../agent_world/graph.py):528-607). `WorkRecord.assurance_refs` is an unbounded tuple, so one additional attempt/evidence ref does not alter its schema ([agent_world/contracts.py](../../../../agent_world/contracts.py):194-223). Candidate, Judge, Registry, and Observe therefore consume no new semantic field, route, or authority.
- **Observe compatibility:** Observe projects safe WorkRecord/Finding facts and returns `not_published` absent a verified release; it never reads a prompt or raw Direct response ([agent_world/observe.py](../../../../agent_world/observe.py):498-538).

## Owners and authority compatibility

Framework code remains the sole owner of correction admission, invocation count, validation, Artifact commit, Finding, and release. The Direct LLM still proposes only one complete replacement; it gains no owner, budget, route, Gate, Judge, or release field. The strict `CorrectionPacket` remains the only persisted correction data (`code`, exact path, violated condition, expected category), with no raw response ([node-contracts.md](node-contracts.md):125-152).

This is a coordinated shared-runner change, not a new retry system:

- `tool_semantics` and `curriculum_plan` are the only current Direct nodes declared with two local corrections ([agent_world/graph.py](../../../../agent_world/graph.py):175-208).
- Default Direct and Agent nodes retain one correction/two total proposals; `NodeSpec` continues to reject `local_corrections=2` for Agent nodes ([agent_world/graph.py](../../../../agent_world/graph.py):49-75).
- Provider/transport retry, fallback, model/route/configuration, graph topology, input projections, output contracts, and cross-node Repair remain unchanged.

The later user clarification is satisfied without broadening this lineage: stochastic model work receives actionable bounded Feedback, while an explicitly two-correction Direct node may have three total proposals. It does not authorize an Agent-wide third call or a generic retry platform.

## State-machine pressure test

The allowed implementation must retain all existing eligibility guards and change only the ordinal-two transition table below. “Semantic” means a parsed, correctable compiler/validator rejection carrying the existing safe, precisely located packet.

| Prior -> current rejection | Required framework result |
| --- | --- |
| format -> format | Admit the second and final Feedback; make proposal 3. A third format failure is terminal. |
| format -> parsed semantic | Admit the second and final Feedback carrying the semantic packet; proposal 3 may commit normally. |
| semantic -> format | Terminal after proposal 2. A format regression is not semantic strict progress and must not unlock proposal 3. |
| any rejection at proposal 3 | Terminal; ordinal three cannot satisfy the ordinal-two eligibility rule, so no fourth invocation occurs. |
| default one-correction node | Unchanged: at most one Feedback and two total proposals. |

The existing strict semantic A-to-B rule stays intact for semantic-first paths. The format-first exception is narrow: it depends on the already-declared two-correction Direct policy, a completed/nonempty/`stop` Direct response that fails only strict object parsing, the existing safe packet, and the same frozen transaction. It must not convert provider, transport, framework, candidate, Integration, Judge, Package, Registry, or missing-packet failures into corrections.

## Smallest allowed implementation

1. Update all normative wording that currently contradicts the declared policy: the source-of-truth exception at [docs/agent-world-environment-generation.zh.md](../../../../docs/agent-world-environment-generation.zh.md):421-429; the Direct task feedback contract at [node-contracts.md](node-contracts.md):125-152; the task feedback rule at [design.md](../design.md):286-300; and the concise debugging-guide clarification at [.trellis/spec/guides/agent-llm-node-debugging.md](../../../spec/guides/agent-llm-node-debugging.md):39-50. The wording must state the explicit format-first two-correction exception and preserve the semantic-first-format terminal rule.
2. Change only the format-first ordinal-two branch of `GraphRunner._eligible_local_correction`; retain the existing loop bound, `semantic_rejection` guard, Direct-only/local-corrections-equals-two guard, and semantic-first strict-progress comparison.
3. Update the focused tests for **both** existing two-correction Direct declarations (`tool_semantics` and `curriculum_plan`), plus the existing one-correction shared/default coverage. This is application of the plan's declared policy to all already affected consumers, not a new node/configuration surface.
4. Update the spec guide through the required spec-update workflow; this critic does not authorize unrelated `.trellis/spec/` changes.

Forbidden shortcuts: parser extraction/weakening, raw-output persistence, response-mode/model/route changes, a scheduler or generic retry abstraction, new Node/Edge/configuration/projection fields, ToolSemantics splitting, cross-node Repair, or any Candidate/Judge/Registry behavior change.

## Smallest tests and proof

Deterministic checks must prove all of the following, preserving the existing semantic-progress regressions:

- `format -> format -> valid` reaches a third proposal and commits.
- `format -> parsed semantic -> valid` reaches a third proposal and commits with the semantic Feedback packet.
- `semantic -> format` stops after two proposals.
- `format -> format -> format` records terminal failure after proposal 3 and issues no fourth call.
- Third successful/failed calls retain the original frozen system/user contract, use only the immediately preceding ephemeral assistant answer, and use the existing concrete format replacement/deletion action or safe semantic action as appropriate.
- Rejected raw content is absent from ArtifactStore, WorkRecord, Finding, Observe, and Feedback; strict parsing and `response_format=json_object` are unchanged.
- Existing same-semantic-issue/no-progress, provider/transport terminal, and default one-correction tests remain unchanged in meaning.

Run focused GraphRunner and Direct-feedback tests first, then full serial pytest, Ruff format/check, mypy, compileall, the legacy firewall, and an independent whole-scope implementation check. Existing focused tests already establish the relevant runner ceiling and Direct Feedback framing ([tests/test_graph_contracts.py](../../../../tests/test_graph_contracts.py):783-1180; [tests/test_design_semantics.py](../../../../tests/test_design_semantics.py):417-469, 615-813, 1174-1310); they must be revised rather than bypassed.

The true-boundary proof is exactly the immutable-parent Luna replay of `tool_semantics[manage_maintenance]` from `run_6df6b3046ae64983847f44621ac81a1c`. Read Observe immediately afterward. It may either commit within at most three proposals or terminate honestly after exactly three. Only a committed shard permits a fresh public Direct E2E; a third terminal starts a new Observe-led Diagnosis Record and does not authorize another call.

## Files found and related specifications

- `AGENTS.md` — source-of-truth precedence, real-failure gate, authority, and Product Alignment requirements.
- `docs/agent-world-environment-generation.zh.md` — canonical bounded-correction, Direct, release, and secrecy requirements; its one-format wording is the stale conflict.
- `docs/direct-rewrite-execution-map.zh.md` — Direct LLM/framework/candidate authority separation and the fixed two-graph scope.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — next-user Feedback, ephemeral previous assistant turn, and proof discipline.
- `.trellis/spec/guides/foundry-product-alignment.md` — partial-proof and downstream non-claim requirements.
- `agent_world/graph.py` — current declaration/loop/eligibility implementation.
- `agent_world/design.py` and `agent_world/invocation.py` — framework-authored Feedback, in-memory prior-turn handoff, and strict parser/SDK request.
- `tests/test_graph_contracts.py` and `tests/test_design_semantics.py` — existing bounded-correction and raw-secrecy regression seams.
- `research/diagnosis-direct-repeated-outer-content-budget.md` and `research/product-alignment-checkpoints.md` — the causal Diagnosis Record and safe Observe-backed terminal facts.

External references: none consulted. No provider, SDK, model, route, or dependency-version behavior is part of this approval.

## Explicit non-claims

- This allow is not evidence that Luna will produce valid JSON on proposal 3.
- Deterministic tests prove only framework admission/terminal behavior, not a live Direct success.
- A successful exact-parent leaf proves only that leaf; it does not prove the remaining Design suffix, Candidate, Integration, Judge, Registry, E2E, bounded Repair, Expand, or Consumer.
- This does not establish a general format-retry policy for all Direct nodes or Agents, and it does not change release authority.

## Next permitted gate

The main planner may add this exact allow record to both `implement.jsonl` and `check.jsonl`, then dispatch bounded implementation only. After implementation: independent check -> exact-parent real replay -> immediate Observe. Any changed digest, broadened retry/authority surface, new live terminal, or attempt to alter parsing/projections/topology invalidates this allow and requires a new Diagnosis/plan/critic gate.

## Caveats / Not Found

- No raw rejected response is included here; preserving that secrecy is a release-blocking invariant.
- No in-scope durable live-state directory for the cited run was present; the persisted safe Observe facts above must be rechecked against a fresh post-change Observe scene.
- No evidence supports projection slimming, a provider/model change, or a generic retry/control-plane redesign; those remain out of scope.
