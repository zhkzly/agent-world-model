# Staged live test and SDK routing debug

## Goal

Execute [`docs/plans/staged-test-and-debug-plan.md`](../../../docs/plans/staged-test-and-debug-plan.md) as the debugging protocol for natural-language need through Registry release. The plan is the sole behavioral source of truth; this task records execution status only.

The required order is T0 → T0.5 → T1 (BC-44 → BC-14 → BC-17 → BC-47) → T2 → T3. Each phase produces its minimum report before the next begins. T0, T0.5, BC-44, and BC-14 are complete; the current phase is T1 / BC-17 physical batch sizing and frozen-context progress.

## Requirements

- Preserve the plan's redlines: real executable environment logic, actual target execution through `InvocationBackend.invoke()`, no target replay, no credential/base-URL values in files/artifacts/traces/manifests, and no fabricated success.
- Keep agentic work on `CodexSdkBackend` / `openai_codex.AsyncCodex`; do not begin T0.5 or route agentic nodes through the OpenAI SDK.
- Every failure is first classified with the plan's bad-case table. The observed provider-routing failure is an infrastructure/configuration bad case, not a semantic-node failure.
- Use official SDK/documentation or official-source evidence before changing the invocation adapter; retain only safe, reproducible evidence.
- A broad structural refactor is allowed when the current phase's single-node evidence establishes it as the causal repair. It must not weaken gates, increase retry ceilings, bypass isolation, or reorder the staged protocol.
- Stop after each phase's minimum report. T0.5, T1, T2, and T3 require their stated preceding evidence.

## Acceptance Criteria

- [x] T0 test-node harness has deterministic tests proving it supersedes only the target coordinate, dispatches it once, validates ancestor closure, and stays diagnostic-only/non-releasable.
- [x] The configured real `test-node` target runs through `InvocationBackend` and produces an honest bounded terminal result after a causal routing compatibility change.
- [x] A credential audit finds zero API-key/base-URL value matches in the resulting test-node root and derived evidence.
- [x] A T0 minimal report records scope/target, model/profile digest, safe terminal evidence, usage/unknowns, redline audit, and stop reason; no later phase is started in the same report.
- [x] T0.5 keeps all calls behind `InvocationBackend`, proves fail-closed
  agentic/direct routing with deterministic tests, and records one fresh
  Direct single-node execution without a replay or credential/base-URL leak.
- [ ] Subsequent phases follow the source plan's exact sequence and per-phase evidence/report gates; final success remains a real `Registry released`, not a fixture or replay result.

## Notes

- The prior broad feedback-control-plane task remains the parent. This child is the active debugging execution record.
