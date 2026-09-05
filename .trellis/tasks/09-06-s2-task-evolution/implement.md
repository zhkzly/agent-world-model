# S2 Task Evolution — Execution and Verification Plan

## One complete delivery

Active task when explicitly started: `.trellis/tasks/09-06-s2-task-evolution`.

This plan implements the entire PRD and `design.md` R01–R10. The dependency order below is an internal execution order, not multiple product versions or independent user sign-offs. A worker's done event, a single canary, or an intermediate commit is not final task completion.

Worker context order follows `.trellis/workflow.md`: curated JSONL -> `prd.md` -> `design.md` -> `implement.md`. JSONL lists specs only; workers read source and tests during execution. If the environment truncates a planning artifact, read its remaining sections before acting; do not implement only the injected prefix.

## Activation and baseline protection

On the user's implementation instruction, use the existing task rather than creating another one:

```bash
TASK=.trellis/tasks/09-06-s2-task-evolution
python3 .trellis/scripts/task.py validate "$TASK"
python3 .trellis/scripts/task.py start "$TASK"
python3 .trellis/scripts/task.py current --source
```

The task is delivered in `planning`. Do not write another session's active-task pointer from GitHub. If the local session has no identity, follow `task.py start` diagnostics and record the routing result rather than claiming a pointer was persisted.

Before code edits:

1. Confirm the actual checkout, branch, HEAD and dirty paths. The specified source lineage is `s3-sft-trajectories`, not old `main`.
2. Verify the user-provided worktree exists locally. Preserve unrelated edits and all historical Release/TaskPack/Episode data.
3. Record the baseline commit and existing test results. If a new implementation branch is created, derive it from the confirmed source branch and update task branch metadata; do not invent that a branch already exists.
4. Resolve genuine manifests and credentials through existing configuration, checking actual IDs. Missing external inputs block the corresponding real validation, not all independently possible coding work.
5. Keep the original baseline available read-only for old-format regression/seed export. Do not use `reset --hard`, mass cleanup, or destructive format conversion.

## Dependency order inside the same task

### Shared contracts and execution foundation

Read the existing implementation before editing. Relevant sources include `task_proposal.py`, `task_draft.py`, `task_candidate.py`, `task_goal.py`, `task_admission.py`, `public_agent.py`, `episodes.py`, `preparation_v3.py`, `episode_runtime_v2.py`, `episode_artifacts.py`, source/batch modules, and S2/S3 campaign scripts.

Implement the frozen intent/start/profile/binding contracts and current-format identity plan. Reconcile intentional representation changes with `PROJECT.md`, `DECISIONS.md` and the affected backend specs; preserve the PRD's product invariants.

Connect the bounded result-verification kernel and the shared `evaluate_public_completion` semantics. Implement real clause coverage, public/native entity binding, public provenance, necessary process timing, and unrelated-state protection. No always-true reviewer, guessed same-value binding, or per-environment checker shortcut is permitted.

Integrate role-specific Host profiles while preserving prompt/capture/PolicySpec digest agreement. Resolve the Witness answer-schema cycle using the design's fixed witness terminal protocol and later evidence extraction, not by leaking expected answers.

### Full algorithm and official consumers

Connect O1, O2 and O3 to the same fresh execution, replay and admission pipeline. Maintain separate Scout, Witness, Extractor and independent-solver contexts. Add qualified starts, short-route diagnosis feedback, deduplication, semantic/leakage groups, matched-task construction, fixed-budget probes, dependency evidence, bounded recursive frontier and complete terminal accounting.

Implement concurrency with frozen scheduling and recovery. Never treat a reused half-modified instance as a fresh attempt or rerun model failures until success.

Adapt all official TaskPack/Corpus and Episode writers/readers and S3 entrypoints to the current shared validation. Preserve reward responsibility and real close/reopen checks. Baseline import is an explicit public-seed export, not a second silent production truth path.

Implement the CLI and manifests from `design.md` section 12, including `doctor`, `run`, `resume`, `verify`, and `compare`. Do not leave the user a set of disconnected Python APIs to wire together.

### Continuous real integration, then full evaluation

Exercise real TaskPack publication, disk reload, official S3 execution and paired cold read as soon as the relevant path exists, and repeat after shared-contract changes. These are regression checkpoints within the full delivery, not permission to stop after one case.

Run the configured bounded campaign on real existing Releases. Account for every proposal and require the PRD's operator/recursion/cross-environment evidence. Then freeze the corpus and run the independent evaluation and all four comparison strategies. Selection probes are not final independent results.

A valid shorter solution remains successful and updates assessment; a verifier dispute stops use of that candidate as complexity evidence until resolved. Never enforce a target call count in the instruction or reward.

## Validation commands

From the verified repository root, record actual commands, exit codes and logs. Use the repository's locked dependencies; do not upgrade them to avoid diagnosing a regression.

```bash
uv sync --frozen --group dev
uv run ruff check src tests scripts
uv run mypy src
uv run pytest
python3 .trellis/scripts/task.py validate .trellis/tasks/09-06-s2-task-evolution
```

Some current checks may expose pre-existing issues. Record the baseline, distinguish new regressions, and do not silently weaken tests or suppress errors to produce a green report. The source checkout's configuration remains authoritative for exact tooling options.

After the new CLI has actually been implemented, execute the design's commands with verified actual paths:

```bash
uv run python scripts/run_s2_task_evolution.py doctor --config CONFIG.json
uv run python scripts/run_s2_task_evolution.py run --config RESOLVED.json
uv run python scripts/run_s2_task_evolution.py resume --campaign-root ROOT
uv run python scripts/run_s2_task_evolution.py verify --campaign-root ROOT --relocation-root NEW_ROOT
uv run python scripts/run_s2_task_evolution.py compare --config COMPARE.json
```

`CONFIG.json`, `RESOLVED.json`, `ROOT`, `NEW_ROOT` and `COMPARE.json` are placeholders in this plan, not claimed existing files. The final report must replace them with exact executed commands and verified artifacts. Resume must be tested after a controlled interruption and on an already completed job set; no duplicate execution of completed jobs is acceptable.

## Required test and evidence coverage

Implement the complete test matrix in `design.md` section 13, not just selected happy paths. Map R01–R10 to their actual source symbols, test IDs and real artifact records in the completion report.

Particular integration traps requiring explicit evidence:

- The fixed instruction reaches the acting session unchanged and cannot be replaced by a smaller post-hoc task.
- Witness does not know parent/scout-only IDs; Extractor cannot execute new calls to repair missing evidence.
- The same healthy public capture has consistent S2/probe/S3 provenance and task verdicts.
- Efficient prompts are genuinely used and correctly identified; tool-call budgets are enforced before dispatch.
- Discovery tasks are not discarded by the old state/Goal-only structure key, while paraphrases do not become new families.
- Legal alternative read/write routes pass supported semantics; wrong entities, omitted outcomes and unintended effects fail.
- Dynamic created IDs bind to actual business facts rather than reference-run IDs.
- Public task/episode views exclude hidden truth and admission/probe/reference material.
- Writers and readers agree after serialization; relocation does not depend on source caches or in-memory objects.
- No-success probes remain null length; they are not classified as an infinite or demonstrated necessary horizon.

## Trellis worker coordination and review

Use the repository's channel-worker workflow when available. The main session owns integration and final acceptance. Worker briefs must specify this one task, editable scope, forbidden actions, exact validation targets and expected evidence. Workers may own bounded code areas internally, but a worker completion must not be reported as completion of the full task.

Use `implement.jsonl` and `check.jsonl` with `prd.md`, `design.md`, and `implement.md` in the documented order. Inspect precise worker output via `trellis channel messages --raw`; do not rely only on truncated dashboards.

An independent check pass must inspect code, actual tests, current-format compatibility boundaries, public/trusted projections, operator behavior, recovery, and the report's claims against retained evidence. Deterministic verification failure cannot be overridden by an LLM review conclusion.

## Change scope and rollback

Runtime scope is the Foundry package, its scripts/tests, and directly affected task/product/spec documentation. Do not modify unrelated project features, rewrite Trellis tooling, alter user credentials or change existing Release bytes to make a candidate pass.

Use focused commits or equivalent auditable change sets so a newly introduced regression can be isolated. Roll back only owned changes with preservation of user work; do not reset shared history or rewrite completed campaign artifacts. Contract repairs require a new verification version and applicable re-evaluation rather than in-place relabelling.

If an actor lacks a required business capability, retain the public counterexample and a GapRecord. Do not expand the entire S1 system opportunistically or silently replace the fixed-environment comparison. Still implement all required generic capabilities; do not use `RepresentationBlocked` as a substitute for unwritten code.

## Final delivery and stop rules

Deliver committed code and tests, synchronized current contracts, actual CLI commands, manifest/artifact identities, full live/cold-read evidence, independent comparisons and `completion-report.json` as specified in design section 14.4.

Report separately:

```text
implementation_complete
live_validation_complete
evaluation_complete
effect_status
unresolved_defects
external_blockers
```

Only the full acceptance criteria authorize task completion. A successful script exit, canary, single operator, object skeleton, or mock-only test suite does not. Do not ask the user to authorize the next internal checkpoint after the complete task has been started.

External missing files, credentials or service availability must be stated precisely, with remaining work and a working recovery entrypoint. Do not claim those checks ran, invent task statistics, or mark the task completed while required acceptance is missing. Algorithm effects may be inconclusive even after a fully implemented and honestly evaluated system.

Once all task-completion conditions are satisfied, follow the repository's finish/update-spec/commit/archive workflow. Do not run it merely because planning artifacts have been written.
