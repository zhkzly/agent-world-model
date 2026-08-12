# Independent implementation check — second Direct format Feedback

- Decision: **allow**
- Reviewed plan digest: `sha256:85541065b75f17ec5509bb7cc7be2d61173365a7a58c414122f765e3345483a8`
- Matching critic record: `cross-layer-review-85541065b75f.md` (`Decision: allow`)
- Scope: only the supplied ordinal-two `GraphRunner` branch, its focused
  regressions, and the four bounded-correction wording updates.

## Evidence

- The SHA-256 of `direct-second-format-feedback-plan.md` exactly matches the
  reviewed digest. The latest `check.jsonl` entries point to the matching
  Diagnosis, plan, allow, and deterministic-results records.
- `DESIGN_NODES` has exactly two deployed Direct nodes with
  `local_corrections=2`: `tool_semantics` and `curriculum_plan`; `NodeSpec`
  still rejects that limit for Agent nodes.
- `GraphRunner._eligible_local_correction` changes only ordinal two. For a
  Direct node declared with two corrections, a prior
  `direct_response_not_json` packet admits proposal 3 for either a second
  format rejection or a safe parsed semantic rejection. A semantic-first
  format regression remains false, semantic distinct-progress comparison is
  retained, and ordinal 3 cannot satisfy the branch, so proposal 4 is
  unreachable.
- The real Direct path still obtains the format packet only from strict,
  unwrapped JSON-object parsing after a nonempty `finish_reason=stop` response
  in official SDK JSON-object mode. The rejected raw content remains only the
  immediately preceding in-memory assistant turn; it is not placed in the
  correction packet, ArtifactStore, WorkRecord, Finding, or Observe data.
- The canonical source, task design, node contracts, and debugging guide now
  agree on the same narrow format-first exception and semantic-first terminal
  rule. No helper, node, edge, configuration, route, provider, parser, or
  downstream ABI was added.

## Verification

- Tests: pass — `uv run pytest -q` over the 13 targeted state-machine and
  Direct-conversation regressions (`13 passed in 2.17s`). These cover both
  two-correction nodes, format-to-format, format-to-semantic,
  semantic-to-format, the three-proposal ceiling, default/Agent declaration
  compatibility, provider/postcompile terminals, immediately preceding
  ephemeral raw answers, actionable Feedback, and raw-output non-persistence.
- Lint: pass — scoped Ruff format/check for `agent_world/graph.py` and the two
  focused test modules.
- TypeCheck: pass — `uv run mypy agent_world/graph.py`.

## Findings (fixed)

None. No production, test, or specification file required an edit.

## Findings (not fixed)

None within the authorized scope.

## Files changed by this check

- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-second-format-feedback-implementation-check.md`
  (this record only).

## Explicit nonclaims

This static check does not run a real model or E2E proof. It does not prove
Luna repairs the frozen shard, a complete Design, Candidate, Integration,
Judge, Registry release, Direct E2E, Repair, Expand, or Consumer behavior.
