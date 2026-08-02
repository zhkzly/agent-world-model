# Design — Runtime resume & topology recovery redesign

## Decisions (user-confirmed)
- Release path: **fix R1 topology-identity first, then advance the existing committed closure** to `release_assurance`→`release`.
- R1 approach: **(b) stable `topology_id`** — derive `topology_id` from a scope-stable closure identity so re-derivation reproduces the same `graph_digest`; do NOT loosen the active-commit check.
- R4 (diagnostic runner convergence): **in scope this round**.

## Boundaries & contracts

### Core invariant we preserve
"Active commit" = fingerprint equality between the child's freshly-computed input closure and the parent head's stored `input_fingerprint` (`work_store.py:719-817`; `work.py:132-137`). We do NOT change this rule. Instead we make the *inputs to the rule* stable across re-derivation.

### C1 — Topology identity (R1)
- **Root:** `graph_id`/`graph_digest` = sha256 over `scope_id, topology_id, mode, node_bindings, group_bindings, milestone_bindings, required_terminal_coordinates, external_root_refs` (`work_graph.py:1392-1415`). `topology_id` is a free input that dominates identity.
- **Defect:** diagnostic re-derivation mints per-dispatch-unique `topology_id`s (`test_node.py:4368, 4491, 4645, 4854, 6378, 6891`), each changing `graph_digest`, orphaning prior commits.
- **Fix (b):** replace per-dispatch-unique topology ids with a **deterministic function of the stable closure identity** (the node_bindings/definition digests + overlay kind, NOT a random/timestamp/attempt suffix). Two re-derivations of the same logical topology for the same scope MUST produce the same `topology_id` → same `graph_digest` → same child fingerprints → prior commits stay active.
- **Overlay differentiation:** genuine overlays (runtime-implementation refresh, profile change, proposal-budget change, terminal-feedback) legitimately DIFFER from the base topology and SHOULD keep a distinct id — but that id must be a pure function of the overlay's semantic content (the overlay digest already computed), not of dispatch identity. Base/passthrough descendant dispatch (no overlay) MUST reuse the ORIGINAL manifest's topology_id, not mint a new one.
- **Ambiguity guard (`test_node.py:3288-3302`):** once base dispatch reuses the original topology_id, a public coordinate resolves to one stable identity for the passthrough case; the derived-overlay case remains explicitly disambiguated by `--manifest-revision`. Verify the guard still protects genuine historical-vs-overlay collisions.

### C2 — Resume recovery (R2)
- **Fix the READER, not the writer** (already-on-disk failed snapshots contain only epoch pointers; a writer fix cannot recover them).
- Change `_recover_direct_design_checkpoint` (`controller.py:4250`) to resolve the five typed `design.*` refs by walking `snapshot` epoch pointers → `WorkGraphEpoch.retained_commit_refs` → `WorkCommit.output_refs`/`consumer_refs` (`work.py:1359-1415`), filtering by artifact_type, then continue with the existing uniqueness/binding/gate re-validation (`controller.py:4302-4396`) unchanged.
- Prefer the `design`/`final` epoch pointers already present in `latest_artifact_refs`. Add a small helper (e.g. in controller or a shared epoch-reader) that returns the flattened typed design bundle from an epoch ref; reuse existing traversal patterns (`work_epoch.py:895`, `test_node.py:5371-5420`).
- Keep the `None` return semantics for genuinely incomplete closures (no design epoch / missing typed output) → resume from research is then correct, not a bug.

### C3 — request_id ↔ scope_id (R3)
- Bridge is currently the implicit convention `scope_id == job.job_id`. Make it first-class with the lowest-risk option:
  - **Option chosen:** add `scope_id` to `DirectJobHead` (`direct_store.py:58`) populated at run start from `job.job_id` (single source of truth), AND expose it in `DirectRunReader.inspect` (`app.py:198-238`) output. This avoids a separate index file and its consistency burden.
  - Back-fill: `inspect`/`resume` MUST still resolve scope_id for OLD heads lacking the field, by falling back to `job_ref → EnvironmentJob.job_id` (the existing convention). New heads store it directly.
- No new on-disk index structure unless the back-fill fallback proves insufficient.

### C4 — Diagnostic runner convergence (R4)
- Introduce `DiagnosticClonePipeline` absorbing the shared skeleton: resolve-source-root → new-diagnostic-root → copy-state-root → mark-clone → build-app → resolve-diagnostic-root → assert-marking.
- Parameterize by: (1) error-code prefix, (2) coordinate-resolution callable, (3) optional freeze callable, (4) result-builder, (5) clone-or-reuse mode (5 runners clone, 3 reuse source root), (6) ancestor-assertion mode (`allow_diagnostic_ancestor_closure`).
- **Keep divergent:** the `DiagnosticDescendantNodeRunner` rework matrix (infra retry / semantic repair authorize+execute / terminal-feedback / runtime-refresh / profile change mutually-exclusive guards, `test_node.py:1997-2066`) is genuinely distinct — it stays as the shared execution engine the pipeline delegates INTO, not something the pipeline absorbs.
- The 8 runners keep their public CLI contracts and result types; only their internal skeleton collapses.

## Data flow (release advance, post-R1)
```
committed closure (scope ed1038477c, original manifest topology_id T0)
  → test-descendant-node verifier_bundle  [re-derivation now reuses T0 → graph_digest stable]
      → parent (batch checkpoint) fingerprint matches → committed  ✓ (already worked)
  → test-descendant-node release_assurance [re-derivation reuses T0]
      → parents candidate_build + runtime_integration + verifier_bundle fingerprints match → ACTIVE ✓ (R1 fix)
      → release_assurance executes (code node, 900s, container eval)
  → release.observability_closure → release.package → registry.publication
```

## Tradeoffs & risks
- **R1 (b) risk:** if any legitimate consumer RELIES on per-dispatch-unique topology ids (e.g. to keep two diagnostic experiments from colliding), making them deterministic could cause two distinct experiments to share identity. Mitigation: the id is a function of overlay semantic content, so genuinely-different overlays still differ; only byte-identical re-derivations collapse (which is the goal). Must audit each of the 6 mint sites.
- **R2 risk:** the epoch-walk must reproduce the exact uniqueness guarantee `only()` gave; if an epoch retains two commits producing the same artifact_type, resolve deterministically (prefer the design-epoch's own node output). Covered by re-validation gate.
- **R4 risk:** highest regression surface (8 runners). Mitigation: land R1/R2/R3 first with tests green, then R4 as pure internal refactor with the 61-pass baseline as the gate.
- **Compatibility:** user waived back-compat; but old on-disk heads/snapshots must still be readable (back-fill fallback in C3, epoch-walk in C2 works on existing data).

## Rollout / rollback shape
- Each child is independently revertible. R1 is the release unblocker and lands first. R2/R3 are independent. R4 lands last (largest surface, zero-behavior-change goal).
- Rollback point after each child: full `pytest tests/agent_world/` subset + the targeted E2E probe for that child.

## Test strategy
- R1: unit test that two re-derivations of the same scope topology produce equal `graph_digest`; integration probe = dispatch release_assurance from the committed closure without `parent_commit_inactive`.
- R2: unit test `_recover_direct_design_checkpoint` returns a bundle from an epoch-pointer-only snapshot fixture; integration = `run resume` on a design-committed failed run does not re-dispatch a committed node.
- R3: unit test inspect surfaces scope_id for both new (field) and old (fallback) heads.
- R4: the existing 61-pass baseline is the regression gate; add pipeline-level unit tests.
- E2E (AC5): one full luna generate to `registry.publication`.
