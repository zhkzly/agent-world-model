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

## S2 task evolution: complete implementation specification

The [complete S2 task evolution specification](docs/plans/s2-task-evolution-implementation.md)
defines one end-to-end implementation deliverable, not a sequence of partial
product releases. Its required scope includes frozen intent, prerequisite,
discovery and related-outcome expansion, bounded result verification, shared
S2/probe/S3 validation, efficient solving, dependency audits, deduplication,
lineage, recursive scheduling, recovery, CLI integration, format updates,
automated tests, real campaign execution, relocation cold reads, and evaluation.

Read section 0 for the complete scope and completion conditions, sections 10–14
for interfaces, formats, commands, tests, and live validation, and section 15
for the implementation-agent handoff. Internal checkpoints do not constitute
final delivery.

The specification is **not implemented functionality or evidence of improved
model/task performance**. This documentation change does not itself activate
an implementation task or change runtime product contracts. During an
authorized implementation, synchronize the actual contracts and report code
completion, live validation, and measured effects separately.
