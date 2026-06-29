# Executable verifier feedback workflow

## Goal

Turn generated-environment implementation into an executable workflow, not a one-shot prompt or a domain-specific patch.

The project goal is an Agent-World-like environment generation system. A user gives a need, capability gap, source packet, repo, CLI/API/MCP/docs seed, or raw request; the system should produce a reproducible executable environment package with runtime/state code, tasks, tools, deterministic verifier, replay/check evidence, release metadata, and downstream training/eval consumer entrypoints. Code agents such as Codex CLI/SDK may implement and repair generated environment code, but they are workflow nodes, not workflow controllers.

This task strengthens the code-agent implementation loop:

```text
accepted generation artifacts
-> code-agent workspace packet
-> generated candidate files
-> framework-owned executable candidate check
-> structured failure observation
-> bounded code-agent repair
-> final independent verifier gate
-> package/release only if verified
```

The intended shape is explicitly multi-layer workflow:

- Outer workflow: S0-S11 request/source/spec/task/surface/verifier/package/release pipeline.
- Middle workflow: code-agent implementation and bounded repair attempts.
- Inner workflow: framework-owned executable verifier/check loop that returns observations like tool-call results.

These layers must stay separate. The agent can operate inside the middle workflow, but it cannot own the outer pipeline or the final release decision.

## Background

The current project already has S0-S11 staged pipeline artifacts, generated environment bundles, agent-backed implementation, runner workspaces, independent verifier strategies, package-relative generated runtime output, and bounded repair attempts.

The latest real `codex_cli_runner` smoke proved the runner path is wired and observable, but it failed before release. The framework correctly blocked release at the independent verifier. The remaining gap is not "no feedback"; the gap is that verifier feedback is not yet a first-class executable workflow contract:

- The runner packet contains natural-language replay expectations, but not a machine-readable replay/check contract.
- Generated `check_replay.py` can produce stdout/stderr, but it is agent-authored and cannot be release authority.
- Framework independent verifier executes generated code, but exception feedback is mostly exception type/message rather than case/call/traceback/expected/actual observations.
- Repair packets carry useful summaries, but not a full framework-owned observation that a code agent can treat like a tool-call result.

## Requirements

1. Preserve the project-level boundary: this is environment generation infrastructure, not a booking-only fix, not AWM reproduction, not trainer integration, and not a direct dependency on one agent backend.
2. Add a machine-readable replay/check contract to the code-agent workspace packet. The contract must describe the environment id, runtime entrypoint, constructor, helpers, required methods, verifier kwargs, trace contract, required bundle files, manifest kind mapping, and accepted replay cases.
3. Add a framework-owned candidate check/preflight mechanism that can be executed against generated files and returns a JSON-compatible observation. It must run generated code enough to catch runtime/verifier failures, not just lint or schema-check files.
4. Improve independent verifier failure evidence so failures can be fed back to a code agent as repair input. Observations should include failure class, task/case id when known, phase/call when known, traceback when an exception is thrown, and expected/actual evidence when a deterministic assertion fails.
5. Feed the structured observation into bounded repair packets without leaking secrets or absolute local workspace paths as candidate paths.
6. Keep final release authority inside the framework. Generated `check_replay.py`, runner self-report, and Codex stdout are supporting evidence only.
7. Keep the design extensible: use a stable observation/contract envelope with pluggable domain-specific replay cases instead of one hardcoded universal booking schema.
8. Preserve existing `support-desk-lite`, `project-board-lite`, `booking-service-lite`, `library-lending-lite`, and `awm` CLI regressions.
9. Use `uv` for Python validation commands.

## Acceptance Criteria

- [x] Runner workspaces contain `input/framework-replay-contract.json` or equivalently named machine-readable contract file.
- [x] The contract is generated from existing artifacts and verifier strategy knowledge, not hand-authored per run by the agent.
- [x] The contract uses a stable top-level schema/envelope and domain-specific replay cases for current supported generated environments.
- [x] A framework-owned check/preflight entrypoint can evaluate a candidate bundle and return JSON-compatible success/failure observation.
- [x] Independent verifier reports include structured observations for prerequisite failures, task replay failures, deterministic expected/actual mismatches, and Python exceptions with traceback.
- [x] Repair packets include the framework-owned observation so the next Codex/code-agent attempt receives actionable feedback.
- [x] A failing generated booking or project-board candidate produces feedback that identifies the failed task/case/call instead of only a generic release failure.
- [x] A forged generated `check_replay.py` success remains rejected by the framework.
- [x] Existing deterministic generated bundle success paths still pass.
- [x] `uv run pytest tests/agent_world` passes before commit.

## Out Of Scope

- Do not implement real trainer loops, GPU/Ray/vLLM/SGLang, verl integration, or policy rollout.
- Do not make Codex SDK/CLI a core dependency. Keep agent invocation behind `AgentBackend`.
- Do not implement arbitrary-domain verifier synthesis in this task. Current supported replay strategies can remain registered strategies, but their contract/observation envelope must be reusable.
- Do not replace the S0-S11 pipeline with an agent-controlled workflow.
- Do not trust generated `check_replay.py` or runner stdout as the release authority.
