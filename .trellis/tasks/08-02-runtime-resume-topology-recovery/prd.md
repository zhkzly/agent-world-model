# Runtime resume & topology recovery redesign

## Goal

Make an already-committed generation closure **advanceable and recoverable** without re-running upstream work, so the pipeline can reach `judge.release_assurance` → `release` → `registry.publication` (the first-ever E2E to Registry) and so future runs can restart cheaply. Today, a fully-committed closure (including the first-ever passing verifier gate) **cannot** be pushed to release by either existing path:

- `run resume <request_id>` silently restarts from `research_acquisition` (recovery returns `None`).
- `test-descendant-node` toward `release_assurance` dies with `parent_commit_inactive`.

Both failures trace to one root: the redesigned scheduler-direct runtime bookkeeps committed work via **epoch + manifest topology identity**, but the resume path and the diagnostic-descendant path still assume the older flat-artifact / per-dispatch-fresh-topology model.

## Background (verified against current code)

### Defect 1 — Topology-identity fragmentation (release blocker)
- Input fingerprint = `sha256(sorted(ref.revision_id))` folded together with `manifest.graph_digest` on the child side (`agent_world/control/work.py:132-137`; `agent_world/control/work_scheduler.py:790-803`).
- "Active commit" = fingerprint-equality between the child's freshly-computed closure (manifest-digest-sensitive) and the parent head's stored fingerprint (`agent_world/control/work_store.py:719-817`).
- Every `test-descendant-node` re-derivation mints a **fresh unique `topology_id`** (`agent_world/control/test_node.py:4368, 4491, 4645, 4854, 6378, 6891`), which changes `graph_digest` (`agent_world/control/work_graph.py:1392-1415`), which changes every child fingerprint, which orphans prior commits made under the original manifest.
- Same gate blocks epoch retention (`agent_world/control/work_epoch.py:836-888`) and readiness/release (`agent_world/control/work_readiness.py:107-112, 185-192`).
- Symptom also surfaces as `test_descendant_target_ambiguous` (one public coordinate resolves to both the original and a derived manifest — `test_node.py:3288-3302`).

### Defect 2 — Resume recovery read/write contract gap
- Reader `_recover_direct_design_checkpoint` (`agent_world/controller.py:4250`) requires five flat typed refs (`design.evidence_graph/coverage_map/world_spec/environment_design/baseline_checkpoint`) in `snapshot.latest_artifact_refs`; returns `None` when absent (`controller.py:4288-4289`).
- Writer `_project_scheduler_outcome` (`controller.py:1333, 1357-1386`) only stores `control.work_graph_epoch` pointers + request/job/context refs — never the flat `design.*` artifacts.
- `None` → `resume_subject_ref = head.job_ref` (`controller.py:928-930`) → `_execute_direct_locked` builds a **fresh run** from the context root and re-runs from research.
- Already-persisted failed snapshots on disk contain only epoch pointers, so a writer-only fix cannot recover existing runs.

### Defect 3 — request_id → scope_id reverse-lookup gap
- `DirectJobHead` (`agent_world/control/direct_store.py:58`) has no `scope_id`; keyed by `sha256(request_id)`.
- Work-control heads key on `sha256(scope_id\0coordinate_key)` (`work_store.py:1342-1347`); scope discovery is full-scan.
- No stored index; the only bridge is the implicit convention `scope_id == job.job_id` (`direct_runner.py`, `app.py:339`). `run inspect` never surfaces scope_id (`app.py:198-238`).

### Refactor debt (adjacent, lower urgency)
- `test_node.py` (7221 lines): 8 near-duplicate diagnostic runners; the clone/mark/build skeleton is duplicated near-verbatim across 6 (`test_node.py:666, 1925, 4890, 5109, 5658, 6011, 6138, 6746`).
- Baseline: `tests/agent_world/test_test_node.py` = 2 failed / 61 passed; both failures are a workspace-authority boundary check at `work_runtime.py:713` (independent of skeleton duplication).

## Requirements

### R1 — Topology identity is stable across re-derivation (release unblocker)
- A committed node's commit MUST remain "active" when a descendant is dispatched under a re-derived manifest for the same scope closure, provided the underlying node definitions and input closure are unchanged.
- Reaching `release_assurance` from a committed closure (candidate_build + runtime_integration + verifier_bundle committed) MUST NOT fail with `parent_commit_inactive` solely due to a topology_id change.
- The chosen fix MUST keep dispatch (`resolve_inputs`) and epoch retention (`_require_retained_predecessor_commits`) consistent — both use the same activeness gate.

### R2 — Resume continues from the deepest committed checkpoint
- `run resume <request_id>` on a failed run whose design (and later) nodes are committed MUST resume WITHOUT re-running committed upstream nodes.
- The fix MUST recover runs whose snapshots are ALREADY on disk (epoch-pointer-only), i.e. work against historical failed snapshots.
- Resume MUST NOT fabricate success; if the committed closure is genuinely incomplete it resumes from the true frontier.

### R3 — request_id ↔ scope_id is resolvable without head-spelunking
- Given a `request_id`, the system MUST resolve its work-control `scope_id` through a first-class path (index or stored field), not by manual `job_ref` dereference convention.
- `run inspect <request_id>` SHOULD surface the resolved `scope_id`.

### R4 — Diagnostic tooling convergence (may be deferred to a child task)
- The clone/mark/build/assert skeleton duplicated across the 8 diagnostic runners SHOULD collapse into a shared `DiagnosticClonePipeline`, parameterized by: error-code prefix, coordinate-resolution callable, optional freeze callable, result-builder. The Descendant rework matrix stays divergent.

## Constraints
- Credentials NEVER enter tracked files; live config stays in gitignored `.agent-world-live/`, reads base_url/key from `OPENAI_BASE_URL`/`OPENAI_API_KEY`.
- No fake success; classify infra/transport vs design defect, and prompt vs code, before any change.
- Do NOT `git commit` without explicit user go-ahead.
- Refactor freely (no back-compat obligation) but explain every major change against the goal before coding.

## Acceptance Criteria
- [ ] AC1: From the committed closure (scope `generate-job:ed1038477c84b260c92baad4`), `release_assurance` dispatches without `parent_commit_inactive` (topology-stable re-derivation), OR a fresh full `generate` run reaches `release`/`publication` and produces a Registry entry.
- [ ] AC2: `run resume <request_id>` on a design-committed failed run resumes from the committed frontier (verified: does not re-dispatch a committed upstream node) and works on an already-on-disk failed snapshot.
- [ ] AC3: `run inspect <request_id>` reports the resolved `scope_id`; a documented first-class request_id→scope_id resolution exists.
- [ ] AC4: `pytest tests/agent_world/test_test_node.py` regresses no currently-passing test (baseline 61 pass); any newly-fixed behavior is covered by a test.
- [ ] AC5: At least one complete E2E generation reaches `registry.publication` end-to-end on luna, proving the release path executes (the ultimate goal that motivated this refactor).
- [ ] AC6 (if R4 in scope): `DiagnosticClonePipeline` absorbs the shared skeleton with zero net test regression.

## Notes
- The topology fix (R1) is the highest-value item: it is the actual release blocker for the diagnostic path AND the same activeness gate governs readiness. A fresh single-topology `generate` may reach release WITHOUT R1 (topology is stable within one run) — R1 makes cheap iteration/restart possible. This priority split should drive task decomposition.
- Related memory: `resume-recovery-epoch-flat-ref-mismatch`, `descendant-topology-parent-commit-inactive`, `test-node-cli-refactor-debt`, `resume-id-topology-missing-index`, `verifier-gate-first-pass-luna-guided`.
