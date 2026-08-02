# Implement — Runtime resume & topology recovery redesign

Parent task owns requirements + integration; work is split into 4 independently-verifiable children. Ordering (written here, not implied by tree): **R1 → (R2, R3 parallel) → R4**. R1 is the release unblocker and must land first; R4 has the largest surface and lands last.

## Child A — R1: stable topology_id (release unblocker) [FIRST]
Goal: re-derivation reproduces the same `graph_digest` so prior commits stay active.

- [ ] A1. Audit the 6 topology_id mint sites (`test_node.py:4368, 4491, 4645, 4854, 6378, 6891`) + any others; classify each as (i) base/passthrough dispatch or (ii) genuine semantic overlay.
- [ ] A2. For base/passthrough descendant dispatch (no overlay): reuse the ORIGINAL manifest's `topology_id` instead of minting a new one. Locate where the descendant path chooses/derives the manifest (`_load_frozen_descendant`, `test_node.py:3002-3077`) and thread the source manifest's topology_id through.
- [ ] A3. For genuine overlays: make `topology_id` a pure function of the overlay's semantic digest (already computed as `overlay_digest`), removing any dispatch/attempt/timestamp component. Same overlay content → same id.
- [ ] A4. Verify the ambiguity guard (`test_node.py:3288-3302`) still fires for real historical-vs-overlay collisions but no longer for benign passthrough re-derivation.
- [ ] A5. Unit test: two re-derivations of the same scope topology (base, and same-overlay) produce equal `graph_digest`; a different overlay differs.
- [ ] A6. Integration probe (real): from committed closure clone `test-node-20260802T033457Z-ee2fa5ec56bf` (scope `generate-job:ed1038477c84b260c92baad4`), dispatch `verifier_bundle` then `release_assurance` via `test-descendant-node`; assert NO `parent_commit_inactive`. Use `env OPENAI_BASE_URL=http://localhost:8317/v1 AGENT_WORLD_CONFIG=.agent-world-live/e2e-local8317/config.toml`.
- Validation: `pytest tests/agent_world/test_test_node.py -q` (no regression vs 61-pass) + A5 + A6.
- Rollback point: revert Child A leaves topology behavior unchanged.

## Child B — R2: resume recovery via epoch walk
Goal: `run resume` continues from committed frontier, incl. already-on-disk snapshots.

- [ ] B1. Add an epoch→typed-design-bundle reader helper: walk `WorkGraphEpoch.retained_commit_refs` → `WorkCommit.output_refs`/`consumer_refs` (`work.py:1359-1415`), filter to the 5 `design.*` types, resolve uniquely (prefer design-epoch node output). Reuse `work_epoch.py:895` / `test_node.py:5371-5420` patterns.
- [ ] B2. Rewrite `_recover_direct_design_checkpoint` (`controller.py:4250-4289`) to source the 5 typed refs from the epoch walk (using `design_epoch_ref`/`final_epoch_ref` present in `snapshot.latest_artifact_refs`) instead of flat `only()` scans. Keep the downstream uniqueness/binding/gate re-validation (`4302-4396`) unchanged.
- [ ] B3. Preserve `None` semantics for genuinely incomplete closures (missing design epoch/output) so resume-from-research stays correct.
- [ ] B4. Unit test with an epoch-pointer-only snapshot fixture → recovery returns a valid bundle; a bootstrap-only snapshot → returns None.
- [ ] B5. Integration (real): `run resume local8317-20260802-020338` on the design-committed failed run; assert it does NOT re-dispatch a committed upstream node (check work-control heads/events), resumes at the true frontier.
- Validation: `pytest tests/agent_world/test_controller*.py` (or nearest) + B4 + B5.

## Child C — R3: request_id ↔ scope_id first-class
- [ ] C1. Add `scope_id` field to `DirectJobHead` (`direct_store.py:58`), populated at run start from `job.job_id`.
- [ ] C2. Back-fill fallback: `inspect`/`resume` resolve scope_id for OLD heads lacking the field via `job_ref → EnvironmentJob.job_id`.
- [ ] C3. Surface `scope_id` in `DirectRunReader.inspect` output (`app.py:198-238`) and the `run inspect` CLI result.
- [ ] C4. Unit test: inspect surfaces scope_id for both new (stored) and old (fallback) heads.
- Validation: nearest direct-store/app tests + C4. Verify AC3.

## Child D — R4: DiagnosticClonePipeline convergence [LAST]
- [ ] D1. Extract `DiagnosticClonePipeline` from the shared skeleton (copy/mark/build/resolve-diagnostic-root/assert-marking), parameterized by error-prefix, coordinate-resolver, optional freeze, result-builder, clone-or-reuse mode, ancestor-assertion mode.
- [ ] D2. Migrate the 5 cloning runners (Descendant-callers: WorldPlan, TaskRequirement, Final, Successor + TestNodeRunner primitives) onto the pipeline; keep the Descendant rework matrix as the delegated execution engine.
- [ ] D3. Migrate the 3 reuse-source-root runners (TaskCurriculumJoin, PlanDerivedDesign, and the inner Descendant call).
- [ ] D4. Preserve every public CLI contract + result type; only internal skeleton collapses.
- [ ] D5. (Optional, if time) address the 2 baseline failures (`work_runtime.py:713` workspace-authority) if they intersect the pipeline; else leave as documented pre-existing.
- Validation: `pytest tests/agent_world/test_test_node.py -q` MUST stay ≥61 pass (zero net regression); add pipeline unit tests.

## Cross-child integration (parent) — AC5
- [ ] E1. After R1 lands: attempt the full advance from committed closure → `release_assurance` → `release` → `registry.publication`. If topology fix suffices, this is the first Registry entry.
- [ ] E2. If the diagnostic advance still can't cross (e.g. release nodes need production scheduler not descendant dispatch): run ONE fresh full `generate` on luna (single stable topology) to `registry.publication`. This satisfies AC5 regardless of R1's diagnostic-advance reach.
- [ ] E3. `registry list` shows the released package; verify AC1/AC5.

## Global validation commands
- `cd /home/kelong/pycodes/agent-world-model && .venv/bin/python -m pytest tests/agent_world/test_test_node.py -q`
- Real E2E env: `export AGENT_WORLD_CONFIG=.agent-world-live/e2e-local8317/config.toml OPENAI_BASE_URL=http://localhost:8317/v1`
- Filter all head/result inspection by exact target scope_id (known clone scope-pollution).

## Review gates
1. After Child A: R1 unit + real release_assurance dispatch proof → review before R2/R3.
2. After R2/R3: resume + inspect proofs → review.
3. After R4: full baseline green → review.
4. Parent: E2E to registry.publication → final review.

## Rollback points
- Each child is a separate revertible unit. R1 first (unblocker), R4 last (surface). Never `git commit` without explicit user go-ahead.
