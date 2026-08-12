# Research: cross-layer review — Direct non-JSON local correction

- Query: Independently review `direct-non-json-local-correction-plan.md` at `sha256:f1cbad9260ad5478d0a8db6431cb64b2986aed3c6396ee92c3471e9d71399559` after the recorded Direct non-JSON terminal.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `sha256:f1cbad9260ad5478d0a8db6431cb64b2986aed3c6396ee92c3471e9d71399559`
- Plan revision: `1/2`
- Scope classification: coordinated common-Direct feedback-policy change, not a local ToolSemantics repair.
- Trigger: the supplied Diagnosis Record for `run_dc28dcded7fe49ce9a2d9a017511831d`, which stopped at `design/tool_semantics[route_tool_to_maintenance]` with `direct_response_not_json`.
- Affected trust boundary: Direct provider completion -> strict parser -> `DesignExecutor._direct_json` classification -> `GraphRunner` correction eligibility -> framework validation/commit -> Design consumers.

## Product Alignment

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This plan can advance only the Direct proposal-format boundary before a Design artifact commits. It cannot prove Design completion, Candidate, Integration, Judge, Package, Registry, Repair, Expand, or Consumer behavior. A corrected node transaction is not an E2E or release claim.

## Evidence and Impact Chain

The persisted diagnosis and Product Alignment Checkpoint support the narrow chronology: the recorded Direct run passed Research, WorldArchitecture, SharedToolSemantics, and seven ToolSemantics shards; its final shard made one call, produced no committed output, and blocked release. The exact frozen-input Luna replay then returned a parsed ToolSemantics object in one call. This supports "not deterministically impossible or too large," but does not itself authorize a change in parser-feedback policy.

The actual chain is:

```text
DirectChatBackend._json_object
  -> InvocationError(direct_response_not_json, rejected)
  -> DesignExecutor._direct_json
  -> DesignError / CorrectionPacket decision
  -> GraphRunner.execute ordinal-1 eligibility
  -> all six Direct semantic nodes
  -> compiler + ArtifactEnvelope + WorkRecord
  -> later Design/Candidate consumers only after a valid commit
```

`_direct_commit` is the common caller for `world_architecture`, `shared_tool_semantics`, `tool_semantics`, `world_rules`, `curriculum_plan`, and `task_requirement`. Thus the proposed one-line classification is mechanically bounded by the existing two-call runner, but it changes the policy of all Direct semantic nodes rather than only the failed tool shard.

## Findings

### 1. Current contracts forbid this correction class

The binding common model contract expressly says that a safe compiler error may receive the one correction packet, while provider, transport, and JSON-parsing failures never enter local correction (`node-contracts.md:125-148`). The focused regression currently asserts exactly that `direct_response_not_json` is terminal after one call, with no output and a blocking Finding (`tests/test_design_semantics.py:843-881`).

The source-of-truth is compatible with that distinction: generic root-schema/no-exact-path mechanical errors are framework/output-contract defects and do not spend model correction; only a shape-correct proposal rejected by the compiler/semantic validator can receive an exact safe issue packet (`docs/agent-world-environment-generation.zh.md:421-445`). A raw non-JSON response has no parsed source object or field-level diagnostic.

The plan would replace the terminal regression and reclassify that failure at the common wrapper, yet it proposes no common-contract or source-of-truth reconciliation. The existing `local_corrections=1` declaration is not blanket authority to correct every rejected invocation.

### 2. The parser and graph bounds would remain mechanically strict, but that does not make the policy authorized

`_json_object` strictly rejects a non-object/non-JSON completion as `direct_response_not_json` (`agent_world/invocation.py:49-59,160-162`). `GraphRunner` permits a correction only on ordinal one, only for a rejected non-retryable model-node error carrying a packet (`agent_world/graph.py:487-555,671-680`); a second malformed response would terminally fail with no third call. The Direct backend falls back only for retryable failures (`agent_world/invocation.py:97-103`).

Therefore the plan correctly avoids an unbounded retry, fallback-on-malformed, parser heuristic, or malformed-output acceptance. Those safeguards are necessary but insufficient: they do not override the explicit terminal classification in the common contract.

### 3. Successful correction would lose first-turn model/usage provenance under the current handoff

The Direct backend computes response usage before `_json_object`, but raises before it can return an `InvocationResult` (`agent_world/invocation.py:146-162`). `GraphRunner` persists `OperationEvidence` only after `operation(...)` returns successfully (`agent_world/graph.py:487-492,683-693`). Consequently, if a newly correction-eligible non-JSON first turn is followed by a valid second turn, the final passed work would retain the first attempt's code/packet but not the first physical call's route/model or usage-or-unknown evidence.

That is not an honest provenance closure for a newly successful two-call transaction. The plan's claim that semantic-revision inputs stay unchanged is narrowly correct for successful-output acceptance: `_direct_commit` continues to bind only effective projection, output shape, and prompt identity (`agent_world/design.py:599-640`), and `local_corrections` is deliberately omitted from `GraphRunner.semantic_revision` (`tests/test_graph_contracts.py:768-779`). It is incomplete for execution provenance and policy evidence.

### 4. Role and consumer compatibility is otherwise bounded

Direct nodes have no Skill/tool/workspace, and the framework retains parse, correction, compiler, Work, Finding, and release authority (`docs/direct-rewrite-execution-map.zh.md:19-24,53-60,71-87`). The proposed Direct-only catch would not call the Agent adapter or a candidate process. Agent malformed JSON still enters the independent Codex/`_agent_json` boundary and remains terminal; no Agent non-JSON evidence justifies changing it (`agent_world/design.py:540-559`; `tests/test_agent_route_config.py:422-458`).

No valid output contract, graph edge, Artifact ABI, or later consumer needs to change if parser failures remain terminal. If the policy is changed, the six Direct producer contracts all require explicit compatibility evidence; later consumers remain compatible only after the ordinary compiler commits a valid typed artifact.

### 5. Response transport is an unresolved competing hypothesis, not a dismissed one

The local backend spec requires a profile-matched native strict-JSON-schema probe for Direct structured output and says malformed/non-object payloads remain rejected (`.trellis/spec/agent_world/backend/index.md:1813-1868`). Its Direct boundary guide also requires inspecting Prompt, compact protocol, provider route, and safe feedback before selecting regeneration, correction, profile, or adapter action (`.trellis/spec/agent_world/backend/index.md:649-705`).

The supplied replay demonstrates that the frozen input can parse once; it does not establish that response transport is irrelevant, nor does it prove a generic parser-level correction is the right policy. No `response_format` change is authorized by this review, but the plan cannot claim that no request-shape/profile investigation is needed.

## Role Audit

- Framework: remains the only owner of parsing, classification, correction authorization, validation, Work/Finding persistence, and release. It must not hide an extra retry or permit the Direct LLM to choose policy.
- Direct LLM: may only return a fresh complete semantic JSON object against frozen input and an authorized safe packet. It gains no route, budget, Finding, candidate, Judge, Registry, or release authority.
- Agent: is not a consumer or producer of this Direct adapter error; its malformed-output behavior stays out of scope.
- Candidate process/Judge/Registry: do not run unless the ordinary Design compiler commits a valid artifact. No downstream compatibility change is claimed.

## Required Plan Revision Feedback

1. Do not implement the current mapping. It contradicts the existing common feedback contract and the source-of-truth root-error rule.
2. Choose one coherent revised route:
   - **Smallest current-contract route:** retain `direct_response_not_json` as a one-call terminal, preserve the existing terminal regression, and plan only a safe profile-matched response-transport/compact-protocol probe or another separately evidenced Direct recipient-contract change; or
   - **Policy-change route:** explicitly revise the common Direct feedback contract and reconcile the source-of-truth distinction before implementation. State why a non-JSON root failure is no longer a generic output-contract defect, cover all six Direct nodes, and do not characterize it as merely spending an already-authorized compiler correction.
3. For the policy-change route, add a minimal safe failed-invocation provenance handoff: retain the original closed failure code, resolved model/route identity, and measured usage or explicit `unknown` for the first physical call without retaining raw provider content, prompts, credentials, or control fields. Then prove both attempts enter the Work/telemetry closure correctly.
4. Add focused common-wrapper regressions: all six Direct node contracts are covered by the intended policy; exactly one packet reaches the second call; a valid second object commits; a second malformed object terminally has no output and no third call; `direct_response_invalid`, `direct_response_empty`, HTTP/transport, and retryable fallback remain non-correctable. Assert Agent non-JSON remains terminal and untouched.
5. Label the injected-first-failure/live-second-call test honestly as a constructed boundary proof. It cannot substitute for a real provider-format recovery or a fresh public Direct E2E. Read Observe after every real terminal.

## Smallest Permitted Implementation / Proof

No implementation is permitted for this digest.

After a revised plan receives a fresh allow, the smallest proof sequence is:

1. deterministic policy/provenance tests for the selected route;
2. one bounded Direct node/protocol probe with only safe model/usage/terminal facts;
3. Observe immediately after that proof;
4. only if it passes, one fresh public Direct E2E to terminal Observe.

## Non-Claims

- This review does not prove Luna will reliably return JSON, that a response-format mechanism is supported, or that one raw parse failure was caused by prompt, provider, or model behavior.
- It does not authorize `response_format`, parser relaxation, parser scraping, fallback-on-malformed, timeout/model/route changes, a retry subsystem, extra helper/module, node/graph change, Agent change, candidate/Judge/Registry change, or later-child work.
- It does not prove a corrected Direct transaction, full Design, executable Candidate, Integration, Judge, Registry release, Repair, Expand, Consumer, SFT, or RL.

## Next Permitted Gate

Revise the written plan only and submit a new digest to an independent cross-layer critic. Do not dispatch implementation or retry the failed Direct node under this blocked digest.

## Files Found

- `research/diagnosis-direct-non-json-feedback-gap.md` — persisted failure chronology and proposed causal hypothesis.
- `research/direct-non-json-local-correction-plan.md` — reviewed revision `1/2`; digest verified.
- `research/product-alignment-checkpoints.md` — safe run-level checkpoint summary for the failed E2E and replay.
- `agent_world/invocation.py` — strict Direct parser, failure taxonomy, and retryable-only fallback.
- `agent_world/design.py` — common Direct wrapper/commit boundary and independent Agent wrapper.
- `agent_world/graph.py` — fixed two-attempt correction transaction and persisted attempt/evidence handling.
- `agent_world/foundry.py` — Direct failure stops before CandidateGraph.
- `tests/test_design_semantics.py` — terminal non-JSON and parsed compiler-correction regressions.
- `tests/test_graph_contracts.py` — correction bound, terminal evidence, and semantic-revision behavior.
- `tests/test_agent_route_config.py` — independent Agent non-JSON terminal regression.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:258-271,421-445,601-643` — framework/LLM authority, root-error policy, bounded correction, and Direct semantic-node ownership.
- `docs/direct-rewrite-execution-map.zh.md:19-24,53-60,71-87,114-124` — Direct/Agent/framework/candidate role separation and shared Direct node transaction.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:125-148` — binding common correction/terminal classification.
- `.trellis/spec/agent_world/backend/index.md:611-705,1813-1868` — Direct prompt-only/response-transport and native structured-output guidance.

## External References

None. This review uses the target worktree's supplied diagnosis, task contracts, specs, and current code.

## Caveats / Not Found

- The raw provider response is intentionally absent, and the raw durable Observe/run artifacts for the two cited run IDs are not present in this worktree. The chronology is supported here by the supplied Diagnosis Record and Product Alignment Checkpoint, not independently re-parsed raw response data.
- No provider call, test run, code edit, plan edit, spec edit, or git operation was performed during this review.
