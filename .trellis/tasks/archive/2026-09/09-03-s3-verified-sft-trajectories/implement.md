# S3 Verified SFT Trajectories — Implementation

## Checkpoint A — Freeze current contracts

- Add RED tests for `EpisodeRecord/3`, `TrainingEpisodeView/2` and
  `EpisodeBatchManifest/2` identities and exact key sets.
- Remove the stale Checker owner/format from current Episode leaf contracts.
- Add strict current-only readers; old checker-bound `/1` artifacts fail.
- Assert the training view is derived from its trusted record and cannot be
  independently trusted.

Exit: mutations of request, calls, observations, state, evaluation or reward
fail cold read; protected evidence cannot enter the training view.

## Checkpoint B — Execute one current TaskPack

- Resolve one Corpus member to its exact S1 Release and S2 TaskPack.
- Build one fresh `EpisodeRequest` and materialization.
- Use `capture_public_episode`; do not create another Agent loop.
- Close/reopen the same instance and evaluate with the current common Goal
  evaluator.
- Derive real success, policy failure and abstention outcomes.

Exercise representative Atom, All, If and ForEach TaskPacks using the same
production function. Tests may use scripted drivers only to force negative
branches; successful product evidence uses Luna and real Releases.

Exit: alternative valid paths pass without S2-trace equality; correct state
with an invalid/missing final answer is reward zero; a truth defect is null.

## Checkpoint C — Persist paired Episode artifacts

- Write one new Episode directory from an in-memory record.
- Derive `TrainingEpisodeView/2` rather than accepting caller-authored bytes.
- Immediately cold-read both files and recompute identity/projection.
- Reject symlinks, extra/missing files, non-canonical bytes and old formats.
- Copy bundles to a fresh root and cold-read again.

Exit: a consumer can read the training view without access to protected state,
and any trusted/public mismatch fails closed.

## Checkpoint D — Multi-Release batch and resume

- Strictly read the current 69-member CorpusManifest.
- Strictly read the S1 campaign mapping for all 20 Release roots.
- Enumerate exactly 552 deterministic request slots.
- Run with worker limit eight; write terminal slot records before fan-in.
- Resume only absent slots and rebuild the same ordered manifest/summary.
- Do not retry or replace semantic failures to meet a success quota.

Exit: serial/resumed/parallel fan-in gives the same request ordering and
identity for the same retained Episode results.

## Checkpoint E — Real Luna canary

Before the full cost-bearing run, execute one TaskPack of each existing Goal
shape through the finished production path. This is an execution preflight,
not completion evidence.

Validate:

- only public inputs reached Luna;
- calls reached real environment processes;
- close/reopen evaluation produced physical reward;
- one cold success view reconstructs complete ordered chat messages and tools;
- failures are attributed rather than patched into Agent prompts.

Any failure is first classified as upstream authority, Framework, policy,
provider, environment or evaluator before code changes.

## Checkpoint F — Full 552-Episode campaign

- Freeze source, prompt, route and configuration digests.
- Run all 69 TaskPacks × 8 rollout indices against Luna on localhost:8317.
- Require a terminal record for every slot.
- Build and cold-read the exact EpisodeBatchManifest and summary.
- Relocate and cold-read every Episode bundle.
- Report per-Task and aggregate success/failure/abstention, turns, tool calls,
  tokens, trajectory lengths, elapsed time and concurrency.
- Verify at least one success per TaskPack and success coverage across all 20
  Releases and all supported Goal/outcome categories; otherwise report the
  exact SFT-readiness failure without hidden refill.

Exit: immutable, non-leaking, SFT-ready public trajectory data exists for the
exact current corpus. This does not claim training improvement.

## Validation

```bash
uv sync --frozen --all-groups
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
git diff --check
```

Focused behavioral mutations must prove:

- reward `1.0`, `0.0` and `null` cannot be interchanged;
- protected/expected/S2 evidence injected into a training view is rejected;
- post-reopen state or an observation mutated under an old Episode ID fails;
- one missing or duplicate rollout slot fails the final manifest;
- old Checker-bound Episode artifacts fail without an adapter;
- a success cannot be created from a final answer or `ok=true` alone.

## Rollback points

- Commit after A, after B/C, after D, and after the real campaign.
- If current S2 primitives are insufficient, stop at the owning boundary and
  justify the smallest refactor; do not import the old S3 implementation.
- Do not change S1 Release or S2 TaskPack bytes, identities or admission logic.
