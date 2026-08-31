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
