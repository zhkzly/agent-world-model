# Implement — R1 stable definition identity

Ordering: implement → unit test (AC1, AC3) → real probe (AC2).

## STATUS 2026-08-02: implemented + AC1/AC3 green + AC2 topology wall proven cleared
- Steps 1-6 done. Suite 62 pass / 2 fail (2 pre-existing work_runtime.py:713).
- AC2 real proof: reconciled re-derivation (manifest `5b20f664`, rev `361421a2`)
  binds ALL 21 committed nodes at byte-exact `definition_digest` (was 18/21 with
  3 mismatches before the fix). Dispatching `release_assurance` against it no
  longer raises `parent_commit_inactive` — candidate_build + runtime_integration
  are active. Remaining error is `ancestor_closure_missing: verifier_bundle=missing`
  = the verification clone never dispatched the verifier_bundle aggregator (NOT
  an R1 defect; verifier_bundle is NO-HEAD in this closure). Dispatching
  verifier_bundle then release_assurance is the closure-completion follow-up.

## Steps

- [x] 1. Add a definition-recovery helper (test_node.py) that, given `app` +
  `WorkCommit`/`WorkControlHead`, returns the exact committed WorkDefinition
  (recover the `control.work_definition` artifact whose `content_hash ==
  commit.definition_digest`, verifying work_id/coordinate/acceptance_digest).
  Reuse the pattern in `TestNodeRunner._definition_for_binding` (test_node.py:1432)
  and `WorkControlStore._require_commit_definition` (work_store.py:1266).

- [x] 2. Add `_reconcile_final_graph_with_committed(app, scope_id, graph,
  exclude_coordinates)` (test_node.py, near `_final_graph` at 6546): for each
  definition in `graph`, if `heads.read_head(coordinate)` is `committed` AND the
  coordinate is not in `exclude_coordinates`, replace it with the committed
  definition; else keep the fresh one. Re-compile via
  `GenerationWorkGraph.compile(reconciled_defs, mode=…, required_terminal_coordinates=…,
  groups=…, milestones=…)` matching the original graph's compile inputs. Return
  the reconciled graph.

- [x] 3. Apply reconciliation in `DiagnosticFinalNodeRunner.run`:
  - `base_final_graph` (test_node.py:6283): reconcile with `exclude=()` — pure
    passthrough must reproduce committed digests.
  - budget-override branches (6335 implementation_plan / 6345 verifier_intent_batch):
    reconcile with `exclude={overridden target coordinate}` so only the
    intended agent target keeps its fresh envelope; all other nodes reuse
    committed definitions.
  - Keep `target`/`effective_definition`/envelope assertions working against the
    reconciled graph.

- [x] 4. Guard: if a committed definition's recovery fails or is structurally
  incompatible with the compiled graph, raise a clear `TestNodeError`
  (`test_final_node_committed_definition_reuse_failed`) rather than silently
  falling back to the divergent fresh definition (no fake passthrough).

- [x] 5. AC1 unit test in `tests/agent_world/test_test_node.py`: construct or
  load a committed final closure; assert reconciled `base_final_graph` yields
  `definition_digest` equal to committed head digest for candidate_build,
  release_assurance, runtime_integration; assert a budget-override target
  differs.

- [x] 6. AC3: `cd /home/kelong/pycodes/agent-world-model &&
  .venv/bin/python -m pytest tests/agent_world/test_test_node.py -q` — must stay
  ≥61 pass (baseline 2 fail / 61 pass; the 2 fails are work_runtime.py:713
  workspace-authority, pre-existing/independent).

## Real probe (AC2) — run by main session after implement lands
- Env: `export AGENT_WORLD_CONFIG=.agent-world-live/e2e-local8317/config.toml
  OPENAI_BASE_URL=http://localhost:8317/v1`
- Re-derive final via test-final-node to runtime_integration on a FRESH clone of
  the committed closure, then dispatch `judge.release_assurance.judge_report`
  via `test-descendant-node` WITHOUT `--manifest-revision`; assert no
  `parent_commit_inactive` and no `test_descendant_target_ambiguous` for the
  passthrough. (release_assurance's own runtime dispatch error is out of R1
  scope — see prd Notes.)

## Constraints
- Do NOT edit `work_store.py` active-commit logic or `complete_generation_work_graph`.
- Do NOT `git commit`.
- Credentials never enter tracked files.
- Classify before changing: this is a code defect in the diagnostic re-derivation
  call site, not prompt and not model.

## Rollback
- Single revertible unit (the reconciliation helper + its 3 call sites). Reverting
  restores current re-derivation behavior.
