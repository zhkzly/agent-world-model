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

## S2 task evolution: bounded complete Trellis task

The [S2 task evolution task](.trellis/tasks/09-06-s2-task-evolution/prd.md)
defines one complete algorithm delivery on the working pipeline, not staged
product versions. Read its [design](.trellis/tasks/09-06-s2-task-evolution/design.md)
and [implementation plan](.trellis/tasks/09-06-s2-task-evolution/implement.md)
with the curated `implement.jsonl` and `check.jsonl`.

The current scope includes prerequisite, discovery and related-outcome
expansion, frozen-intent execution, necessary endpoint/route verification
repairs, efficient-solver feedback, finite recursion, deduplication, official
TaskPack/S3 integration, real cold reads and independent comparisons.
It does not require a universal state-mapping system, a separate Extractor
subsystem, blanket artifact-format migration or replacement runtime services.
The earlier broader specification is superseded, not an extra hidden checklist.

The task is **planning**. Its algorithm, including the proposed minimal
`FinalStateGoal` support, is not implemented functionality or evidence of
improved performance. After an implementation instruction, the local session
should validate and start this existing task, then report code completion,
real integration and measured effects separately.

The former [plan URL](docs/plans/s2-task-evolution-implementation.md) is only a
navigation entry to the Trellis task.
