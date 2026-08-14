# Repair Plan: bounded in-session rework for malformed agent JSON (diagnosis 15)

Scope: local, builder lane — agent_world/candidate.py only. No prompt,
skill, route, graph, Judge, or release-policy change.

## Change 1 — correction packet for agent_response_not_json

In CandidateExecutor._agent_json (candidate.py:1058-1061), when the
InvocationError carries code "agent_response_not_json", raise
_model_rejection(
    "agent_response_not_json",
    "$",
    "the agent response was not one parseable JSON object; return exactly "
    "one JSON object with no prose, labels, or Markdown fences",
    "object",
)
instead of the plain CandidateError. _model_rejection already builds a
NodeExecutionError with a CorrectionPacket (candidate.py:633-639); the
node's existing correction loop (local_corrections=1) then re-prompts the
agent once in the same session, and _agent_json appends the authorized
packet to the instruction (candidate.py:1031-1034) — no new mechanism.

All other InvocationError codes keep their current conversion
(CandidateError -> _node_error without a packet): provider/transport/
timeout classes remain non-correctable.

## Explicitly not changed

- No transport retry, no new budget, no local_corrections change.
- Direct's direct_response_not_json path untouched.
- Judge-gate semantics plan (previous lineage) untouched.

## Verification

1. Deterministic: unit test with a fake agent backend that raises
   InvocationError(SafeFailure("agent_response_not_json", "rejected")) on
   the first call and returns a valid proposal on the second — assert the
   node records attempt 1 correction_requested and attempt 2 passed, and
   that the second call's instruction contains the authorized correction
   packet. A second test asserts other codes (e.g. agent_timeout) still
   fail without a correction. Existing 299 tests stay green.
2. Real boundary (mandated): pure `uv run agent-world generate --config
   config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55` — design graph skipped, the
   candidate graph re-runs from build_plan; stop at the first new terminal
   and re-attribute. Registry receipt remains the only release verdict.

## Product Alignment Checkpoint

The previous pac-judge-node-family.md PAC remains valid; a PAC note for
this builder-lane change is appended to it after the proof (canonical goal
restated; trust boundary = builder agent invocation conversion; Judge and
release authority unchanged).
