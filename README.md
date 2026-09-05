# agent-env-foundry

Implementation of the Canonical Agent Environment Foundry (see `PROJECT.md`).

The implemented branch uses `EnvironmentRelease/3`: an immutable executable
actor with public tools and protected task-neutral state readback. The Direct
S2 sampler executes public actions, materializes and replays task evidence,
filters candidates through five fresh public policy runs, and publishes
checker-free TaskPacks. S3 consumes the frozen artifacts, records real tool-use
Episodes, reopens persistent state, and emits verified public training views.
The retained campaigns and claim boundaries are documented under `experiments/`.

No demo, mock, canned artifact, unit-test result, or code-shaped placeholder
constitutes a released environment or a completed live campaign. Product
intent, stage boundaries, and working rules live in `PROJECT.md`,
`DECISIONS.md`, and `AGENTS.md`.

## S2 task evolution: complete Trellis implementation task

The [S2 task evolution Trellis task](.trellis/tasks/09-06-s2-task-evolution/prd.md)
contains the requirements and acceptance criteria for one complete end-to-end
deliverable. The [technical specification](.trellis/tasks/09-06-s2-task-evolution/design.md)
retains the full prior design, and the [execution plan](.trellis/tasks/09-06-s2-task-evolution/implement.md)
defines integration, validation, review and completion. Curated
`implement.jsonl` and `check.jsonl` supply the worker spec context.

The scope includes frozen intent, all three expansion operators, bounded
path-open verification, shared S2/probe/S3 validation, efficient solving,
dependency audits, deduplication, lineage, recursive scheduling, recovery,
CLI and current-format integration, automated tests, real campaigns,
relocation cold reads and independent comparisons. Internal checkpoints do
not constitute separate product releases or final delivery.

The task is **planning**, not implemented functionality or evidence of improved
model/task performance. On an implementation instruction, the implementing
session should validate and start this existing task using the repository's
Trellis workflow; no activation or runtime change is performed by its creation.
Report code completion, live validation and measured effects separately.

The former [plan URL](docs/plans/s2-task-evolution-implementation.md) remains a
navigation entry to the task, not another maintained specification.
