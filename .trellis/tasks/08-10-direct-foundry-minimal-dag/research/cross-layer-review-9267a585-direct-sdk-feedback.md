# Research: cross-layer-review-9267a585-direct-sdk-feedback

- Query: Independent read-only `agent-world-cross-layer-critic` review of `research/direct-sdk-feedback-plan.md`.
- Scope: mixed (internal code/contracts plus official SDK documentation)
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `sha256:9267a5855fda23918e8aa520406938b3046470d47ffe008a67a18f3dc8e59710` (verified against the complete supplied plan).
- Plan revision: `1/2`.
- Scope classification: coordinated common-Direct adapter and model-feedback-contract change, not a local ToolSemantics fix. It also changes the shared Agent feedback rendering boundary and proposes a source-contract revision.
- Trigger: the diagnosed real Direct terminal `run_dc28dcded7fe49ce9a2d9a017511831d` at `design/tool_semantics[route_tool_to_maintenance]`, safely recorded as `direct_response_not_json`, rejected and not published.
- Affected trust boundary: Direct route/configuration -> official SDK request/result -> strict completion classification -> Direct wrapper -> `GraphRunner` correction decision and operation evidence -> deterministic compiler/validation -> committed Design Artifact -> Candidate/Judge/Registry/Observe consumers.

## Product target and impact chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. A repaired Direct turn advances only a pre-Design proposal boundary; it is neither a Design/E2E/release proof nor an implementation of Repair, Expand, or Consumer.

The actual affected chain is:

```text
ChatRoute/config
  -> DirectChatBackend._call
  -> OpenAI typed completion or safe InvocationError
  -> DesignExecutor._direct_json / Feedback renderer
  -> GraphRunner.execute (at most ordinal 1 -> ordinal 2)
  -> compiler + ValidationReport/attempt evidence
  -> ArtifactEnvelope + WorkRecord
  -> Modeling Gate -> CandidateGraph
  -> Integration -> Judge -> Package -> Registry -> Observe
```

The Direct producer is shared by six semantic nodes: `world_architecture`, `shared_tool_semantics`, `tool_semantics`, `world_rules`, `curriculum_plan`, and `task_requirement` (`agent_world/graph.py:152-210`; `agent_world/design.py:599-641`). Their downstream contract is unchanged only if strict parsing and the ordinary compiler still commit the same typed Artifact. `DirectFoundry` enters CandidateGraph only after `DesignExecutor.run` succeeds (`agent_world/foundry.py:37-58`); Candidate then requires a passed Integration, a Verifier bundle, Judge evidence, package closure, and Registry publication (`agent_world/candidate.py:554-700`). Thus Candidate, Judge, Registry, package format, lineage, and Observe need no new ABI if the plan keeps invalid output uncommitted and proves that fact.

The shared Agent recipients are separate consumers of an already framework-authorized packet: Design Agent calls append it in `DesignExecutor._agent_json` (`agent_world/design.py:540-559`), while build-plan, verifier-intent, and CandidateBuild calls append it in `CandidateExecutor._agent_json` (`agent_world/candidate.py:708-750`). This wording change must not alter their Codex route, mounted Skill, workspace, or malformed-Agent-output terminal policy.

## What is coherent

The proposed Direct transport direction is minimal and coherent in principle:

- Replacing the hand-written `urllib` transport and its fixed `max_tokens=4096` request (`agent_world/invocation.py:90-163`) with the official `openai==2.54.0` SDK addresses the diagnosed adapter boundary.
- An API-root `base_url`, `max_retries=0`, JSON-object response mode, no output-token parameter, strict JSON-object parsing, and a `finish_reason == "stop"` completeness guard keep request transport separate from semantic acceptance. Zero SDK retries preserves framework ownership of the existing retryable-only primary-to-fallback transition.
- A 300-second physical timeout is transport configuration, not a semantic acceptance rule, provided its timeout outcome remains safely observed and does not become local semantic feedback.

However, these mechanics are not yet an implementable common contract. Current checked-in Direct configuration still stores `/v1/chat/completions` (`config/agent-world.example.toml:4-12`) and the parser accepts it as an arbitrary HTTP(S) URL (`agent_world/config.py:65-79`). With an SDK API-root contract, accepting that suffix can create an incorrectly doubled endpoint. The revised plan must explicitly update the example/config tests and fail closed on endpoint-suffix configuration rather than quietly retaining it as a compatibility path. It must also name client lifecycle/close behavior, the exact SDK exception-to-safe-code table, and the closed `finish_reason` table before implementation.

## Blocking findings

### 1. The proposed malformed-response correction lacks the required common contract and provenance closure

The existing runner does cap correction at exactly two physical calls: it grants a correction only on ordinal one, for a rejected non-retryable Direct/Agent node carrying a `CorrectionPacket` (`agent_world/graph.py:462-555`, `671-680`). That preserves strict validation and prevents an unbounded hidden retry.

But `direct_response_not_json` currently raises before `InvocationResult` is returned (`agent_world/invocation.py:49-59`, `139-163`), and `_direct_json` intentionally converts every `InvocationError` into a non-correctable `DesignError` (`agent_world/design.py:561-587`). Operation evidence is persisted only after `operation(...)` returns (`agent_world/graph.py:487-492`, `683-697`). A successful second response would therefore lose the first completed provider call's safe model/route identity and measured usage-or-unknown value, even though source-of-truth requires all actual attempts to be accounted for and unknown never represented as zero (`docs/agent-world-environment-generation.zh.md:351-354`, `399-412`).

The plan must add a minimal safe failed-invocation provenance handoff for this newly correctable class. It must retain the original closed code, resolved route/model, and measured usage or explicit unknown for the first completed call, without raw content, prompt, credentials, or control fields. It must also precisely limit eligibility to a completed, `stop`-finished response whose nonempty model content fails strict JSON-object parsing. No-choice/envelope failures, empty content, non-`stop` finishes (including truncation), credential/configuration/auth, HTTP/connection/timeout, and the second malformed response must remain terminal; retryable transport alone retains the explicit framework fallback rule. The plan's current prose is not a sufficiently closed classification or evidence contract.

This policy is possible in principle, but it is not already authorized by `local_corrections=1`. The current common contract explicitly says provider, transport, and JSON-parsing failures never enter local correction (`node-contracts.md:125-148`), and its current regression proves the one-call terminal behavior (`tests/test_design_semantics.py:843-881`). A policy change must revise that common contract alongside the source-of-truth, not only change wrapper code and tests.

### 2. Refusing the safe same-object validation frontier would violate the binding product contract

The plan proposes replacing the source requirement with "aggregate issues already safely known" while leaving the current fail-fast validator behavior out of scope. That is not an honest clarification.

The source-of-truth requires one aggregated `ValidationReport` for the WorkAttempt (`docs/agent-world-environment-generation.zh.md:340-344`, `384-389`), requires every safe field-level issue to be retained, and permits compacting only the model-facing brief (`:428-445`). It also explicitly requires all safe problems in a ToolSemantics shard to be aggregated at the same validation frontier (`:601-603`). The independent audit showed the current opposite behavior: `GraphRunner` carries one `CorrectionPacket`, and reviewed Design/Candidate compilers raise at their first discovered failure. The current code confirms that the runner records only one exception packet (`agent_world/graph.py:486-524`) and Candidate validators return at their first rejection (`agent_world/candidate.py:361-466`, `469-538`).

This does **not** require a repository-wide rewrite of every validator or a new feedback service. It does require the revised plan to preserve the product behavior for every currently correction-capable node: either collect and persist the bounded safely known same-object frontier through the existing compiler/runner boundary and render one deterministic compact brief, or terminal-block a node until its validator can provide that safe frontier. Deferring the behavior to the later bounded-Repair child is invalid because this Direct child already owns and spends the node-local correction.

The source-of-truth change in step 6 is therefore blocked as written: it would erase necessary validation evidence rather than distinguish a compact brief from the complete control-plane report. Any revision may clarify that no second validator and no additional call are introduced, but it must retain full safe issue persistence, deterministic grouping, no-progress comparison, strict validation, and the two-call ceiling.

### 3. The user-wish renderer needs an exact recipient and authority contract

The proposed continuity/action/self-check wording correctly distinguishes Prompt, Runtime Skill, observation, Observe, Feedback, local correction, transport retry, and workflow Repair. It is consistent with the source-of-truth rule that a correction is data-only and must not project route/budget/owner/invalidations/release authority (`docs/agent-world-environment-generation.zh.md:428-445`, `631-642`) and with the Direct no-Skill boundary (`docs/direct-rewrite-execution-map.zh.md:19-24`, `114-124`).

It remains incomplete until the plan states that the renderer consumes only an already authorized safe issue set, retains the original frozen objective/input/output contract, and is used identically by both existing wrapper families. It must prove that Agent malformed JSON remains terminal, no Agent Skill or workspace changes, Direct receives no Skill/tools/workspace/provider `instructions`, and neither transport fallback nor outer workflow Repair is encoded as a user-facing correction.

### 4. Source-contract changes must be coordinated rather than documentation-only

The source document is normative (`docs/agent-world-environment-generation.zh.md:1-8`). A revised policy must reconcile all of:

- the source-of-truth root-output/strict-validation rule and full validation-evidence requirement;
- `node-contracts.md` common correction classification;
- the Direct debugging guidance's transport-fingerprint and constructed-proof requirements (`.trellis/spec/guides/agent-llm-node-debugging.md:107-145`); and
- the changed task's Product Alignment Checkpoint before any live proof (`.trellis/spec/guides/foundry-product-alignment.md:23-55`).

Changing only feedback prose cannot reclassify a common Direct terminal or make omitted first-attempt evidence safe. The source-of-truth wins over task research and implementation convenience.

## Required plan revision feedback

1. State the exact common Direct configuration/SDK contract: API-root validation and rejection of the legacy suffix, pinned dependency plus lock update, bounded client lifecycle, request fields omitted/present, precise finish/error-to-safe-code mapping, and fallback eligibility. Keep no raw HTTP path, no output-token argument, and no SDK retry.
2. State the exact exception for a parser-level correction, if retaining it: only a completed `stop` response with attributable nonempty malformed JSON is eligible once; define its safe packet and first-attempt provenance/usage handoff. Preserve terminal behavior for all other malformed/envelope/finish/transport/auth cases and the second malformed response.
3. Revise the common correction/validation plan so it meets the already binding same-object frontier rule for correction-capable nodes. Do not replace the requirement with wording that permits known blockers to be hidden. Do not add a generic feedback service, graph node, retry budget, validator platform, or third model call.
4. Name the coordinated contract files and tests, including `node-contracts.md`, source-of-truth text, Direct/Agent wrapper tests, config/example route tests, and required Product Alignment Checkpoints. The revision must make clear that Agent route/Skill/workspace and Candidate/Judge/Registry artifacts remain unchanged.
5. Make the proof matrix distinguish deterministic and real-boundary evidence:
   - configuration/SDK request, error/fallback, API-root, client-close, and no-token-argument tests;
   - a two-attempt Direct test proving complete first-attempt safe provenance, exact feedback, strict parse, no third call, and terminal non-`stop`/second-malformed cases;
   - a two-independent-safe-issue validation-frontier/brief regression and Agent-recipient regression while keeping Agent malformed JSON terminal;
   - one real, profile-matched Direct SDK node proof that retains only safe category/model/usage facts, followed by Observe; and
   - only then a fresh public Direct E2E to terminal Observe. Any injected malformed-first-result proof is a constructed boundary proof, not evidence that a provider format failure recovered live.

## Compatibility facts and non-claims

- If a second Direct proposal parses and the unchanged compiler accepts it, its committed artifact shape and all Candidate/Judge/Registry inputs are unchanged. If it does not, CandidateGraph is not entered; current `not_run` behavior remains the compatible fail-close path.
- This review does not authorize parser relaxation, heuristic extraction, fallback-on-malformed content, a Responses migration, an output cap, an SDK-managed retry, a new node/service/scheduler, extra local corrections, Agent transport changes, Candidate/Judge/Registry changes, or an automatic workflow Repair.
- It does not prove provider reliability, Design completion, Candidate build, Integration, Judge, package, Registry release, Expand, Consumer, SFT, or RL.

## Smallest next permitted gate

Revise the written plan only, explicitly address the four blocking contract/evidence findings, compute a new digest, and submit that new plan to a fresh independent cross-layer critic. No implementation, provider retry, or live E2E is permitted under this blocked digest.

## Files found

- `research/direct-sdk-feedback-plan.md` — reviewed plan; supplied SHA-256 verified.
- `research/diagnosis-direct-sdk-feedback-boundary.md` — safe chronology and causal hypothesis for the failed Direct node.
- `research/prompt-feedback-observe-retry-principles.md` — intended conceptual distinctions for the renderer.
- `research/correction-feedback-audit.md` — independent evidence that current correction-capable validation is fail-fast.
- `agent_world/invocation.py` — raw Direct HTTP boundary, current cap, parser, fallback, and Codex adapter.
- `agent_world/config.py` and `config/agent-world.example.toml` — current permissive Direct URL input and endpoint-suffix example.
- `agent_world/design.py`, `agent_world/graph.py`, `agent_world/candidate.py`, and `agent_world/foundry.py` — producer, correction, compiler/commit, and downstream ownership chain.
- `agent_world/contracts.py` — current one-issue `CorrectionPacket` contract.
- `tests/test_agent_route_config.py`, `tests/test_design_semantics.py`, and `tests/test_graph_contracts.py` — existing transport, terminal, and bounded-correction coverage.
- `node-contracts.md`, `docs/agent-world-environment-generation.zh.md`, `docs/direct-rewrite-execution-map.zh.md`, and relevant `.trellis/spec/` guides — binding product and role contracts.

## External references

- Official OpenAI Python SDK documentation: <https://github.com/openai/openai-python>. It documents client-level retries, timeout configuration, typed API/connection errors, and explicit client lifecycle. The plan's exact `openai==2.54.0` behavior must be pinned in `uv.lock` and exercised by adapter doubles.

## Caveats / Not Found

- The raw provider response, credentials, and private transcripts were intentionally not read or recorded. The real-run chronology comes from the supplied Diagnosis Record.
- `openai==2.54.0` is not presently a project dependency (`pyproject.toml:7`); the existing `uv.lock` lacks an `openai` package entry. No dependency resolution, test, provider invocation, retry, git operation, or production/spec/task-plan edit was performed.
- `implement.jsonl` and `check.jsonl` were not opened, in accordance with research-role isolation.
