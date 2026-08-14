# Cross-Layer Review: agent-response-parse-retry (diagnosis 15)

- Decision: **allow**
- Plan digest: 6c932849 (sha256 of plan-agent-response-parse-retry.md, first 8 hex)
- Plan revision: 1
- Scope classification: local (single-node, builder lane, agent_world/candidate.py only)
- Revision count: 1 of at most 2
- Reviewer model: deepseek-v4-pro (explicit spawn not required; local review, scope demonstrably local)

## Trigger
E2E resume terminal agent_response_not_json on run_386e4f07c70d4f61be9cafbf82edcc55
(need: 用户预订宾馆), build_plan node, inv 1, 04:57:59. Exactly one attempt recorded; run aborted.

## Diagnosis evidence (verified against code)
- invocation.py:371 _json_object(output, "agent_response_not_json") raises InvocationError(SafeFailure("agent_response_not_json", "rejected")). CONFIRMED: SafeFailure status "rejected", retryable defaults False.
- candidate.py:1058-1061 _agent_json except InvocationError converts ANY code to raise CandidateError(code, status, retryable) — drops the correction identity (no CorrectionPacket). CONFIRMED.
- candidate.py:140-141 _node_error maps CandidateError -> NodeExecutionError WITHOUT correction. CONFIRMED.
- candidate.py:633-639 _model_rejection(code, path, violated_condition, expected_category) returns NodeExecutionError with correction=CorrectionPacket(...), status default "rejected", retryable default False. CONFIRMED.
- candidate.py:1196-1226 _build_plan operation wraps _agent_json in except CandidateError: raise _node_error. NOTE: _model_rejection returns NodeExecutionError, which is NOT a CandidateError (sibling RuntimeError subclasses), so it propagates past this handler directly to graph.execute. CONFIRMED correct propagation.
- graph.py CANDIDATE_NODES build_plan NodeSpec is execution_kind="agent", route="agent", no explicit local_corrections -> default local_corrections=1. CONFIRMED.
- graph.py:650 loop range(1, node.local_corrections + 2) = ordinals {1,2}.
- graph.py:850-883 _eligible_local_correction: ordinal 1 = execution_kind in {direct_llm,agent} AND status=="rejected" AND not retryable AND correction is not None AND local_corrections >= 1 -> True for build_plan. ordinal 2 requires execution_kind=="direct_llm" and route=="direct" and local_corrections==2 -> False for agent node. CONFIRMED: exactly ONE in-session re-prompt.

## Affected trust boundary
Builder agent invocation conversion in CandidateExecutor._agent_json (candidate.py). The correction loop, budget, and eligibility remain framework-owned and unchanged. Correction mechanism and correction injection are already present and unchanged.

## Repeated product target
EnvironmentRequest -> Research -> Design/WorldSpec -> Task/Verifier/Implementation -> Builder -> isolated Runtime -> independent Judge -> Package -> Registry -> Observe.
This plan advances the Builder lane of the Direct path by making a malformed-agent-JSON transient correctable in-session instead of an unrecoverable single-attempt abort.

## Impact chain
producer InvocationBackend (invoke_json -> InvocationError code agent_response_not_json) -> changed handoff _agent_json conversion (now raises NodeExecutionError with CorrectionPacket for this code only) -> immediate consumer graph.execute correction loop (eligible at ordinal 1) -> corrected proposal re-enters _agent_json with the authorized packet appended to instruction (candidate.py:1031-1034) -> same node re-prompts once -> build_plan proposal -> candidate_build -> judge -> package -> registry -> observe. Unchanged downstream: candidate_build, integration, judge, registry, observe.

## Owners
- Correction packet construction: _model_rejection (candidate.py) — unchanged.
- Correction budget/eligibility: graph.py _eligible_local_correction / NodeSpec.local_corrections — unchanged, framework-owned.
- Conversion branch: _agent_json — the only edited surface.

## Compatibility facts
- _model_rejection call in plan matches existing signature exactly (code, path, violated_condition, expected_category).
- Raising NodeExecutionError (not CandidateError) bypasses except CandidateError wrappers at all three _agent_json call sites (1196/1251/1440), so NodeExecutionError reaches graph.execute uncorrupted. The plan only alters the agent_response_not_json branch; all other InvocationError codes keep CandidateError -> _node_error (no correction), preserving non-correctable transport/timeout semantics.
- No other consumer handles agent_response_not_json (grep: only invocation.py:371 producer and tests/test_agent_route_config.py:683 assertion). No consumer depends on _agent_json raising CandidateError specifically for this code.
- Correction injection path (1031-1034) appends only the canonical CorrectionPacket (code, path, fixed violated_condition string, category) — no secret, credential, raw output, or private data enters the packet text. The violated_condition is a fixed literal, not the malformed output.

## Unproved consumers / non-claims
- Whether the transient repeats across later agent nodes (same class, e.g. candidate_build) is not claimed and is out of scope.
- Judge, integration, and Registry outcomes remain unproven until the real resume run reaches a terminal honestly.
- The plan does not claim Registry receipt; it only claims the corrected re-prompt mechanism and honest progression.

## Smallest allowed implementation and proof plan
Implementation: in _agent_json except-InvocationError block, branch on exc.failure.code == "agent_response_not_json" to raise _model_rejection("agent_response_not_json", "$", "<fixed instruction>", "object"); keep all other codes on the existing CandidateError conversion. No other file.
Deterministic: unit test with fake agent backend raising InvocationError(SafeFailure("agent_response_not_json","rejected")) first call, valid proposal second call — assert attempt1 correction_requested and attempt2 passed, and second instruction contains the authorized packet. Second test asserts other codes (e.g. agent_timeout) fail without correction. Existing 299 tests stay green.
True boundary: pure --resume of run_386e4f07... (design graph skipped, build_plan re-runs); a malformed first response must yield a correction_requested attempt + a second in-session attempt, then run proceeds to next terminal honestly.

## Deterministic checks
1. Unit: correction_requested on first malformed response; second attempt passes; correction packet present in second instruction.
2. Unit: non-json other codes still fail without correction (regression guard).

## True-boundary proof
Pure --resume re-run of the exact failed run; design graph skipped; build_plan re-executes; observe attempt records show inv1 correction_requested (code agent_response_not_json, correction present) and inv2 outcome; run stops at first new terminal and is re-attributed. Registry receipt remains the only release verdict.

## Explicit non-claims
No transport/model retry; no new budget or local_corrections change; Direct direct_response_not_json path untouched; Judge-gate semantics (previous lineage) untouched; no claim of Judge/registry completion from graph/test progress.

## Next permitted gate
Implementation (after allow) -> agent-world-real-execution-proof (pure --resume) -> Observe. Append builder-lane Product Alignment Checkpoint note to pac-judge-node-family.md after proof.
