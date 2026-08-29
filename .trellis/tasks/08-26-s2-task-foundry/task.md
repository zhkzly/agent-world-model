# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher or fallback survives.
Invariant 2: Framework owns deterministic identities, execution and verdicts; Codex-authored release code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks, dictionary worlds or green tests alone.
Not doing now: do not implement later S2 checkpoints while the v2 release/Qualification boundary is incomplete.
Gold reference: the contrasting real SQLite and filesystem/Git releases and the held-out Need gates in `implement.md`.

## Current boundary

- B: mutually blind Qualification Verifier authoring is implemented.
- C1: actor, TaskSemantics and verifier share one canonical locked materializer.
- C2: exact Author inputs and three isolated runtimes bind one acyclic Core.
- C3 is active: run public physical cases, compare Semantics and Verifier axes/report values, then produce evidence.
- Failure-code strings are local diagnostics; cross-reader agreement covers the declared result axes and `report_values`.
- No Qualification receipt, Publication, Release, TaskPack or S2 completion claim exists yet.

## Deletion-first correction

- Deleted the model-only `agent_task_foundry` package and its tests because no production runtime consumed it.
- Deleted the standalone QualificationCaseSpec format; real case inputs will be recorded directly by the C3 runner/evidence writer.
- Deleted disabled Alignment Patrol code, agent card and tests.
- Deleted the brittle qualification-goal keyword blacklist and duplicate completion-confirmation contract.
- Future TaskDefinition, TaskPack, AdmissionPlan, assessment and corpus records may be implemented only together with their first executable Checkpoint E–G consumer.

## Current real C3 evidence

- Expected Semantics digest: `b368ab19bd726082c21d6b99d8f6b36aee27a34e04d4e44e0bd4c9f09815a29d`.
- Actor digest: `65ad8443b5a24ec908703d85404d61c8ab73c1aa6e9e4656788a187c139650ac`.
- Repaired TaskSemantics digest: `6d0d3df0a392b1b4deec60536f7bdf61291e284437ca639629819824bebf52f7`.
- Independent verifier digest: `eae4359a79a314c0a612ef1ce5ed74d0fc7bef5edc44df49c79cbacb5ad5adbf`.
- Current Core: `67e235dd516a462adaecbb63598f30e1c9b8109f5dec50763f303497d5fa27ac`.
- Real public positives pass for query, persisted state change with public read-back, and stable refusal.
- No-op query/state/refusal, wrong answer and missing-readback negatives agree on all result axes and report values.
- Repository lock, Ruff, format, Mypy, full Pytest and diff checks are green after the deletion.
