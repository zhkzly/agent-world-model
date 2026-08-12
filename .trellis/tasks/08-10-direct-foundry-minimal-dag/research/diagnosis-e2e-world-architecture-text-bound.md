# Diagnosis — E2E WorldArchitecture text bound was not actionable

## Expected behavior

The first full CLI run should carry committed Research output into one bounded
`world_architecture` Direct transaction. Its compact output contract must tell
Luna every existing textual bound needed before proposal, and the one local
correction must name the exact violated bound if needed.

## Real scene

- Run: `run_d825291601a741da8d854a94400e2d01`
- Completed before failure: `research_plan`, `research_acquire`, and
  `research_synthesis`, all with passed WorkRecords
- Failed node: `design/world_architecture`
- Terminal: `rejected`, `world_architecture_invalid`
- Finding: `finding_979a8e04629fff7a`, blocks release
- Release: `not_published`

Chronology:

1. Luna returned a complete response using 2,420 input and 3,430 output tokens.
2. Compiler rejected `$.boundary.purpose` because `_text(..., limit=160)`
   received text outside its bound.
3. Framework sent the only correction, but the packet said only "value must be
   bounded nonempty text" and did not disclose `160`.
4. Luna returned another complete response using 2,450 input and 3,181 output
   tokens. It failed at the same path and same condition; the correction budget
   then closed the Work as failed.

## Attribution

This is not a provider, route, truncation, Research, sparse-field, actor mapping
or correction-count failure. The earlier sparse SourceDraft real proof passed
on Luna. Here both responses were below the 4,096-token output ceiling and
reached the compiler.

The current recipient shape names boundary/entity/tool text fields without the
limits already enforced by the compiler. The generic correction also hides the
numeric limit, so it is not actionable. Real Research evidence elicited a more
detailed boundary purpose than the synthetic node proof and exposed that
producer/validator mismatch.

## Repair boundary

Keep the same node, sparse grammar, compiler acceptance, one correction, route
and downstream Artifact. Add one compact model-visible text/uniqueness clause
for the limits already enforced inside WorldArchitecture and make `_text`
include its existing numeric limit in rejection feedback. Do not truncate model
semantics, relax limits, add retries, split the node, add a schema/prompt system,
or touch another node's output shape.

This diagnosis authorizes no code edit or retry.
