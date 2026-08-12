# Research: cross-layer-review-07cee5d8-direct-sdk-feedback-r2

- Query: Is plan `07cee5d8e3746bcf4417777a4a0846678e6b6a0987f9848826befd303d92cc63` the smallest safe repair for the observed Direct `tool_semantics` non-JSON terminal?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `sha256:07cee5d8e3746bcf4417777a4a0846678e6b6a0987f9848826befd303d92cc63` (verified).
- Plan revision: `2/2`; the replacement below must be a new, narrower Direct-only plan lineage, not a third revision of the mixed plan.
- Scope classification: coordinated Direct adapter + failed-call evidence boundary. The submitted plan unnecessarily crosses into generic Agent context and parsed semantic-compiler feedback.
- Trigger / evidence: real Direct run `run_dc28dcded7fe49ce9a2d9a017511831d` reached `design/tool_semantics[route_tool_to_maintenance]` and terminaled `direct_response_not_json`; Candidate, Judge, and Registry did not run (`diagnosis-direct-sdk-feedback-boundary.md:25-49`).

## Why the supplied scope is not minimal

The product target remains: turn an `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it, and release an immutable Registry `EnvironmentPackage`. This repair advances only the first Direct Design handoff; it cannot claim Candidate, Judge, Registry, Expand, or Consumer completion.

The source contract makes JSON/root-format failures framework/output-contract terminals: generic root schema errors or mechanical failures without an exact safe field path do not consume an LLM correction (`docs/agent-world-environment-generation.zh.md:421-432`). Only a shape-correct proposal rejected by the compiler/semantic validator may produce a one-correction brief (`:428-445`). Therefore the observed non-JSON `stop` response must remain a one-call terminal after the SDK fix; it must not become a four-message continuation or expose the rejected content to a second Direct call.

The four-message sequence is a conditional contract for an *already authorized parsed semantic correction*—the prior answer is then ephemeral and the new feedback is a user turn (`.trellis/spec/guides/agent-llm-node-debugging.md:12-43`). It is not authorization to correct this pre-parse terminal. Direct and Agent contexts are intentionally different (`docs/agent-world-environment-generation.zh.md:502-513`), so changing generic Agent feedback has no causal evidence here.

Likewise, the audit's A-to-B compiler-feedback defect is real but separate. For a future parsed semantic case, the full `ValidationReport` must retain every safe issue and a brief may group it (`docs/agent-world-environment-generation.zh.md:428-445`; `.trellis/spec/agent_world/backend/index.md:1740-1756`). A global `1..12` tuple across Design/Candidate compilers neither repairs this non-JSON failure nor substitutes for that future full-report contract.

## Impact chain and compatibility

`DirectChatBackend` currently hand-builds `urllib` `/chat/completions` requests, applies `max_tokens=4096`, and parses before returning `InvocationResult` (`agent_world/invocation.py:90-163`). `DesignExecutor._direct_json` then maps any `InvocationError` to a non-correctable `DesignError` (`agent_world/design.py:561-587`). `GraphRunner` persists operation evidence only after `operation()` returns (`agent_world/graph.py:487-515`), so the completed malformed call loses its route/usage evidence; its terminal record otherwise already carries the safe code (`agent_world/graph.py:498-522`).

Framework owns SDK transport, classification, evidence, validation, correction authorization, and release; the Direct model owns only a Prompt-only proposal. The only changed consumer should be the existing Direct Design transaction and its existing `OperationEvidence`/attempt/failure artifacts. Agent wrappers, `CorrectionPacket`, Design/Candidate compilers, graph topology, Candidate, Judge, Registry, and Observe schema remain compatible by remaining untouched. The current regression explicitly expects this non-JSON case to terminal after one call with no correction (`tests/test_design_semantics.py:843-881`).

## Smallest replacement scope

1. Replace only the raw Direct HTTP adapter with the official OpenAI SDK at an API-root route; retain JSON-object transport, `max_retries=0`, a physical timeout, strict object parsing, and no application output-token cap or legacy endpoint-suffix compatibility.
2. Classify a completed nonempty `stop` response that is not one strict JSON object as terminal `direct_response_not_json`; do not fallback, correct, retain raw content, or send a second Direct request.
3. Add only the narrow existing failure/evidence handoff needed to persist that completed Direct call's resolved model, measured-or-unknown usage, and safe outcome code before the existing terminal path. Do not add OperationRun/lease/span services, a retry framework, or public Observe fields.
4. Keep the Direct initial request Prompt-only and two-message-shaped; delete the four-message continuation for this terminal. Reserve it for a separately diagnosed, authorized parsed-semantic correction.
5. Do not change Agent feedback, `CorrectionPacket`, any Design/Candidate compiler, or all-compiler `1..12` aggregation in this plan.
6. Deterministically prove SDK request shape/close/no hidden retry/no output cap, closed result classification, and one malformed completed call's safe evidence plus one-call terminal behavior.
7. Then run one profile-matched real Direct ToolSemantics node, read Observe, and only after it passes run the fresh public Direct E2E; stop and diagnose the first new terminal.

## Required contract versus deferred work

- Required now: an official SDK Direct adapter, strict fail-closed format handling, Direct no-Skill/no-hidden-instruction isolation, and secret-safe evidence for the physical failed call. The source requires real model calls through an `InvocationBackend` adapter, not raw HTTP or a fabricated path (`docs/agent-world-environment-generation.zh.md:590-592`).
- Deferred but not erased: full safe issue retention/grouped feedback and four-message continuation when a future *parsed, shape-valid semantic* failure is independently diagnosed and authorized; generic Agent conversation changes need their own failure and plan.
- Optional future hardening: broad operation-attempt machinery, generic feedback services, new graph nodes, additional fallback policy, and any cross-compiler aggregation architecture.

## Smallest proof and non-claims

Deterministic tests are regression evidence only. The next true-boundary proof is one real Direct ToolSemantics invocation followed by Observe; a passing node still proves neither complete Design nor Candidate/Integration/Judge/Registry release. No provider call, E2E, or code edit occurred during this review.

## Files inspected

- `AGENTS.md` — product authority, SDK adapter, and critic-gate rules.
- `docs/agent-world-environment-generation.zh.md` — Direct, feedback, correction, and operation-evidence source contract.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-direct-sdk-feedback-boundary.md` — observed run and causal hypothesis.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-sdk-feedback-plan.md` — reviewed plan (digest verified).
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/correction-feedback-audit.md` — separate parsed-semantic A-to-B finding.
- `agent_world/invocation.py`, `agent_world/design.py`, `agent_world/graph.py`, `agent_world/contracts.py` — current Direct/result/evidence boundary.
- `tests/test_agent_route_config.py`, `tests/test_graph_contracts.py`, `tests/test_design_semantics.py` — directly relevant adapter, correction, and non-JSON regressions.

## External references

No external lookup was performed by request. The reviewed plan's `openai==2.54.0` pin is recorded as plan evidence, not independently revalidated here.

## Caveats / Not Found

- This critic did not read task JSONL, invoke a provider, run tests/E2E, inspect unrelated history, or edit production/spec files.
- Next permitted gate: write the new Direct-only plan above, digest it, and submit it to a fresh independent critic before implementation.
