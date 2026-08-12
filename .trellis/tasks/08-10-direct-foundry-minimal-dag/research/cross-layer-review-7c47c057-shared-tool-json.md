# Research: cross-layer review — shared-tool JSON contract

- Query: Independently review `shared-tool-json-contract-plan.md` at SHA-256 `7c47c0571028a26a0d59a5c346331852592f8a81e6b3944b64513bbfc84b35ce` after Direct E2E `run_4528cf8a411a4d8a82b6390465c6d138`.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `7c47c0571028a26a0d59a5c346331852592f8a81e6b3944b64513bbfc84b35ce`
- Plan revision: `shared-tool-json-contract`, revision `1/2`
- Scope classification: coordinated Direct recipient-contract and Direct output-format/correction boundary; immediate SharedTool consumer chain only.
- Trigger: failed real Direct E2E. Research, WorldArchitecture, and the frozen six-member group passed; `shared_tool_semantics[1-2-3-4-5-6]` stopped at `direct_response_not_json`, produced no SharedTool Artifact, and left Registry `not_published`.
- Affected trust boundary: Direct LLM rendered recipient contract -> Direct parser -> framework-owned local-correction transaction -> validated SharedTool Artifact -> ToolSemantics/Modeling -> package/Registry.

## Product Target

The target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe.

This plan can advance only the Architecture-to-SharedToolSemantics handoff. It does not prove ToolSemantics, Modeling, Candidate, Judge, Package, Registry, Repair, Expand, or Consumer completion.

## Findings

### 1. The incomplete SharedTool recipient shape is a causal, actionable defect

The current recipient sees only the seven field names at `agent_world/design.py:1369-1373`, while the compiler requires an exact seven-key object, exact ordered group echo, bounded domain arrays, frozen-member coverage, bounded text, and an ordered one-policy-per-member array at `agent_world/design.py:1245-1361`. The existing task contract instead describes an obsolete `ordered_tool_indexes/domains` draft at `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:357-380`.

The proposed grammar accurately exposes the current compiler's material requirements:

- exact group echo (`design.py:1258-1273`);
- 1..group-size domain arrays with members limited to and covering the group (`design.py:1275-1303`);
- exactly group-size, ordered error-policy objects (`design.py:1305-1332`);
- 0..8 bounded ordering/compensation texts (`design.py:1339-1358`).

It appropriately does **not** claim stricter disjointness/uniqueness than the current compiler proves: the compiler tests set coverage, not duplicate occurrences within a domain. The framework remains the sole compiler and digest owner. Updating the SharedTool shape and its stale node-contract prose is therefore a minimal, justified recipient-contract repair.

### 2. The proposed non-JSON mapping is bounded in mechanism, but not allowed or observable enough as written

`_json_object` classifies a completed non-object/non-JSON content response as rejected `direct_response_not_json` (`agent_world/invocation.py:49-58`). `_direct_json` currently maps every `InvocationError` into an explicitly non-correctable `DesignError` (`agent_world/design.py:543-569`). If it instead emitted the proposed safe packet, `GraphRunner` would create a `correction_requested` attempt and permit only ordinal one to receive a correction; ordinal two cannot receive a third call (`agent_world/graph.py:487-515`, `671-680`). Thus the proposed second call would not be an unbounded hidden retry at the graph-control level.

It is nevertheless blocked for two concrete reasons:

1. The source-of-truth explicitly treats generic root schema errors as framework/output-contract defects rather than correction-consuming semantic failures (`docs/agent-world-environment-generation.zh.md:421-432`). The binding task contract is even more explicit: provider, transport, and JSON-parsing failures never enter local correction (`node-contracts.md:144-148`). The plan changes that policy for every Direct node but only proposes to update the SharedTool section; it neither reconciles nor revises the common Direct boundary.
2. The first failed physical call would remain under-observed. `DirectChatBackend` calculates usage before `_json_object` raises, but no `InvocationResult` is returned (`invocation.py:146-162`). `GraphRunner` persists `OperationEvidence` only after `operation(...)` returns (`graph.py:487-492`); its error attempt stores only a code and correction (`graph.py:496-510`). Mapping to `<node>_invalid` would also erase the original `direct_response_not_json` classification from that attempt. The plan's claimed inspection of first-attempt model and usage therefore cannot be satisfied without a safe provenance path. Raw content need not and must not be persisted.

### 3. Generic Direct impact is real and is not fully covered by the proposed tests

Every Direct semantic node routes through `_direct_commit` and the one `_direct_json` adapter (`agent_world/design.py:581-624`): `world_architecture`, `shared_tool_semantics`, `tool_semantics`, `world_rules`, `curriculum_plan`, and `task_requirement` (`agent_world/graph.py:151-210`). No Agent or candidate path calls that helper.

The plan correctly calls this a generic Direct proposal change, but its stated deterministic tests prove the behavior only at SharedTool. It needs explicit compatibility evidence for the shared helper and the exact six-node Direct set, including that Agent/candidate nodes remain untouched. It must also prove `direct_response_empty`, malformed provider envelopes, transport/HTTP terminals, and existing retryable fallback behavior do not acquire a correction packet.

### 4. Immediate and later consumers remain compatible only if the compiled contract stays byte-for-byte unchanged

The plan rightly leaves `SharedToolContract`, group identity, compiler, Artifact kind, and graph ports unchanged. On a valid proposal, the existing compiled contract remains the immediate input to every ToolSemantics shard and is verified against the coupling plan in `DesignContract` (`agent_world/contracts.py:960-1015`). Candidate, package, and Registry preserve and revalidate the same representation (`agent_world/candidate.py:304-307`, `750-763`, `2085-2100`, `2536-2564`). The plan's valid-payload and downstream-ToolSemantics tests are necessary; the full regression suite is the appropriate later check for the package/Registry representation.

No SharedTool Artifact is produced on the failed first proposal today, so no downstream ToolSemantics, Modeling, Package, or Registry consumer can consume partial semantics. That fail-closed behavior must remain true after a second invalid response.

### 5. Exclusions

- **All-tools grouping / split group:** correctly excluded. The current Architecture compiler intentionally derives one all-tool group whenever there is more than one tool (`agent_world/design.py:1190-1198`; `agent_world/contracts.py:679-681`). Splitting it changes topology and downstream closure without evidence from a parse failure.
- **`max_tokens`, model switch, and compiler changes:** correctly excluded by this evidence. The diagnosis has no truncated content, model-competence, or parsed-compiler failure fact. `direct_response_not_json` is non-retryable at the adapter, so primary-to-fallback does not currently run (`agent_world/invocation.py:97-103`).
- **Broader parser scraping:** correctly excluded. Existing code-fence normalization is already narrow (`invocation.py:49-58`); accepting arbitrary prose would weaken the framework-owned boundary and is unsupported by the scene.
- **`response_format`: not discharged as an exclusion.** The actual Direct request has no native response-format/schema field (`invocation.py:113-123`), while the applicable backend guidance requires native strict JSON Schema and a profile-matched probe before classifying provider limits (`.trellis/spec/agent_world/backend/index.md:1813-1853`). This record does **not** authorize a response-format change, but the plan cannot assert it is non-causal without reconciling that contract through a bounded true-boundary request-shape/probe fact.

### 6. Owners and role boundaries

The shape-only portion preserves the intended separation: framework owns group derivation, JSON grammar, validation, digest, attempts, gates, Artifacts, and release; Direct owns only shared business semantics; Agent retains only Skill/tool work; candidate remains untrusted. The proposed correction packet contains only safe format facts and grants no route, budget, Artifact, Finding, Judge, or release authority.

That ownership is insufficient to allow the plan because current authority policy classifies parser-level failure as terminal. A policy change must be explicit, safely observable, and consistent across all Direct nodes before it can use the existing correction mechanism.

## Required Plan Revision Feedback

1. Choose the smallest coherent policy rather than silently reclassifying a parser failure:
   - the minimal route is to keep `direct_response_not_json` terminal and implement only the complete SharedTool grammar/document correction; or
   - if a non-JSON completion is to become a correction-eligible Direct format failure, revise the common Direct contract (and reconcile the source-of-truth root-error rule) before implementation. Do not update only the SharedTool node prose.
2. For the second route, preserve safe first-attempt facts through the failed adapter boundary: the original closed failure category, resolved model/route identity, and provider usage or explicit unknown. Persist no raw provider content, prompt, credentials, or control-plane fields.
3. Add a focused generic-Direct regression: assert the one common adapter is used by the six Direct nodes, a first eligible format failure receives exactly one safe packet, a valid second proposal commits, and a second invalid proposal leaves no output Artifact, a failed WorkRecord, one blocking Finding, and no third call. Separately assert empty/envelope/transport/retryable-fallback behavior remains non-semantic.
4. Do not declare native response transport irrelevant. Add a profile-matched, safe request-shape/probe fact or explicitly leave it as an unresolved competing hypothesis and keep the parser failure terminal in this lineage. Do not add `response_format`, change models, alter token limits, split the group, or weaken/scrape the parser under this plan.
5. Retain the plan's valid-current-payload, semantic-identity, immediate ToolSemantics, and fresh same-artifact real-node proof requirements. The changed SharedTool output shape must rotate its semantic revision while node/edge/route/group topology remains fixed.

## Smallest Allowed Proof Plan After Revision

1. Deterministic compiler/prompt regression for the exact SharedTool grammar and unchanged valid payload.
2. Deterministic generic Direct correction/provenance regression, only if the revised contract authorizes it; otherwise assert terminal parser behavior.
3. Focused real `shared_tool_semantics[1-2-3-4-5-6]` proof with the exact committed Architecture/Evidence Artifacts, inspecting safe attempts, model/usage provenance, Artifact/WorkRecord, and Observe.
4. Only after that passes, one fresh public Direct request to terminal Observe. Any new terminal begins a new Diagnosis Record.

## Non-Claims

- This review does not prove a prompt-only grammar will make Luna return JSON.
- It does not approve a `response_format`, token, timeout, model, fallback, parser, group-topology, or compiler change.
- It does not prove later Design, Candidate, Judge, Package, Registry, Expand, or Consumer closure.
- It does not expose or retain raw provider output; the diagnosis intentionally lacks it.

## Next Permitted Gate

Revise the written plan only, addressing the five items above, then submit the new plan digest for a fresh independent cross-layer review. Do not dispatch implementation or retry the failed Direct node under this blocked revision.

## Files Found

- `shared-tool-json-contract-plan.md` — reviewed plan, revision 1/2, hash verified.
- `diagnosis-e2e-shared-tool-json-boundary.md` — persisted real-scene chronology and causal hypothesis.
- `agent_world/design.py` — Direct projection, SharedTool compiler, and common Direct adapter.
- `agent_world/invocation.py` — Direct chat request, JSON parsing, failure taxonomy, and fallback behavior.
- `agent_world/graph.py` — bounded two-attempt transaction and persisted attempt/evidence behavior.
- `agent_world/contracts.py` — SharedTool and Design consumer invariants.
- `agent_world/candidate.py` — candidate/package/Registry consumers of the unchanged SharedTool representation.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — stale SharedTool draft and conflicting common JSON-parsing correction rule.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:421-445,600-635` — source-of-truth rules for root output errors, Direct semantic ownership, bounded correction, observability, and downstream closure.
- `.trellis/spec/agent_world/backend/index.md:593-706,1466-1513,1813-1890` — Direct prompt-only boundary, SharedTool completion, and native structured-output guidance.
- `docs/direct-rewrite-execution-map.zh.md` — Direct/Agent/framework/candidate role separation.

## External References

None. This review is based on the supplied real-scene diagnosis and the target repository's current contracts and code.

## Caveats / Not Found

The raw provider response is intentionally not persisted, so its length and text cannot distinguish truncation from other non-JSON content. No new live call was made during this read-only review.
