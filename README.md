# agent-env-foundry

Implementation of the Canonical Agent Environment Foundry (see `PROJECT.md`).

Current branch status: the v1 loader/Qualification/publication path has been
deleted. The repository contains the v2-only release verifier, locked actor and
TaskSemantics runtimes, Research/Builder foundations, semantics contracts and
the complete Direct S2 production sampler. `run_task_foundry_batch(...)` and
`run_task_foundry_product(...)` are the sole Direct sampling path; three real
cross-domain releases (filesystem/Git, SQLite and one post-freeze held-out
Need) already carry Qualification, publication, TaskPack, assessment and corpus
evidence. The thin `generate_environment_v2(...)` S1 coordinator composes the
existing Research, Builder, author, Qualification and publication stages into
one domain-neutral call.

No demo, mock or canned artifact constitutes a released environment or a
completed S2 result. Completion requires the real cross-domain and held-out
evidence in the active Trellis task.

Product intent, stage boundaries and working rules live in `PROJECT.md`,
`DECISIONS.md` and `AGENTS.md`; this file only describes the code package.

## Planned S2 task evolution

The [S2 task evolution implementation plan](docs/plans/s2-task-evolution-implementation.md)
contains the reviewed design for intent-grounded prerequisite/discovery
expansion, independent efficient solving, task deduplication, dependency
assessment, tests, and the PR0–PR5 implementation sequence.

This is a **design proposal, not implemented functionality**. It does not
change the current product contracts or activate an implementation task.
Read section 0 for the overview, sections 15–16 for the implementation order
and handoff, and sections 12–13 for interfaces and test cases.
