# Frozen task contract
Goal: ship S2 that samples and admits real Good Tasks from arbitrary Release/3 environments.
Invariant: Sampling Agent acts only through public reset/tools/invoke; Host owns truth and identity.
Invariant: Candidate requires a completed objective, grounded answer, fresh replay, and common-evaluator PASS.
Invariant: Atom/All/If/ForEach use one domain-free evaluator; five valid fresh runs require at least two PASS.
Not doing: Tool Graph/random walk, S1 diagnostic templates, generated Checker/TaskSemantics, S3/S4, compatibility.
Gold: S1 campaign `486dd234...a09ad7d`; four-environment probe `research/no-graph-cross-environment-probe.md`.

## Append-only decisions

- 2026-09-03: replace Agent-authored answer schema with Host-resolved AnswerProjection and type-only schema. Alternative was retaining model schema authoring; Git changed from 0/5 format-valid runs to 5/5 after the Host projection.
- 2026-09-03: default local 8317 filtering concurrency to one. Alternative was forcing parallel five-run execution; two-way concurrency produced zero attributable semantic outcomes while serial runs passed.
- Known baseline RED: two `test_product_authority.py` assertions encode superseded Graph wording/section text and must be replaced by no-Graph/no-Checker authority assertions.
- 2026-09-03: split Checkpoint A into A1 Goal/evaluator and A2 AnswerProjection/TaskDraft. Alternative was a 1190-line first module; the split reduced A1 to about 730 lines while retaining seven independently mutated truth edges.
- 2026-09-03: If state-change validation follows the actually selected branch, and its public condition event cannot double as branch completion. The rejected alternative treated any transition-capable branch as mandatory and failed the real false-branch RED.
- 2026-09-03: AnswerProjection is a separate 703-line A2 module and can only copy/assemble Task/reset/observation JSON; Host derives the type-only schema, including empty-array item shape from the public source schema. Alternative Agent-authored schemas failed 5/5 Git filters.
- 2026-09-03: Sampling context includes the exact target-specific DraftGoal/AnswerProjection templates and actionable rejected-output feedback; an identical terminal error twice or three terminal errors total stops the attempt. The opaque-string alternative caused 10+ retries after the environment objective had already succeeded.
- 2026-09-03: Checkpoint B retains the legacy proposal entrypoint only as an unreachable rollback boundary; Checkpoint C must delete it and return task_proposal.py below its pre-B size rather than preserving two product paths.
