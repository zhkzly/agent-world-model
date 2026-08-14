# Diagnosis Record 15: agent_response_not_json kills the run without bounded rework

Date: 2026-08-14 (session)
Trigger: e2e resume terminal `agent_response_not_json` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆).

## Evidence (verified)

- The design graph COMPLETED under the new gates: all 5 task_requirement
  shards passed (preview inv1, search inv1, submit inv3, track inv2,
  bounded inv1) and modeling_gate passed at 04:57:13. The Judge-gate repair
  is proven convergent on the real boundary.
- Candidate graph: node build_plan (agent, Codex backend, skill
  engineer-build-planning, local_corrections=1) failed at inv 1 with
  agent_response_not_json at 04:57:59 — exactly one attempt was recorded.
- Code path: CodexAgentBackend.invoke_json ->
  _json_object(output, "agent_response_not_json") (invocation.py:371)
  raises InvocationError(SafeFailure("agent_response_not_json",
  "rejected")); candidate.py _agent_json (1058-1061) converts ANY
  InvocationError into CandidateError(code, status, retryable); the node
  operation wraps it via _node_error (candidate.py:140-141) into
  NodeExecutionError WITHOUT a CorrectionPacket -> graph.execute's
  correction loop has nothing eligible -> the node fails immediately.
- Contrast: the Direct node equivalent direct_response_not_json IS
  correctable (design.py _direct_json raises DesignError with a
  CorrectionPacket; graph.py:877 handles it specially).
- build_plan passed in the 04:01-04:05 run with the same prompt, skill,
  route and model — the failure is a response-mode/parse transient, not a
  prompt/skill/design defect.

## Root cause

Retry-policy asymmetry: malformed structured output from a Direct LLM gets
bounded in-session rework; the identical failure class from a Codex Agent
is treated as correctable=False and aborts the whole run after one
attempt. The source-of-truth prescribes bounded same-session rework for
malformed structured output (designer/verifier/builder correction), and
the node already has local_corrections=1 and the correction-injection
mechanism (_agent_json appends the authorized packet, candidate.py
1031-1034) — only the conversion drops the packet.

## Five-lens status

1. Project Agent view — not implicated.
2. Effective Prompt/input — SUPPORTED as unchanged: same prompt/skill/
   route passed at 04:01; no deficiency evidenced.
3. Runtime Skill / Direct no-Skill — SUPPORTED as unchanged (same
   engineer-build-planning bundle digest path).
4. Code/execution boundary — SUPPORTED ROOT CAUSE: InvocationError ->
   CandidateError -> _node_error conversion drops correction authority
   (candidate.py:1058-1061, 140-141).
5. Feedback/observability — SUPPORTED gap: the agent receives no
   authorized correction packet for a parse failure, and the attempt
   record carries no remediation surface.

## Alternatives rejected

- Model/provider retry at the transport layer: the SDK turn succeeded; the
  OUTPUT was malformed — an in-session correction packet is the designed
  mechanism, not a new transport retry.
- Raising local_corrections: the node already has a correction budget; the
  packet is what is missing.

## Owner / boundary

Builder agent invocation conversion (candidate.py _agent_json); the
correction loop and budget stay framework-owned and unchanged.

## Smallest next proof

With the conversion fixed: pure `--resume` — the design graph is skipped
(frozen heads), build_plan re-runs; a malformed first response must yield
a correction_requested attempt and a second in-session attempt, and the
run proceeds to the next terminal honestly.

## What remains unknown

- Whether the transient repeats; whether later agent nodes hit the same
  class; Judge/registry outcomes remain unproven.
