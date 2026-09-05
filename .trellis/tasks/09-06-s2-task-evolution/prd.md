# S2 Task Evolution — Complete Delivery PRD

## Task state and authority

This is the Trellis task for the user's requested complete implementation. It is currently `planning`, not an active or completed implementation. Creating these artifacts does not start workers or modify runtime contracts.

Parent: `08-26-foundry-paper-product`. This task has no staged child releases. Internal dependency ordering, commits and review checkpoints belong to one complete delivery and must not become requests for the user to approve a partial version.

Read `AGENTS.md`, `PROJECT.md` and `DECISIONS.md` first. `prd.md` defines requirements and acceptance; `design.md` preserves the full implementation specification; `implement.md` defines execution, validation and review. Existing product invariants remain binding. Changes to current task representation and verification are proposed by this task and must be explicitly reconciled with product/spec documents during authorized implementation, not silently overridden by the design.

## Goal

Improve the quality of tasks sampled from the already working Foundry environments. Increase genuine information/state dependencies and coherent business work, while preserving public solvability, real execution, fresh replay, deterministic verification, isolation and correct acceptance of supported alternative routes.

The objective is to improve tasks, not to make an acting model waste tool calls. Correct shorter solutions remain successful. Length is an assessment and corpus-selection property, never a public minimum-call requirement or an extra S3 reward.

## User requirements

- Use the working `s3-sft-trajectories` lineage, not an older default branch or a substitute environment.
- Deliver the complete algorithm, necessary shared-runtime adaptations, tests, CLI, real execution and reports. Do not stop after a prototype, one operator, a canary, or passing unit tests.
- Preserve the existing environment releases, historical artifacts and user modifications.
- Do not require the user to assemble disconnected modules or authorize the next internal checkpoint repeatedly after implementation has been authorized.
- Separate code completion, live validation and measured algorithm effects. Do not invent successful runs, force task-length targets, or guarantee an improvement before experiments.

## Baseline and inputs

- Repository: `zhkzly/agent-world-model`.
- Task base branch: `s3-sft-trajectories`.
- Planning source HEAD: `786e770811aecfbde904b9b251cf7b07a0eb06d1`.
- Reviewed code baseline: `e02595a4044419ae755f13f02e21237f1c935171`.
- Previously working code: `1a6d3421315fc1e1c07961b54f950814ea21d40c`.
- User-provided worktree: `/home/kelong/pycodes/foundry-s3-sft-trajectories`; verify it locally before use.

The full specification previously at `docs/plans/s2-task-evolution-implementation.md` is now this task's `design.md`, migrated without changing its content. The old path is a navigation stub, not a second maintained specification. Its September 5 design date is retained; this Trellis task was created September 6, 2026.

Real Release, TaskPack and Episode inputs must be resolved from existing manifests and verified identities. Paths written in reports are discovery hints, not evidence that the files exist in the implementing runtime. No new S1 generation may silently replace unavailable historical inputs.

## Complete required scope

| ID | Required capability | Acceptance evidence |
|---|---|---|
| R01 | Frozen intent and isolated Scout/Proposer, Witness, Extractor and independent solving | Actual public-input captures, immutable intent identities, leak and goal-shrinking rejection tests |
| R02 | O1 prerequisite, O2 object discovery and O3 related-outcome expansion | Implemented operators, feasible/infeasible tests, real proposals and per-operator outcomes |
| R03 | Qualified reset-only starts, full public execution and fresh replay | Start/release identities, real native observations, replay and persistence evidence |
| R04 | Bounded path-open result/necessary-process validation and public provenance | Explicit bindings and clause coverage; valid alternative-route and invalid-result tests |
| R05 | One task-validation semantics shared by S2, complexity probes and S3 | Same-capture parity tests, typed defects, post-reopen reward tests |
| R06 | Efficient profiles, fixed-budget probes, local dependency audits and short-route diagnosis feedback | Correct profile digests, probe budget/route records, E1/E2 evidence and matched-task results |
| R07 | Instance deduplication, semantic grouping, lineage and leakage-aware splits | Direct-ID/discovery distinction, paraphrase handling, family and split collision tests |
| R08 | Bounded recursive search, budget allocation, concurrency, recovery and complete failure accounting | Frozen schedules, resume/idempotency tests, budget enforcement and retained terminal records |
| R09 | Official TaskPack publication, disk reload and S3 consumption | Real S3 rollouts, close/reopen verification, local and relocated paired artifact reads |
| R10 | Working CLI, current-format readers, automated tests, real campaigns, comparisons and completion report | Actual commands, logs, output identities, comparison metrics and requirement-to-test traceability |

The precise contracts, supported assertion types, operator definitions, format changes, budgets and test IDs are in `design.md`, sections 2–14. They are required design details, not optional future work.

## Constraints

- No hidden setup, direct database mutation for task initialization, Scout-state reuse, or stitched traces presented as one fresh successful execution.
- No per-task Python Checker or Framework business-domain branch. Supported deterministic assertions are interpreted by one bounded kernel.
- Every acting role receives only its authorized public inputs. Hidden truth, parent answers, reference paths and target lengths stay out of those inputs.
- Keep five valid fresh admission runs and at least two passes. Infrastructure retries are bounded and separate; semantic failures are not retried until success.
- Keep S3 reward semantics `1 / 0 / null`. A known verifier dispute cannot be reclassified as useful task difficulty or an ordinary negative example.
- Do not disable provenance, snapshot or digest checks merely to make the new path run.
- Do not turn unsupported multi-solution, arithmetic or process semantics into hidden reference-answer constraints.
- Record all relevant costs, failed proposals, truncated runs and unresolved defects. Test fixtures do not establish real algorithm effectiveness.

## Out of scope

S4 model training; training the task generator; arbitrary executable parameter programs; unrestricted optimization or multi-solution tasks; cross-Release super-environments; arbitrary nested loops; proofs of a global shortest solution. These boundaries do not excuse omission of R01–R10.

## Acceptance criteria

### Implementation and integration

- [ ] R01–R10 are implemented, connected and mapped to code/tests, with no placeholder success path or unimplemented mandatory operator.
- [ ] All applicable tests in `design.md` section 13 exist and pass; lint/type/unit/integration results are recorded.
- [ ] Shared policy profiles, source validation, budgets, native-state bindings and artifact identities agree across producers and consumers.
- [ ] Current-format writers/readers and the explicit baseline seed-export path work without overwriting or silently relabelling historical artifacts.
- [ ] `doctor`, `run`, `resume`, `verify` and `compare` are real CLI entrypoints, not README-only commands.
- [ ] Default behavior and historical baseline remain auditable; new runtime changes have focused regression evidence.

### Real environment validation

- [ ] Real source manifests and Release identities are checked; missing credentials/inputs are reported as actual external blockers, not replaced by mocks.
- [ ] The configured automatic algorithm runs on at least three actual suitable Releases. Every proposal has a terminal record.
- [ ] O1/O2/O3 each produce real executed proposals and outcome reports; at least two operators publish tasks on distinct roots, and at least one family has an admitted second recursive expansion.
- [ ] Every selected TaskPack is read back from disk and consumed by the official S3 runtime for configured rollouts. Success, failure and null outcomes are all retained.
- [ ] All sealed artifacts pass local and relocated cold reads with matching identities, public projections and reward records.

### Independent evaluation and completion

- [ ] `direct_coverage`, `intent_direct`, `evolution_without_shortcut_feedback` and `evolution` comparisons use common environment/validation/reporting rules and account for all costs.
- [ ] Final independent probes are separate from selection/admission evidence. Task/family counts are not inflated by repeated rollout counts.
- [ ] Report `L_best_all`, protocol-bound `L_best_probe`, successful probe counts, truncation, dependency evidence, family coverage and failure causes.
- [ ] `completion-report.json` records `implementation_complete`, `live_validation_complete`, `evaluation_complete` and `effect_status` separately, with exact commits, commands and artifact IDs.
- [ ] The full delivery is not marked complete while mandatory live/evaluation evidence is absent. Honest external blockers remain explicit; effect status may be `improved`, `inconclusive` or `not_improved` according to actual evidence.

## Handoff

Implementation starts only when the implementing session is instructed to start this task and runs the repository's `task.py start`. After that authorization, execute the complete task under the Trellis workflow; do not ask for another approval at every internal checkpoint.

No code, worker, local active-task pointer, or live run is created by the planning-artifact commit itself.
