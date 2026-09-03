# Git causal audit: S2 Goal sampling and generated checker removal

## Scope

This audit uses repository history and retained task records only. It does not
treat later memory summaries or design proposals as accepted authority.

## What the earlier Goal-first implementation actually did

- `dc1f12c` added immutable `AtomGoal`, `AllGoal`, `IfGoal`, `ForEachGoal`,
  selectors, reports and Task identity models.
- `89c2475` added one common `CompiledTaskChecker`. It recursively interpreted
  the four Goal shapes and delegated atomic/condition truth to a release-local
  `TaskSemantics` surface.
- `0718bf0` added deterministic `enumerate_blueprints(...)` from qualified
  `StartCase`, `CapabilitySpec`, `BindingCandidate`, `ConditionSpec` and
  `CompositionRule`; it did not ask an LLM to invent each Task.
- `227f1a9` added the public-only witness runner and argument provenance.
- `3465e93` exposed that pipeline as the core API.

The release-local `TaskSemantics` was a Python project with:

```text
start_cases(seed, limit)
inspect(instance_directory)
capabilities()
enumerate_bindings(capability_id, facts)
evaluate_atom(request)
evaluate_condition(request)
```

`54a88b3` introduced the Codex Semantics Author. `03c5ce4` added a separately
generated Native Verifier, and the Qualification runner compared their results
over real executions.

## Trellis plan evolution before the deletion

The archived task's latest text is not the only plan that governed this work.
Reading every PRD revision in Git order shows materially different definitions:

- `451a998` required constructive sampling. Graph candidates existed only after
  a refined public chain `tau*` executed successfully; Programmatic candidates
  existed only after their bounded public solution program executed
  successfully. Later acting-Agent trials measured public recoverability and
  empirical difficulty, explicitly not logical solvability.
- `71f1e2a` replaced that design with qualified Goal-first enumeration followed
  by a public witness search after candidate/checker freeze.
- `fc6456a` and `99c4b2f` restored grounded execution-first Candidate sampling:
  Graph and Programmatic discovery both had to execute real public tools and
  feed one common ephemeral Candidate boundary, while deterministic Goal
  compilation remained a baseline. The plan explicitly separated
  reachability proved by execution from meaning anchored to S1 Requirements.
- `6994f4c` again made Graph/Programmatic optional and promoted Direct
  Goal-first enumeration plus two fresh public witnesses as the sole required
  production route. This is the latest archived PRD, but not the earlier
  sampling/filtering plan the user was referring to.

The recovered user intent is therefore a two-stage core: sampling emits a
Candidate only after real public execution succeeds; filtering then evaluates
Good-Task validity/recoverability and corpus value. Goal shapes describe the
sampled Task semantics and are not a substitute for successful sampling.

## What failed and caused repeated repair

The architecture contained two release-specific generated semantic programs:
TaskSemantics and the mutually blind Native Verifier. Qualification compared
them across required effects, collateral, process, answer fields, bindings and
conditions. Real task records show repeated disagreements such as:

- required-effect failure incorrectly setting collateral failure;
- public condition sources exposing less than the condition implementation
  actually used;
- protected bindings whose public descriptors were ambiguous;
- answer/report fields present in one reader but not the other;
- generic floors requiring Goal shapes or challenge categories that were not
  naturally supported by a release.

These failures were real, but repairing generated reader A until it agreed with
generated reader B on one release created a release-local convergence loop and
an overfitting risk. The very large qualification/check matrix also delayed any
Task production.

The Goal path eventually did produce physical results after the matrix was
reduced: retained records report 42 candidates and 9 TaskPacks across Git,
SQLite and a post-freeze held-out maintenance release, including Atom,
ForEach and If. All remained unsupported when no release CompositionRule
existed. Therefore the deterministic Goal model/enumerator was not itself the
cause of zero Task output.

## What the user asked to delete

The user objected to adding environment-specific pressure tests and requiring
wrong-target, partial, collateral, wrong-answer, reverse-order and mutation
work for every Task regardless of applicability. Later, `d33012b` introduced a
new per-Candidate Codex-authored Checker, and `219d318` added 2,637 lines of
per-Task physical challenge machinery. `53aa27b` correctly reverted that
challenge commit.

## Where deletion exceeded the correction

- `c9c4564` replaced the controlled sampler with the one-by-one Direct sampler
  and deleted 9,484 lines, including ForEach/If and batch/corpus code. Its own
  task note says the intended correction was removal of per-Task pressure
  pipelines; deleting Goal shapes was broader than that cause.
- `6924dd6` then removed 17,528 lines of the old v1/v2 release,
  TaskSemantics/Verifier and Task Foundry stack because the new Direct path no
  longer referenced them. That zero-reference fact followed from the cut; it
  was not comparative evidence that free LLM proposals produced better Tasks.

## Final planning consequence after cross-environment probes

The history establishes which concepts survived the failed implementations,
but it does not authorize restoring their old producer:

- retain typed Atom/All/If/ForEach Goal data, one common evaluator,
  public-only fresh solving, structural identity and corpus separation;
- reuse the real Direct Responses function-tool loop for execution-first
  semantic discovery;
- replace the Direct terminal with a TaskDraft over actual public events, then
  let Host evidence and fresh replay decide whether a Candidate exists;
- do not restore deterministic Release-local TaskSemantics enumeration. The
  S1 diagnostic catalog is qualification evidence, not a complete TaskSpace;
- do not add a Tool Graph or random walk. The later four-environment probe
  showed schema-derived edges were neither sound nor complete.

The prohibited paths remain:

- a per-Task generated Checker;
- mandatory per-Task pressure suites;
- two arbitrary release-local generated semantic readers repaired against one
  another;
- the deleted v1/v2 package/reader/compatibility stack.

The current design resolves atomic and condition truth by requiring the
Sampling Agent to select actual public events and sources, after which the Host
freezes their observed answer/state evidence and freshly replays them through
the common evaluator. This conclusion supersedes the earlier deterministic
enumeration proposal recorded above.
