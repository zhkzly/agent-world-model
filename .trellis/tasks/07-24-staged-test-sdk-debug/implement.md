# T0 execution order

`docs/plans/staged-test-and-debug-plan.md` is authoritative.

1. T0: keep the already-passing harness tests as the fixed test bed; record the failed builtin-provider target as a configuration/SDK bad case and do not rerun it unchanged.
2. T0: verify the SDK's official thread-config behavior through documentation/official source; add a deterministic no-persistence/argv regression; change only the Codex SDK adapter and retain `InvocationBackend` as the sole pipeline boundary.
3. T0: run focused lint/type/test checks, rerun exactly the target coordinate, audit files without printing credential values, and report T0.
4. Only after that report, execute T0.5, then T1, T2, and T3 exactly as specified in the source plan. A larger code redesign is permitted only when the then-current bad-case classification and isolated evidence justify it.
