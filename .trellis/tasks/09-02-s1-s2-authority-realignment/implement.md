# S1/S2 Authority Realignment — Implementation Plan

## 1. Execution rules

- Planning approval does not authorize implementation until `task.py start` is
  explicitly approved after the final summary.
- Create a dedicated branch/worktree from `ef9aad8` before product edits.
- Implement in the main/inline session as previously requested; use an
  independent Trellis check worker only after the user approves this plan and
  only at the named review gates.
- Work RED-first with mutation evidence for every new authority edge.
- Every checkpoint ends with deterministic checks, a semantic-drift review,
  production-reference grep, LOC report and commit before the next checkpoint.
- No checkpoint may add compatibility, a feature flag, a second public API, a
  generic workflow engine or domain-specific Framework behavior.
- Real physical acceptance is required before any completion claim.

## 2. Checkpoint A — Product authority and v3 contract RED

### Work

1. Update `PROJECT.md` to the approved S1/S2 authority boundary.
2. Update only the owning backend specs; mark old v2 semantic-authority text
   superseded rather than maintaining parallel current contracts.
3. Add RED tests for the exact EnvironmentRelease/3 descriptor and payload:
   actor project, public/state factories, start/reset/state schemas,
   conformance receipt, payload manifest and no Task bytes.
4. Add negative tests proving v2 semantics/verifier fields and roots are
   rejected rather than ignored.
5. Freeze the public/protected access matrix and identity preimage.

### Exit

- Stable docs contain one non-contradictory authority model.
- v3 parser/publication tests are RED for missing implementation and kill a
  mutant that accepts a semantics/verifier field.
- No production behavior has switched yet.

### Expected files

```text
PROJECT.md
.trellis/spec/backend/s1-coordinator.md
.trellis/spec/backend/v3-preparation.md
.trellis/spec/backend/v3-conformance-publication.md
tests/test_release_v3.py
tests/test_product_authority.py
```

## 3. Checkpoint B — Environment state readback and conformance

### Work

1. Extend the actor development contract with fixed protected `read_state` and
   `docs/schemas/state.json` deliverables.
2. Implement Host validation and an isolated `StateSnapshotProxy`:
   schema validation, deterministic repeat, close/reopen stability and
   instance-tree no-mutation.
3. Implement minimal `EnvironmentConformanceReceipt` and physical evidence for
   actor/source/lock/test/public schemas/reset/replay/isolation/readback.
4. Add one real generated-project boundary exercise; do not use it as a Release
   yet.

### Exit

- A real actor project exposes public tools and protected task-neutral state.
- Public policy input contains no state snapshot/factory/path.
- Readback mutation, schema drift and reopen drift each fail a focused test and
  mutation.
- No Task, capability, answer or reward contract has entered S1.

### Expected files

```text
src/agent_env_foundry/environment.py
src/agent_env_foundry/builder.py
src/agent_env_foundry/state_snapshot.py (only if separation is clearer)
src/agent_env_foundry/runtime_skills/environment-codegen/*
tests/test_builder.py
tests/test_environment_contract.py
tests/test_state_snapshot.py
```

## 4. Checkpoint C — Atomic EnvironmentRelease/3 and S1 cutover

### Work

1. Implement v3 descriptor, publication, verification, ZIP and cold reader.
2. Replace `prepare_release` with actor + protected snapshot materialization.
3. Replace `generate_environment_v2` with the sole v3 S1 order:

   ```text
   Need -> Research -> Builder -> public/state surface
        -> environment conformance -> publication -> ZIP -> cold prepare
   ```

4. Atomically remove S1 Expected Semantics, TaskSemantics Author, Native
   Auditor and task-case Qualification calls from the public path.
5. Delete old v2 reader/conversion/fixture authority in the same cutover.

### Exit

- A failed Task concept cannot block or revoke S1 publication.
- v2 packages fail as unsupported; no dual reader exists.
- Cold v3 Release opens from a relocated directory with public/protected
  separation.
- Old S1 semantic-authority production references are zero.

### Expected files

```text
src/agent_env_foundry/generation.py
src/agent_env_foundry/release.py
src/agent_env_foundry/preparation.py
src/agent_env_foundry/project_identity.py
tests/test_generation.py
tests/test_release_v3.py
tests/test_preparation.py
tests/v3_release_factory.py
```

## 5. Checkpoint D — Real S1 physical acceptance

### Work

1. Generate one filesystem/Git and one SQLite/stateful environment from fresh
   Needs using the single v3 API.
2. Run real tool calls, mutations/refusals, snapshot comparisons, close/reopen,
   ZIP relocation and cold preparation.
3. Preserve failed attempts and exact owner attribution.
4. Independently review for mock/canned state, schema lies, public snapshot
   leakage and Development-Brief drift.

### Exit

- Two contrasting cold EnvironmentReleases exist with exact IDs.
- One deliberately broken environment fails before publication.
- S1 completion is demonstrated without any Task/checker/verifier generation.

### Rollback point

Commit the complete S1 v3 boundary before beginning S2 work. If this checkpoint
fails, fix S1 or revise the approved design; do not start S2 scaffolding.

## 6. Checkpoint E — S2 CandidateTaskContract and checker authority

### Work

1. Define one versioned TaskContract and isolated checker project/factory over
   before/after state, public trace and final answer.
2. Implement a Direct proposal Agent that uses Need/Brief, public tools and one
   real exploration to propose a candidate; it cannot seal truth.
3. Implement the checker-author workspace and Host-owned identity/checks.
4. Freeze TaskContract, checker and instruction before witness execution.
5. Ensure a checker correction creates a new candidate version; no admitted
   contract or witness result can be edited in place.

### Exit

- One real v3 Release produces one frozen Task candidate and checker.
- Checker identity excludes witness, assessment and corpus results.
- No release-local CapabilitySpec/evaluate_atom API is used.
- A witness or challenger cannot see protected state, checker source or proposal
  trace.

### Expected files

```text
src/agent_env_foundry/task_contract.py
src/agent_env_foundry/checker_author.py
src/agent_env_foundry/task_foundry.py (rewrite, not adapter)
src/agent_env_foundry/runtime_skills/task-checker-codegen/*
tests/test_task_contract.py
tests/test_checker_author.py
tests/test_task_foundry.py
```

## 7. Checkpoint F — Physical Task admission and retained S2 product

### Work

1. Execute checker challenges against proposal evidence, no-op, wrong answer,
   wrong target, partial and collateral cases when physically constructible.
2. Run two fresh public-only witnesses on fresh starts after freeze.
3. Close/reopen and execute the frozen checker against real snapshots.
4. Seal TaskPack, TaskAssessment and CorpusManifest using retained identity
   separation and honest rejection attribution.
5. Reject bad Task candidates without mutating or invalidating the Release.

### Exit

- Each contrasting v3 Release admits at least one real TaskPack or produces a
  typed per-Task abstention without release failure.
- A deliberately wrong checker and unsolved instruction are rejected.
- Alternative valid execution is not rejected for trace inequality.
- Existing public Agent and assessment code is reused, not forked.

## 8. Checkpoint G — Deletion closure and held-out proof

### Work

1. Delete obsolete S1/S2 semantic-authority modules, runtime Skills, fixtures,
   tests and docs after their last consumer moves.
2. Grep for old semantics/verifier factories, v2 roots, `TrustedProxy`, sealed
   capability/start/task-goal fields and compatibility language.
3. Run a post-freeze held-out Need through S1 v3 and S2 Direct with no domain
   edits.
4. Run independent cross-layer/semantic review and publish exact LOC/deletion
   evidence.

### Exit

- Old production references are zero and old formats fail closed.
- Net production code growth is explained; obsolete authority deletion exceeds
  replacement compatibility code (which must remain zero).
- Held-out Release and Task evidence cold-verify after relocation.
- Current task can be marked complete only after real execution evidence.

## 9. Validation commands

At every checkpoint, use the applicable focused commands plus:

```bash
uv lock --check
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen mypy src
uv run --frozen python -m pytest -q
git diff --check
```

Mutation evidence is issued per changed authority file. Real acceptance commands
and artifact IDs are added when the v3 public APIs exist; a fake provider cannot
satisfy Checkpoints D, F or G.

## 10. Review questions at every checkpoint

1. Does this change serve the approved S1/S2 authority, or revive old semantics
   under another name?
2. Is a deterministic Framework responsibility being handed to an Agent?
3. Is an open semantic judgment being hard-coded into Framework or a domain
   branch?
4. Can the acting policy see protected truth or proposal/witness leakage?
5. Does one failed Task affect only that Task?
6. Did code/tests/docs delete the superseded authority instead of wrapping it?
7. What real physical execution proves the checkpoint, and what remains
   unproven?
