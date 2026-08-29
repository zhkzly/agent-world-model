# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher or fallback survives.
Invariant 2: Framework owns deterministic identities, execution and verdicts; Codex-authored release code never self-authorizes.
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

## Contract reclosure after independent BLOCK

- Three independent reviewers agreed that `9ba397b` is a genuine v2-only base but blocked further implementation because Qualification depended on a not-yet-known Release ID and no independent native truth producer existed.
- Selected: derive an internal Core ID before Qualification, add one mutually blind qualification-only verifier project, then seal the passed receipt into the final Release ID.
- Selected: replace cross-run protected bindings with logical binding plans and run-local resolutions; add exact public value sources and bounded selected-sibling evaluation context.
- Rejected: weaken independence to TaskSemantics self-agreement, restore the deleted v1 Qualifier, add a provisional package, or create a universal State/SQL/effect DSL.
- Implementation remains paused until the amended PROJECT/PRD/design/implement/spec package passes a fresh independent review and receives subsequent user approval.

## Re-review result

- Identity/native-truth reviewer: `ALLOW`; Core → evidence → receipt → Release is acyclic and the mutually blind verifier is independently executable.
- Full-S2 reviewer: `ALLOW`; sealed manifests, qualified StartCases, logical selection/rebinding, event-level provenance, fresh episodes and pre-witness AdmissionPlan close the release → TaskPack → corpus chain.
- Overdesign/guidance reviewer: `ALLOW`; additions are bounded Host-derived records, not new lifecycles, DSLs, services or public runtimes; stale active S1/v1 guidance was removed.
- Repository validation after reclosure: Trellis context valid, 277 tests green, Ruff/format/Mypy/lock/diff checks green.
- Next authorized implementation boundary, after user approval: Checkpoint A contracts/decoders/tests only; no author run, Qualification, Publication or S2 execution claim.
