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
