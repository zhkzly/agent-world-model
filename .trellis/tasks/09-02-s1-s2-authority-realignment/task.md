# Initial contract (frozen)
Goal: clean-break S1 environment publication from S2 Task truth and deliver real v3 Release→Task evidence.
Invariant: S1 publishes executable actor/state truth only; no Task/checker/reward authority.
Invariant: S2 has one sealed TaskContract/checker authority; challenges only reject.
Invariant: all completion claims require cold real execution, not mocks or unit-test green.
Not doing: no compatibility, dual reader, generic workflow/verifier DSL, domain branches, S3/S4 work or gate weakening.
Gold evidence: stopped campaign `bb0645b2...` (8 terminals/0 Release) and retained real Release/Product IDs in the parent evidence task.

## Append-only decisions

- 2026-09-02 Checkpoint A: selected an exact internal EnvironmentRelease/3 descriptor/path/identity contract while the public v2 API remains untouched until atomic cutover. Alternative: edit `release.py` public behavior immediately. Reversal evidence: the internal contract cannot be integrated without a second public reader or materially duplicates final publication logic.
- 2026-09-02 Checkpoint A: current S1 v2 preparation/qualification specs were deleted and replaced by sole v3 environment-only specs; they were not retained as deprecated current guidance. Alternative: keep both document generations. Reversal evidence: an active consumer still requires the old task-case publication authority before Checkpoint C.
- 2026-09-02 Checkpoint B: selected one protected `read_state` entrypoint inside the frozen actor project, validated by a separate stdlib child and Host proxy; no second state-author project exists. Alternative: independent readback project. Reversal evidence: actor-owned readback cannot expose persistent truth without circularly calling public business methods or cannot be kept physically hidden from policies.
- 2026-09-02 Checkpoint B: the first real purchase-order actor passed its own five tests but a Host invocation exposed a success-schema mismatch. The general Builder method now requires every public tool to execute and validate a complete envelope against its ToolSpec; a fresh repair produced digest `8534db6f...e1b8d`, six tests and physical refusal/mutation/reopen/snapshot closure. Alternative: patch the purchase-order schema manually. Reversal evidence: held-out actors continue producing unobserved schema lies despite complying with the complete matrix requirement.
