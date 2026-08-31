# S3 Execution Contract

## Initial contract (frozen)

- Goal: turn exact admitted S2 TaskPacks into trustworthy target-policy Episode evidence for S4.
- Invariant: one Host-owned public tool loop preserves complete healthy success/failure trajectories.
- Invariant: Task truth is evaluated only by the frozen checker after same-instance close/reopen.
- Invariant: reward is exactly 1.0, 0.0 or typed null with no protected-data leakage.
- Not doing: Task generation/readmission, retries, veRL/trainer code, services, registries or another Agent loop.
- Gold authority: the Git, SQLite and maintenance IDs in `research/input-readiness.md`.
- Acceptance: `PROJECT.md` S3 completion evidence plus this task's PRD/checklist.

## 追加

### 2026-08-31 — execution shape

- Chosen: decision-only, single-Episode PolicyDriver under one Host loop.
- Alternative rejected: driver-side invoke/loop or a provider registry.
- Reconsider only if a real S4 consumer cannot use the restricted decision seam.

### 2026-08-31 — retry and trainer scope

- Chosen: one attempt per rollout; no SDK/Host automatic retry and no veRL integration.
- Alternative rejected: preallocated attempt slots and trainer-shaped S3 schemas.
- Reconsider only after measured S4 evidence creates a separate accepted task.

### 2026-08-31 — baseline harness repair

- Chosen: point the S2 product-authority test to the canonical archived task and run pytest via `python -m`.
- Alternative rejected: exclude the stale harness tests from every checkpoint gate.
- Evidence: full collection/path failures while S2 task status is completed under the archive path.

### 2026-08-31 — CP1 ACCEPTED with one protocol violation

- Chosen: accept the contract code after 25 focused tests, full 392-test suite, Mypy/Ruff and four killed semantic mutants.
- Alternative rejected: replay a fake historical RED or rewrite already-green code solely to stage one.
- Violation: initial RED was ModuleNotFound import noise; CP2+ must first fail on a reachable behavioral assertion.

### 2026-08-31 — CP2 behavioral RED

- Chosen: existing `run_public_episode` must expose its retained public capture in failure details after one successful call followed by a policy defect.
- Alternative rejected: treating a missing `capture_public_episode` symbol or stub exception as RED.
- Evidence to overturn: an existing reachable API already returns the complete failed public prefix without implementation changes.

### 2026-08-31 — CP2 ACCEPTED after live and independent rework

- Chosen: one Host loop plus a single-use, decision-only Responses adapter; keep the existing S2 API as a strict success projection over the retained capture.
- Evidence: 37 focused tests, 425 full tests, locked Ruff/format/Mypy, a killed blank-terminal semantic mutant, and independent ACCEPTED review at HEAD `001992d3f53431aa8b0bad57a1f45d24c520ce36` with staged digest `04875ca55d7b49d5477a21d6542232758f8f320629bf0fc3e4e377ce0e10f581`.
- Live exit: Git Release `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`, TaskPack `242b298797d5dc9cdc558ebb74f59977a35033b113e84f2f1190890f746a48bc`, Task `81cb99623100f26c9e2ad19feac147a5a7dc26b6f707cbc2cf9781928e1b0b74`; four Responses turns continued across four real public tool observations and ended in a structured answer with usage retained on every turn.
- Rework retained: blank `output_text` beside calls, malformed/missing Responses output, actor-tools infrastructure ownership and generic driver-close naming were corrected before acceptance.
- Boundary: `DriverDecision.defect` remains limited to same-turn evidence defects; no hypothetical S4 failure hierarchy, retry, lifecycle, EpisodeRecord/View/Batch or veRL surface was added.

### 2026-08-31 — CP1/CP2 reopened: deletion before extension

- Chosen: revoke the design-level ACCEPTED verdicts and rework CP1 then CP2 before CP3; retain only original Episode/Policy/Reward requirements and behavior exercised by the current S2/S3 path.
- Alternative rejected: preserve fields, validation layers, public exceptions or ledgers because CP4/S4 might use them later.
- Evidence: frozen JSON fields are runtime `mappingproxy` values that fail the project's own JSON predicates; the S2 path calls `actor.tools()` twice; capture and `TraceEvent` are maintained as parallel mutable ledgers.
- Boundary: no package moves or new directories during deletion-first rework; directory changes require remaining post-deletion responsibilities, not the current flat file count.
- Order: CP1R valid RED, deletion, mutation, independent review and commit; then CP2R under the same gate. CP3 remains paused.

### 2026-08-31 — CP1R ACCEPTED

- Chosen: expose ordinary structural JSON snapshots and delete `checkpoint_id` plus the complete MappingProxy/frozen-array freeze/thaw implementation.
- Alternative rejected: keep nested read-only containers or checkpoint identity because a later trainer might use them.
- RED: the old values failed `is_json_value`/`is_json_object`, and the old PolicySpec still exposed the producer-less field through a reachable dataclass contract.
- Evidence: 58 focused and 427 full tests, locked Ruff/format/Mypy/lock checks, independent ACCEPTED review, and a mutation-license run that replaced JSON snapshotting with caller aliases and was killed by the alias test.
- Reviewed source: HEAD `5f5cc1191e90791424e1d4fb33627ec1ed8bd067`; pre-record diff digest `2ddfab4e8ebe354987054eefc774e919c2651c3c69d5015f0cc7350a6fbcae95`.
- Deletion: `episodes.py` 505 to 468 lines and the mechanical Responses consumer 866 to 865; production net `-38`, no replacement framework, package move or CP2/CP3 behavior.

### 2026-08-31 — CP2R ACCEPTED

- Chosen: one ToolSpec snapshot and validated catalog, PublicEpisodeCapture as the sole call ledger, and a pure legacy TraceEvent projection.
- Alternative rejected: keep caller-versus-actor divergence checks, adapter-side result ledger, parallel mutable trace, defect detail channel or provider self-attribution restriction for hypothetical consumers.
- RED: the existing legacy wrapper called `actor.tools()` after its trusted caller already supplied the snapshot, producing an exact reachable `2 != 1` failure.
- Evidence: 37 focused and 427 full tests, locked Ruff/format/Mypy/lock checks, two mutation licences for snapshot and dispatched-only trace bindings, independent ACCEPTED review, and the same live Responses Git episode with four provider turns/calls and complete usage.
- Live authority: Release `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`, TaskPack `242b298797d5dc9cdc558ebb74f59977a35033b113e84f2f1190890f746a48bc`, Task `81cb99623100f26c9e2ad19feac147a5a7dc26b6f707cbc2cf9781928e1b0b74`.
- Reviewed source: HEAD `758d734952a4c9f545ed639b5357ba98488cea46`; pre-record diff digest `ba55ed0459b651d84a3fa018cf30ff7642d67a29d8efb0663388fe048bdc7aa0`.
- Deletion: `public_agent.py` 865 to 836 lines; source/tests combined net `-68`; no replacement API, CP3 code, package move or directory split.

### 2026-08-31 — standalone lifecycle checkpoint deleted

- Chosen: merge lifecycle generalization into the first concrete consumer, exact `run_task_episode`, and renumber the remaining work to CP3 runtime, CP4 bundle, CP5 batch and CP6 frozen acceptance.
- Alternative rejected: retain a test-only callback lifecycle, `AttemptOutcome`, `EpisodeVerification` or separate attempt-evidence carrier until a later runtime consumes it.
- Scope deleted: TaskAssessment repair, loader union, generic supplied-evaluator seam and independent lifecycle checkpoint; EpisodeRecord directly binds request/policy/capture/latency/achieved lifecycle/checker/reward.
- Compatibility: existing S2 `run_public_attempt` and `ReloadEvidence/1` remain unchanged; the exact S3 Task runtime owns its concrete failure lifecycle.
- Review: independent plan review ACCEPTED after removing all positive `EpisodeAttemptEvidence`, CP7 and assessment.py remnants; plan diff net deletes about 190 lines and directory restructuring remains out of scope.

### 2026-08-31 — CP3 authority RED

- Chosen: an exact current If TaskPack reader must reject an invalid embedded branch pack before any policy use, even when the outer canonical identity is honestly recomputed.
- Alternative rejected: use a missing `episode_runtime` import or a not-implemented stub as RED.
- Evidence: a canonical outer If v3 document containing `atom-task-pack/999` currently reaches `read_task_pack_artifact` successfully; the focused test fails with `DID NOT RAISE`, not setup noise.
- Lifecycle baseline: the existing success-only `run_public_attempt` raises on a policy terminal before pre-close/reopen/checker; the new concrete `run_task_episode`, not the legacy wrapper, owns the corresponding green path.

### 2026-08-31 — CP3 ACCEPTED

- Chosen: one concrete `run_task_episode` and one direct EpisodeRecord over exact Atom/ForEach/If authority; no standalone lifecycle/checker/evidence carrier.
- Deterministic evidence: 45 focused and 452 full tests, locked Ruff/format/Mypy/lock checks, four mutation licences covering nested If authority, unchanged ReloadEvidence, lifecycle order and defect/reward precedence, and independent deletion-first ACCEPTED review.
- Reviewed source: HEAD `41623eaf37a9c4e80ca4be905ced2f86a0b7d4a9`; source/test diff digest `98f6e9eaa2110a6802d7b10ee12a37680f3fe32fdfe385a9a4b0a5d0cfc358fb`.
- SQLite physical exit: Release `64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87`; exact Atom `dc3991...`, ForEach `055a57...`, If `fc1080...`; Episode IDs `33172d3c...`/`e2f5da5d...`/`f25376ad...` produced real `1.0`, `0cf15159...` produced policy `0.0`, and `e5aa65a9...`/`3080e1a1...` produced provider/infrastructure null after full real close/reopen/checker.
- Git transfer exit: Release `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`, Atom pack `242b2987...`, Episode `f2b6d461...`, real reward `1.0` after the same nine-event lifecycle.
- Drift correction: the implementer reached about 990 production lines before adding tests; main paused it, required focused tests and deletion review, and independent review reduced the module to 936 lines while removing over-tight If/ForEach checks and duplicate checker-result state.
- Boundary: TaskAssessment, persistence, TrainingEpisodeView, batch, generic callbacks, directory/package changes and close-transport invention remain absent.

### 2026-08-31 — CP4 cross-binding RED

- Chosen: a cold-persistable EpisodeRecord must reject checker requests whose trace differs from the sole PublicEpisodeCapture ledger before any view can be trusted.
- Alternative rejected: use a missing bundle/view symbol or an unimplemented writer as RED.
- Evidence: a policy-failed Atom Record with one dispatched call currently accepts a checker trace changed to empty and recomputes a new valid Episode ID; the focused assertion fails with `DID NOT RAISE`.
- Projection boundary: TrainingEpisodeView has no independent identity or reader; it is derived only after the paired Record passes canonical and semantic validation.

### 2026-08-31 — CP4 ACCEPTED

- Chosen: one TrainingEpisodeView contract and exactly two bundle functions; paired reader reconstructs the full Record and returns only its newly derived view.
- Deterministic evidence: 46 focused and 476 full tests, locked Ruff/format/Mypy/lock checks, three mutation licences for checker binding, usage leakage and view reward truth, and independent deletion-first ACCEPTED review.
- Reviewed source: HEAD `616de09127e5324393062a5c133f802d4e7deccb`; source/test diff digest `892173f7f5cc403622c13f8d5bb0fdc0bedb2ae661292e2f659a32e30a9358bd`.
- Review rework: fresh-ID cold bundles carrying malformed Atom evaluation context/protected binding or If condition request were initially accepted; private reconstruction with existing checker constructors now rejects all four variants without a new public type.
- Physical/cold exit: exact SQLite Release `64fa07e1...` persisted and relocated success `f2f73822...`, policy failure `55999f67...`, provider abstain `2128424d...` and infrastructure abstain `8773a13b...`; paired cold reads reproduced exact public inputs/turns/rewards with usage/checker/lifecycle structurally absent.
- Boundary: public additions are only TrainingEpisodeView, `write_episode_bundle` and `read_episode_bundle`; no bundle class, view ID, view-only reader, Registry, transaction layer, S4 helper, batch or directory split.
