# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher or fallback survives.
Invariant 2: Framework owns deterministic identities, execution and verdicts; Codex authors actor and TaskSemantics code only.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks, dictionary worlds or green tests alone.
Not doing now: do not implement later S2 checkpoints while the v2 release/Qualification boundary is incomplete.
Gold reference: the contrasting real SQLite and filesystem/Git releases and the held-out Need gates in `implement.md`.

## Current execution boundary

- Selected: delete the entire v1 publication/Qualification/loader/CLI path and its positive fixtures before adding new v2 behavior.
- Rejected: retain a compatibility shim or reuse old Qualification artifacts to accelerate a nominal green path.
- Reconsider only if a current v2 consumer requires a physical primitive that cannot be expressed without an old semantic authority; no such evidence currently exists.
- Preserve only version-neutral physical assets that have a live v2 consumer, such as deterministic tree manifests and locked two-runtime preparation.
- After the deletion baseline is green, implement native v2 Qualification and Publication before S2 compiler/witness/admission.

## Evidence

- Deleted 12,000+ lines of v1 production code, positive fixtures, tests and stale active guidance; no compatibility adapter or fallback was added.
- Preserved tree-manifest integrity as a version-neutral v2 preparation primitive and killed a constant-digest mutant with the real trusted-mutation tests.
- Focused physical tests, 277 full tests, Ruff, format, Mypy, lock and zero-reference checks pass; this establishes only the clean v2 foundation.
