# Research: cross-layer review — Direct SDK format Feedback

- Query: Is the 78-line Direct-only plan with digest `sha256:12fc5ef06c9d829acd7b70a6d4f13dc4151f9027919cec838eef60e2bb07e621` the smallest coherent implementation of the user-authorized one-turn format Feedback exception?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `sha256:12fc5ef06c9d829acd7b70a6d4f13dc4151f9027919cec838eef60e2bb07e621` — verified from the complete 78-line plan file.
- Plan revision: new Direct-only lineage, revision `1/2`; it is not a third revision of the blocked mixed `07cee5d8` lineage.
- Scope classification: coordinated Direct adapter and Direct Design-transaction handoff, with the existing graph transaction/evidence closure as the immediate consumer. It is not a Controller, Repair, Release, Agent, compiler, Candidate, Judge, Registry, Expand, or Consumer change.
- Trigger: real terminal `run_dc28dcded7fe49ce9a2d9a017511831d` at `design/tool_semantics[route_tool_to_maintenance]`, safe code `direct_response_not_json`, before Candidate/Judge/Registry (`research/diagnosis-direct-sdk-format-feedback-minimal.md:4-26`).
- Policy authority: the user explicitly supersedes the prior blanket root-format rule only for a completed, nonempty, `finish_reason=stop` Direct answer that fails strict JSON-object parsing. The earlier `07cee5d8` block is therefore not a contradiction for this narrower lineage.

## Product target and affected boundary

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This plan advances only the Direct Design proposal handoff; it does not establish any later product stage.

The affected chain is:

```text
Direct ChatRoute/config
  -> DirectChatBackend official-SDK call and safe classification
  -> DesignExecutor Direct in-memory transaction
  -> existing GraphRunner two-ordinal transaction + OperationEvidence/WorkRecord
  -> safe Observe facts
  -> unchanged typed Design artifact on success
  -> unchanged Candidate -> Integration -> Judge -> Package -> Registry consumers
```

Framework remains the sole owner of route configuration, SDK transport, response classification, one-turn authorization, strict parsing, evidence persistence, terminal failure, and release. The Direct model owns only an untrusted proposal. The ephemeral rejected text is permitted only as the immediately preceding Direct `assistant` message before the one framework-authored Feedback `user` message; it is never an Artifact, `CorrectionPacket`, `OperationEvidence`, failure evidence, Observe field, Skill, or durable transcript.

## Findings

### Files found

- `research/diagnosis-direct-sdk-format-feedback-minimal.md` — records the real non-JSON Direct terminal, narrow user policy, and required proof order.
- `research/direct-sdk-format-feedback-minimal-plan.md` — reviewed 78-line implementation/proof plan; its SHA-256 matches the requested digest.
- `research/cross-layer-review-07cee5d8-direct-sdk-feedback-r2.md` — prior block; its source-policy premise is narrowly overridden by the current user instruction.
- `agent_world/invocation.py` — current raw-`urllib` Direct adapter parses the response before the Design transaction can persist operation evidence.
- `agent_world/design.py` — current Direct producer wrapper and the immediate bridge into `GraphRunner`.
- `agent_world/graph.py` — existing bounded two-ordinal correction transaction and safe evidence persistence.
- `agent_world/contracts.py` — closed safe `OperationEvidence` and generic `CorrectionPacket` contracts.
- `agent_world/config.py` and `config/agent-world.example.toml` — Direct route currently accepts the endpoint suffix that the SDK-root plan removes.
- `tests/test_agent_route_config.py`, `tests/test_design_semantics.py`, and `tests/test_graph_contracts.py` — focused route, Direct-format, correction ceiling, and evidence regressions.

### Code patterns and compatibility facts

- The raw Direct adapter appends `/chat/completions`, sends a hard `max_tokens=4096`, and raises `direct_response_not_json` while constructing `InvocationResult` (`agent_world/invocation.py:49-59`, `90-163`). Replacing that one adapter with the official SDK is causally local and removes the unwanted adapter-level behavior.
- Direct Design calls enter through `_direct_json`, then `_direct_commit` supplies the existing `GraphRunner.execute` operation/evidence callbacks (`agent_world/design.py:561-645`). The plan's in-memory format handoff belongs here; no Agent wrapper needs a new input, Skill, workspace, or correction format.
- `GraphRunner` already permits only ordinal 1 to request one local correction and makes ordinal 2 terminal (`agent_world/graph.py:487-538`, `672-679`). A first eligible format failure can use that fixed ceiling; a malformed or otherwise rejected replacement cannot create a third semantic call or workflow Repair.
- `OperationEvidence` permits only category, node, model, canonical measured usage, and Agent-only skill digest (`agent_world/contracts.py:114-150`). The plan can preserve both physical-call facts without storing rejected text. Existing evidence persistence occurs before compilation for a returned proposal (`agent_world/graph.py:489-492`, `683-697`).
- The old focused regression deliberately asserts one-call terminal behavior for `direct_response_not_json` (`tests/test_design_semantics.py:843-881`); changing that one expectation is required by the explicit user override. The existing compiler-correction test already demonstrates the one-correction/two-attempt ceiling (`tests/test_graph_contracts.py:770-814`).
- Candidate, Judge, Registry, release, Expand, and Consumer consume only a committed typed Design artifact. A successful replacement yields the same artifact contract; a second failure retains the existing safe failed WorkRecord/Finding path. Their interfaces and owners remain compatible and untouched.

### Strictness and minimal implementation boundary

The allowed implementation is limited to the plan's Direct-only path:

1. Use a context-managed official `OpenAI` Chat Completions client with the configured API root, explicit zero SDK retries, a 300-second timeout, JSON-object mode, no Direct output-token cap, and the existing closed safe error/fallback classification.
2. Keep malformed response text in a Direct-only, per-node in-memory handoff long enough to reconstruct `system -> original user -> rejected assistant -> Feedback user`; pass no raw text through a generic correction/evidence/persistence contract.
3. Return/persist only the safe model and measured-or-unknown canonical usage for each completed physical call, then strictly validate the replacement through the unchanged Direct compiler and graph transaction.
4. Treat "strict JSON object" as the declared no-Markdown whole-object contract. The focused test should make this concrete by classifying code-fenced or prose-wrapped content as `direct_response_not_json`, rather than retaining a normalizer that accepts it as a successful object (`agent_world/invocation.py:49-59`). This is within the plan's stated strict-validation scope, not a new feedback mechanism.

The existing route credential handle must remain the sole credential source when constructing the SDK client (`agent_world/config.py:138-143`); neither ambient SDK environment discovery nor a raw provider exception may become persisted evidence. This preserves the existing Direct credential boundary and does not alter the Agent adapter.

## Related specs

- `AGENTS.md` — requires real calls behind `InvocationBackend`, no secret persistence, a Direct first-package path, and a critic allow before implementation.
- `docs/agent-world-environment-generation.zh.md:421-445` — defines framework-owned validation/correction boundaries; the user instruction supplies the explicit narrow exception to its prior root-format default.
- `docs/agent-world-environment-generation.zh.md:508-513,631-642` — Direct receives only rendered prompt/input plus authorized feedback; code owns the bounded correction and terminal handling.
- `.trellis/spec/agent_world/backend/index.md` — requires a single `InvocationBackend` boundary, explicit retry ownership, safe configuration/credential handling, and opt-in live proof.
- `.trellis/spec/guides/agent-llm-node-debugging.md:8-43` — permits the logical `initial user -> rejected ephemeral assistant -> Feedback user` sequence while forbidding raw-output persistence and hidden continuation state.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:125-148` — must receive the stated Direct-only JSON-format exception; Agent and parsed-semantic contracts remain unchanged.

## External references

- [Official openai-python README](https://github.com/openai/openai-python/blob/main/README.md) documents client-level `base_url`, `timeout`, and `max_retries=0`; the plan's SDK use does not require an SDK-owned retry loop.
- [Official Chat Completions parameter definition](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/completion_create_params.py) documents `response_format={"type":"json_object"}` as JSON mode. The plan continues to perform its own strict object validation after transport.

## Smallest tests and proof

Deterministic regression checks:

1. SDK double: API-root construction, explicit configured credential path, client close, `max_retries=0`, 300-second timeout, JSON-object response mode, no output-token parameter, and closed safe exception mapping.
2. Direct-only conversation: a nonempty `stop` malformed first completion produces exactly the four logical messages and one complete replacement; exactly two completed calls contribute safe model/usage evidence; raw completion content is absent from every Artifact and Observe projection.
3. Terminal matrix: code-fenced/prose-wrapped malformed input, second malformed input, non-`stop`, empty/refusal/invalid envelope, and transport/auth failures receive no format Feedback and no third semantic call. Existing parsed-semantic correction and Agent correction behavior remain unchanged.
4. Run the focused tests plus the plan's full pytest, Ruff, mypy, compileall, and legacy-firewall checks.

True-boundary proof, after implementation and deterministic review: run one real Luna `ToolSemantics` node through the official Direct SDK adapter and read Observe. Only if that passes, run one fresh public Direct E2E and read terminal Observe; stop and create a new diagnosis at the first new terminal.

## Non-claims

- This allow does not prove an SDK call, a repaired node, full Design, Builder, Integration, Judge, Package, Registry, E2E success, or release.
- It does not authorize Agent feedback/Skill/workspace changes, compiler or generic `CorrectionPacket` changes, a feedback service, new graph node, new retry/model policy, workflow Repair, Candidate/Judge/Registry changes, or Expand/Consumer work.
- It does not authorize raw rejected model text in durable evidence, logs, artifacts, package contents, Observe, or user-visible errors.
- It does not relax JSON-object parsing, compiler validation, hard gates, or the one-correction/two-ordinal ceiling.

## Caveats / Not Found

- No provider was invoked; no E2E or test command was run; no production/spec file or task JSONL was read or edited during this review.
- The official SDK documentation confirms the reviewed transport controls, but a live configured-provider proof remains required for the configured Luna route.
- Next permitted gate: add this matching allow record to the implementation/check context, dispatch implementation strictly to this digest, perform deterministic review, then execute the stated real-node proof and read Observe.
