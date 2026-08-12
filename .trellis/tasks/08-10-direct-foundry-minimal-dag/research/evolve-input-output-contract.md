# Minimum Expand contract — semantic evolution with optional multi-parent code

This is the contract for the immediate Expand child. It is not implemented by
the current Direct task and is not a generic evolution platform.

## 1. Campaign start

Framework receives a small `CampaignRequest`:

```text
anchor: optional exact package refs, request anchor, or released Pool selector
direction: bounded capability / tool / workflow targets and optional weights
source_specs: permitted technical-document URL/query targets
operator_allowlist: ToolSurface | ToolSemantics | TransitionConstraint | TaskScope | Composite
policy_id: directed@1
seed: campaign seed
budget: source/model/candidate limits
release_profile_ref: normal independent release policy
```

The request contains no parent source tree, free-form Agent control prompt,
release verdict or training requirement.

## 2. Frozen snapshot

Framework resolves once and persists:

```text
exact eligible released parent package refs and safe semantic/contract refs
frozen Pool/source/operator revisions
materialized source requests and target dimensions
seed, policy id, budget leases and release profile
optional aggregate capability feedback projection (priority only)
```

Unreleased, superseded or quarantined packages cannot be parents. Policy and
Designer do not receive credentials, sealed data, evaluator internals, mutable
Registry state or writable parent code.

## 3. Evidence source

```text
SourceRequest
  -> framework Search / Fetch / Extract
  -> bounded Researcher Codex Agent synthesis
  -> framework-validated SourceResult / clue refs
```

The Researcher sees bounded parent semantics and acquired document text in an
ephemeral workspace. It proposes only evidence-backed capability/tool/workflow
clues. It cannot select parents, write candidate code, define a Gate or publish.

## 4. Policy and operator

The stable policy interface is:

```text
ask(frozen_context, checkpoint, budget) -> MutationIntentBatch
tell(checkpoint, CandidateOutcome[]) -> PolicyCheckpoint
should_stop(checkpoint, remaining_budget) -> StopDecision
```

`directed@1` is the first deterministic implementation. A MutationIntent may
select one or several exact parent refs, clue refs, one allowed operator,
bounded parameters and target dimensions. Framework admission rechecks release
eligibility, catalog membership, dedup, permissions and budget.

Policy chooses; it does not merge source code. Operator expresses the bounded
semantic change; it does not produce a trusted child object or source files.

## 5. Complete child Design

Designer is a Direct LLM work over safe parent semantic projections, admitted
clues and the mutation intent. It proposes a complete semantic source draft,
not a patch to parent code. Framework compiles one complete child Design and
computes the authoritative `SemanticDelta` from compiled parent/child facts.

```text
SemanticDelta:
  operator and subjects
  exact parent semantic refs / before digests
  changed tool/world/task aspects
  evidence refs
  same-package revision or new-package identity result
```

An empty semantic delta cannot be reported as successful Expand merely because
files changed.

## 6. Builder-only parent source access

Only after the complete child Design is committed:

1. Framework resolves each selected exact package digest again.
2. It verifies release status and the package/source-tree digest.
3. It materializes only the candidate source closure and applicable dependency/
   license metadata into a separate read-only parent root.
4. Builder gives those roots, the frozen child Design and advisories to the one
   CandidateBuild Agent.
5. CandidateBuild writes one new child workspace. It may reuse, adapt, combine
   or replace parent code; no framework file-merger guesses how to resolve
   semantic or dependency conflicts.
6. Framework scans the final source closure and computes all physical facts.

Parent evaluator code, sealed cases, Judge traces, credentials, Registry writer
and release internals are never mounted. The final child contains all required
code and cannot import or fetch a mutable parent at runtime.

## 7. Separate lineage

```text
SemanticLineage:
  exact parent package refs + semantic delta refs

ImplementationLineage:
  exact parent package/source-tree digests + final source-tree digest
  + bounded reuse/adapt/rewrite facts derived from physical closure
```

These answer different questions. Neither carries an inherited Judge pass. The
result is one ordinary self-contained child package, not an EnvironmentFamily
or composite runtime.

The first live E2E uses one parent. The schema is plural and deterministic tests
mount at least two parent roots read-only; a later real multi-parent E2E must
prove actual useful composition.

## 8. Shared candidate core and policy result

```text
compiled child Design + validated lineage + verified parent source roots
  -> advisory Engineer / Challenger Agents
  -> CandidateBuild Agent
  -> framework source scan
  -> isolated Integration
  -> independent Judge
  -> Registry release or honest non-release
  -> CandidateOutcome
```

`CandidateOutcome` contains durable multi-objective facts: hard-gate/release
status, semantic/coverage/diversity descriptors, fidelity/risk, cost, repair
depth, lineage and package ref when released. Optional aggregate training
metrics may be included as priority data. Policy cannot alter release facts.

## 9. Execution taxonomy

| Work | Kind |
| --- | --- |
| snapshot, policy, admission, operator, lineage, outcome, Observe | framework |
| search/fetch/extract | framework tools |
| evidence synthesis | Researcher Codex Agent |
| complete semantic design | Direct LLM + framework compiler |
| planning/challenge/build | Codex Agent works inside owners |
| source scan/integration/judge/release | framework + isolated candidate process |

## 10. Training boundary

Training does not participate in this contract. A separate Consumer loads exact
released child or parent packages later. Removing training adapters leaves the
Campaign unchanged; any aggregate capability feedback is optional and never
evidence or a release gate.
