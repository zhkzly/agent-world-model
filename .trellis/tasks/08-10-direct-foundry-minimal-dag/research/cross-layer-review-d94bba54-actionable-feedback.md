# Research: Cross-layer review — actionable Direct Feedback

- Query: Independently review repair-plan revision 1 for the failed Direct `design/tool_semantics[reserve_tool]` proof, including correction authority, raw-response secrecy, retry budget, consumer compatibility, and capacity/sharding scope.
- Scope: internal
- Date: 2026-08-12

## Decision

- Decision: **allow**
- Plan digest: `d94bba5476f326f34778c0cff4b602fed697e9cd09c482bc258bdb59e4b35f90`
- Plan revision: 1
- Revision count: 1 of at most 2 for this diagnosis/plan lineage.
- Scope classification: local, intra-node Direct parser-to-Feedback handoff. It crosses the private `DirectChatBackend` -> `DesignExecutor` handoff but neither changes a graph port, committed Design Artifact schema, node ownership, CandidateGraph input, nor release rule.
- Trigger and evidence: real Direct terminal `run_5d7bd3a844d4458daa56670f4c0003b9` at `design/tool_semantics[reserve_tool]`; both nonempty Luna responses ended `finish_reason=stop`, failed strict JSON-object parsing, stopped after the authorized second call, and produced no release ([diagnosis-direct-format-feedback-repeat.md:18](diagnosis-direct-format-feedback-repeat.md#L18)). The persisted Diagnosis Record precedes this review.
- Affected trust boundary: framework-owned Direct response classification and the one authorized in-memory `assistant` -> framework-authored `user` format-Feedback turn. The Direct LLM remains prompt-only and has no routing, retry, Artifact, Gate, Judge, or release authority.

## Canonical target

Turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This repair advances only a single uncommitted Direct ToolSemantics leaf; it is not evidence of Candidate, Integration, Judge, Package, Registry, Expand, Consumer, or end-to-end success.

## Findings

### Plan and diagnosis fit

- The diagnosis establishes a narrow causal gap: the strict parser discarded a safely observable malformed-output subtype, so the second user turn stated only the failed end state rather than the specific correction to make ([diagnosis-direct-format-feedback-repeat.md:85](diagnosis-direct-format-feedback-repeat.md#L85)). It explicitly rejects a third call, parser relaxation/extraction, fallback, prompt/Skill change, and topology change ([diagnosis-direct-format-feedback-repeat.md:53](diagnosis-direct-format-feedback-repeat.md#L53)).
- The reviewed plan limits the change to one closed parse condition, its existing `CorrectionPacket` rendering, focused tests, and the exact frozen-parent leaf proof ([direct-actionable-feedback-plan.md:17](direct-actionable-feedback-plan.md#L17)). This is the smallest coherent scope for the observed defect.

### Feedback is an actionable next user wish

- The allowed Feedback must carry the safe observed `path + condition + expected category`, state the concrete replacement action for that condition, request one complete JSON-object replacement rather than a patch or explanation, and require a whole-output self-check. It must retain the original objective, frozen input projection, and output shape. This matches the Diagnosis Record ([diagnosis-direct-format-feedback-repeat.md:96](diagnosis-direct-format-feedback-repeat.md#L96)) and the project contract for a safe correction packet ([node-contracts.md:127](../node-contracts.md#L127)).
- Current format feedback is materially too generic: it says only that the answer was not one valid object ([agent_world/design.py:74](../../../../agent_world/design.py#L74)). Current semantic feedback already carries the existing packet and asks for a complete replacement/self-check ([agent_world/design.py:116](../../../../agent_world/design.py#L116)). The plan may make their recipient-facing structure consistent, but may not alter semantic validation, proposal shape, or feedback authority.

### Safe parsing, secrecy, and unchanged Direct contract

- The private failure envelope currently carries raw content only in memory ([agent_world/invocation.py:43](../../../../agent_world/invocation.py#L43)); strict Direct parsing accepts only a top-level JSON object ([agent_world/invocation.py:71](../../../../agent_world/invocation.py#L71)). The approved category is diagnostic-only: classifying a fence, outer non-JSON text, a non-object JSON root, or syntax location must not strip/extract/wrap and accept that response.
- The existing backend reconstructs exactly `system -> original user -> rejected assistant -> Feedback user`, keeps `response_format={"type":"json_object"}`, and falls back only after a retryable transport/provider exception ([agent_world/invocation.py:129](../../../../agent_world/invocation.py#L129), [agent_world/invocation.py:156](../../../../agent_world/invocation.py#L156), [agent_world/invocation.py:176](../../../../agent_world/invocation.py#L176)). The plan expressly keeps system text, frozen user payload, output shape, previous ephemeral assistant turn, route, and compiler unchanged ([direct-actionable-feedback-plan.md:24](direct-actionable-feedback-plan.md#L24)).
- The implementation may persist only the closed condition through the pre-existing `CorrectionPacket` field. It must never persist raw response text, parser/provider exception prose, credentials, or model-private content. The current graph persistence writes packet-shaped correction evidence and operation metadata, not the raw proposal ([agent_world/graph.py:510](../../../../agent_world/graph.py#L510)); existing regression coverage scans persisted bytes for rejected output ([tests/test_design_semantics.py:1083](../../../../tests/test_design_semantics.py#L1083)).

### Retry and authority compatibility

- No extra retry is authorized. `tool_semantics` is the only Direct node with the existing bounded two-local-correction policy ([agent_world/graph.py:178](../../../../agent_world/graph.py#L178)). Its current eligibility rule explicitly prevents a third proposal whenever either the prior or current issue is `direct_response_not_json` ([agent_world/graph.py:702](../../../../agent_world/graph.py#L702)); focused regression coverage already verifies the format/semantic mixed cases ([tests/test_graph_contracts.py:908](../../../../tests/test_graph_contracts.py#L908)). The plan must preserve that code and continue using the same code value for format failure.
- Framework/Designer owns classification, validation, the correction packet, call authorization, commit, and terminal non-release. The Direct model only receives the existing prompt plus the authorized next user turn; it cannot claim completion or choose another call. CandidateBuild, Judge, Controller ReleaseKernel, and Registry remain untouched.

### Impact chain and downstream compatibility

```text
DirectChatBackend strict parser
  -> private _DirectFormatFailure(raw ephemeral + safe condition)
  -> DesignExecutor creates existing CorrectionPacket / actionable Feedback
  -> GraphRunner applies existing two-call eligibility and records safe evidence
  -> [success] unchanged ToolSemantics Artifact
       -> WorldRules / Curriculum / Task / ModelingGate
       -> CandidateGraph -> Judge -> Package -> Registry -> Observe
  -> [second format failure] same terminal non-release; no downstream work
```

- Producer: `DirectChatBackend` changes only a private rejected-response diagnostic. Immediate consumer: `DesignExecutor._direct_commit` still emits the same `direct_response_not_json` and uses the same compiler path ([agent_world/design.py:635](../../../../agent_world/design.py#L635)).
- The committed success shape remains `ToolSemanticsSourceDraft` / `ToolDraft`; the node contract remains one exact tool plus related catalog/shared contract/citations and one independently committed Artifact ([node-contracts.md:381](../node-contracts.md#L381)). No Artifact envelope, graph edge, semantic source field, Candidate ABI, Package content, Registry receipt, or Observe projection changes.
- A rejected attempt's safe correction evidence will intentionally have a different content digest when its condition becomes more precise. That is a diagnostic-evidence change, not a byte change to a committed ToolSemantics Artifact or a downstream ABI. Later consumers are compatible because they consume only a successfully committed artifact; terminal runs remain terminal.

### Capacity and sharding ruling

- Deferring any further split is justified. The two real responses stopped normally rather than truncating; the first used 5,885 input and 1,976 output tokens; and ToolSemantics already executes one frozen tool per physical shard ([diagnosis-direct-format-feedback-repeat.md:102](diagnosis-direct-format-feedback-repeat.md#L102)). The implementation loop independently calls `_direct_commit` for every `architecture.tools` member ([agent_world/design.py:1449](../../../../agent_world/design.py#L1449)).
- This evidence supports a format/recipient-feedback repair, not an input- or output-capacity diagnosis. The source contract forbids imposing a hidden fixed input/token ceiling or forcing semantic sharding without a real attributable terminal ([docs/agent-world-environment-generation.zh.md:608](../../../../docs/agent-world-environment-generation.zh.md#L608)).
- If a future real terminal proves capacity, a new diagnosis and critic review may authorize calls split only at independent schema-owned semantic coordinates, with framework validation of each result and deterministic assembly. Raw token chunking an object, accepting fragments, or disguising a topology change as Feedback remains forbidden ([diagnosis-direct-format-feedback-repeat.md:105](diagnosis-direct-format-feedback-repeat.md#L105)).

## Smallest allowed implementation and proof

1. Change only `agent_world/invocation.py` and `agent_world/design.py` for runtime behavior: add a bounded closed condition to the private format failure, map it into the existing safe packet, and render the existing one Feedback user turn as the actionable replacement request. Do not change `graph.py`, node declarations, routes, response mode, parser acceptance, compiler, fallback policy, Skills, or Artifact schemas.
2. Add focused parser/conversation/graph tests. They must show: strict valid object acceptance; each closed rejected category remains rejected; only the safe condition reaches Feedback; the original user/system/output contract and four-message sequence are unchanged; raw rejected text is present only in the in-memory assistant slot and absent from persisted files; and every format path ends after two proposals even when paired with a semantic error.
3. Run the plan's deterministic suite: focused tests, full pytest, Ruff format/check, mypy, and compileall.
4. Run only the immutable-parent `design/tool_semantics[reserve_tool]` Luna proof, then read Observe immediately. It may establish a committed ToolSemantics Artifact within the existing two calls, or an honestly safe terminal with no third call. It is not an E2E/release proof.

## Related contracts and files examined

- `AGENTS.md` — requires the Observe -> Diagnosis -> plan -> critic -> implementation -> proof sequence and an independent reviewer after a failed Direct proof.
- `docs/agent-world-environment-generation.zh.md:421` — permits the sole completed/nonempty/`stop` strict-JSON exception while preserving output contract, raw secrecy, and no third call.
- `docs/direct-rewrite-execution-map.zh.md` — Direct remains a Prompt-only model boundary; framework owns validation and release.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — feedback is the next framework-authored user wish and rejected content stays only as an ephemeral prior assistant turn.
- No external reference was used; the decision relies on the frozen plan, Diagnosis Record, repository contracts, source, and existing tests.

## Non-claims and next permitted gate

- This allow does not claim that Luna will honor JSON-object mode, that the exact leaf will pass, that a parser relaxation is acceptable, or that any later Direct/Candidate/Registry boundary has passed.
- It does not authorize a third format call, fallback after malformed content, extra retry accounting, a Prompt/Skill/route change, generic response-normalization service, split ToolSemantics calls, raw-token chunking, or any Expand/Consumer work.
- The plan's documentation step is not runtime authorization. The existing debugging guide already defines the next-user-wish rule; any capacity/sharding clarification must remain documentation-only and be made through the normal spec-update gate after the implementation/proof evidence.
- Next permitted gate: the main planner may add this exact current allow record to `implement.jsonl` and `check.jsonl`, then dispatch implementation limited to this digest. Any change to the digest, trust boundary, or a new real terminal expires this allow and requires Observe -> new Diagnosis Record -> revised plan -> fresh independent review.

## Caveats / Not Found

- The real terminal intentionally did not retain the malformed raw content, so the exact provider subtype remains unproven. The approved categories are safe feedback diagnostics, not a claim that the provider returned a fenced object, outer prose, non-object JSON, or a specific syntax error.
- No real capacity failure was found. A normal `finish_reason=stop` is affirmative evidence against treating this repair as a sharding decision, but it does not prove future requests can never exceed provider capacity.
- No production code, plan, diagnosis, test, spec, task JSONL, or existing research record was edited by this reviewer.
