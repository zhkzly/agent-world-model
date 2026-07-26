# World Rules E2E Diagnostic Fidelity

## Goal

Drive the staged real E2E path toward a trustworthy terminal result, starting at the
`world_rules` node. Every repair must be justified by isolated, deterministic evidence;
the real `test-node` execution is the integration oracle, not a sampling mechanism.

## Background

- The parent staged-test task remains governed by
  [`docs/plans/staged-test-and-debug-plan.md`](../../../docs/plans/staged-test-and-debug-plan.md).
- The handoff document
  [`docs/plans/handoff-world-rules-diagnostic-fidelity.md`](../../../docs/plans/handoff-world-rules-diagnostic-fidelity.md)
  establishes a concrete initial hypothesis: proposal-owned `world_rules` validation can
  throw bare `ValueError`, which `one_shot` intentionally collapses to the non-actionable
  `framework_diagnostic_incomplete` fallback.
- The captured `t2-probe-2` evidence reports `world_rules` as a completed proposal-semantic
  failure (`validation_failed`), rather than proving a provider hang. This is a starting
  fact to revalidate against the current head before selecting a repair.

## Requirements

- R1. Use the staged E2E/test-node workflow as the authoritative integration test. Do not
  repeatedly re-run an unchanged coordinate to sample for a different outcome.
- R2. Before any real rerun, classify the current terminal evidence and isolate one failing
  node, validator, or transport boundary. State the causal change that makes the next run
  meaningfully different.
- R2a. The first diagnosis question for every failure is which owning layer is defective:
  (1) prompt definition, (2) Agent Skill/capability guidance, (3) deterministic code or
  contract, or (4) feedback/observability fidelity. Do not assume a code patch is the
  answer merely because the E2E result failed; a substantial refactor is allowed when the
  isolated evidence proves code ownership.
- R3. When a proposal-semantic failure lacks a stable safe code, precise path, violated
  condition, or expected category, treat the weak feedback as the defect to repair before
  attempting another semantic retry.
- R4. Preserve deterministic validation and all release/isolation/repair-budget gates. No
  prompt expansion, retry increase, validator relaxation, artifact injection, fixture/replay
  success path, or model fallback may be used to make the E2E path appear successful.
- R5. Migrate only the exact diagnostic boundaries established by current evidence. The
  handoff's remaining `world_rules` bare-`ValueError` inventory is an initial worklist, not
  a substitute for confirming ownership and reproducibility at the current head.
- R6. Typed diagnostics crossing the Agent boundary must use stable codes and precise
  source-facing paths and must never echo Agent-provided values, credentials, provider
  transcripts, sealed data, or raw proposal payloads.
- R7. For each code change, first add or update a direct deterministic failing-to-passing
  test for the exact validator/compiler boundary. Run focused tests before re-running the
  affected real node.
- R7a. A node may enter a wider E2E path only after its isolated contract passes. The sole
  exception is a demonstrated feedback-fidelity defect: repair and test the feedback
  boundary first, then repeat the same isolated node to obtain actionable evidence. Do not
  chain partially understood failures together.
- R7b. A refactor is permitted, and preferred over an incremental patch, when isolated
  evidence shows the current contract/ownership boundary is structurally wrong. Do not
  preserve a design merely because it already exists.
- R7c. Construct or adapt minimal valid typed inputs for node-level tests, then poison only
  the target field or condition. Never run upstream Research/Design merely to obtain a test
  input, and never depend on retaining a rejected provider payload to reproduce a validator
  failure.
- R7d. Once one isolated failure proves a defect pattern, inventory every same-owner,
  same-boundary occurrence before returning to E2E. Prove each member locally; do not leave
  homologous defects behind merely because the first example now passes.
- R8. After a repaired node has deterministic evidence, run only that `test-node` target.
  Interpret its terminal `ValidationReport`, telemetry, frontier issue samples, and
  observability scene before selecting the next repair. Continue this loop only while
  there is strict causal progress; stop at an external/authority-required blocker.
- R9. Keep changes within the `agent_world/` slice and route all model execution through
  `InvocationBackend` / the existing isolated backend adapter.

## Acceptance Criteria

- [x] AC1: The current `world_rules` target is classified from durable E2E evidence before
  implementation; the task records the exact coordinate, terminal category, and chosen
  single-node boundary.
- [x] AC2: Each repaired proposal-owned validation failure reaches the structured-output
  boundary as a typed, safe, source-addressable diagnostic rather than an opaque generic
  fallback.
- [x] AC3: Framework-owned invariant failures remain explicitly non-actionable and safe;
  they are not routed to an Agent as semantic repair work.
- [x] AC4: Each changed boundary has direct deterministic failing-to-passing coverage,
  including code/path/actionability and no-Agent-value disclosure assertions.
- [x] AC5: Focused and relevant regression tests pass, without weakening the existing
  bare-`ValueError` fail-closed fallback behavior for truly untyped framework errors.
- [x] AC6: A fresh, isolated real `test-node` run is performed only after deterministic
  evidence passes. Its outcome is honestly recorded: a passed/released progression, a
  next typed single-node failure, or a bounded external blocker.
- [x] AC7: No secrets, endpoint values, raw provider transcripts, or sealed data appear in
  tracked artifacts, telemetry, test output retained by the task, or source changes.
- [x] AC8: Every repair report records the four-way ownership decision (prompt, Skill, code,
  feedback), the single-point proof, and the explicit causal reason for any subsequent
  E2E/test-node execution.
- [x] AC9: Node-level regressions use constructed or fixture-derived valid inputs and change
  only the target condition; no broad pipeline run is used as a substitute for a unit-level
  reproduction.
- [x] AC10: For every confirmed defect pattern, the task records the complete same-boundary
  inventory and has direct coverage for every member before the next E2E integration run.

## Out of Scope

- Rewriting the whole E2E pipeline based on one trace.
- Changing the five known catch-all fallback sites or unrelated Judge/Builder paths without
  new, node-local evidence.
- Treating a test-node diagnostic execution as releasable or publishing a package from it.
- Provider per-turn timeout and orphan-running-head recovery work unless a subsequent
  isolated run proves either is the active blocker and scope is explicitly expanded.

## Notes

- This is a complex task: `design.md` and `implement.md` are required before activation.
- The user's instruction to modify the system authorizes implementation after the planning
  artifacts capture these constraints; it does not authorize commits or pushes.
