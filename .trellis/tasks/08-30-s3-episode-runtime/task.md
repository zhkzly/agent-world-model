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
