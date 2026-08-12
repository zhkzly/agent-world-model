# Diagnosis — WorldArchitecture correction regressed a later constraint

## Expected behavior

`world_architecture` is one prompt-only Direct LLM transaction. It receives the
need plus frozen EvidenceGraph semantics and proposes only the world boundary,
entities, compact field semantics, tool surface, and cited divergences.
Framework code owns the closed grammar, the `1..8` tool bound, entity-reference
closure, compilation, IDs, hashes, WorkRecord, Finding, route and release.

## Real scene and chronology

Fresh public run `run_fac8d0b2961842c996837d2f035e3102` passed real
`research_plan` (Agent), `research_acquire` (framework), and
`research_synthesis` (Agent). Its first Luna WorldArchitecture proposal was
rejected at `$.entities[1].fields[1].entity_ref` because the reference did not
name a declared entity. The exact correction packet was returned. The second
proposal passed the earlier entity parsing/closure checks and then failed at
`$.tools` because it was not an array with the disclosed `1..8` cardinality.
Framework committed no Architecture, emitted one blocking Finding, rejected the
run, and left Registry `not_published`.

Both Luna calls completed normally. The first used 1,931 input / 4,013 output
tokens; the second used 1,968 input / 3,560 output tokens. This was not a
transport, credential, timeout, JSON envelope, Research Skill, or token-ceiling
failure.

## Attribution

The model-visible shape contains both rules, so this is not another hidden
numeric contract. The node intentionally asks for one coherent architecture,
but presents its connected rules as one dense grammar line. A correction asks
for a complete replacement object; the generic Direct instruction does not
explicitly require a final whole-object recheck after repairing one path. The
second draft therefore made validator progress but regressed at a later
collection boundary.

The task's human-facing `node-contracts.md` also still describes an older rich
field draft (`meaning`, `presence`, `value_kind`, and index references), while
the actual model/compiler contract is the current sparse draft (`name`,
`category`, `required`, conditional `values`, and optional exact-name
`entity_ref`). That documentation drift did not cause the runtime failure—the
model never reads the task file—but it makes future implementation review
unsafe and must be corrected alongside the model-visible wording.

## Minimal repair boundary

Keep the one-node architecture transaction and the existing two total attempts.
Clarify only its model-visible output contract with a concise objective and a
mandatory whole-object self-check: emit no more than eight coherent tools,
combine closely related workflow actions when necessary, and make every
present `entity_ref` exactly copy one emitted entity name. State that the full
object must be rechecked after a correction. Align the task node-contract text
to the already-implemented sparse source draft.

Do not hardcode business tools or entities, accept invalid output, truncate or
select model output, add a node, split the architecture, add a generic prompt
framework, increase retries, change model routes, or touch later child paths.
This diagnosis authorizes no edit or provider retry.
