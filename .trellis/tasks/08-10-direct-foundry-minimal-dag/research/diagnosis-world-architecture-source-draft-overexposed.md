# Diagnosis — WorldArchitecture SourceDraft exposes framework mechanics

## Expected behavior

`world_architecture` is one bounded Direct LLM semantic transaction. The model
chooses the world boundary, entities, business field kinds and finite business
domains, tool purpose/interface meaning, actor scope, and evidence-backed
divergences. The framework then normalizes defaults and compiles indexes,
references, schema shape, IDs, catalog, coupling plan and provenance.

This is the binding split in the source of truth: the model owns business
meaning and typed source IR; the framework owns JSON Schema mechanics,
`required` assembly, IDs and references.

## Evidence

- Real run `run_5c648fca95e64bc08107b70a48127854` reached Luna twice with
  complete JSON responses. The failure was not timeout, truncation or route
  failure.
- The first response failed because the recipient had not been told to emit a
  nonempty `values` array for an enum/list; the second failed on duplicate
  finite values.
- The first repair made every field emit all five internal keys, including
  `values: []` and `entity_ref: null`, and made each tool emit one-based
  `actor_indexes`. Static checks pass, but that turns framework-normalizable
  details into model obligations.
- `docs/agent-world-environment-generation.zh.md` says WorldArchitecture emits
  compact field/tool business semantics and the framework deterministically
  compiles Entity/Tool Schema, IDs, references, required and closed shape.
  `docs/direct-rewrite-execution-map.zh.md` likewise forbids WorldArchitecture
  from owning JSON Schema mechanics.

## Causal attribution

The node is not too large: the observed requests were about 562--598 tokens
and responses about 1,472--1,787 tokens, with no truncation. The defect is the
SourceDraft boundary. We responded to hidden compiler rules by disclosing the
whole normalized wire object instead of removing framework-owned obligations
from the model output.

The closed set of field categories is framework code; the model only selects
the business kind. Concrete enum/list members such as `available` and
`checked_out` are business semantics and cannot be globally hardcoded. Empty
finite-domain arrays, null relation placeholders and numeric actor references
are mechanical and should be normalized or resolved by code.

## Repair boundary

Keep the single WorldArchitecture node and its current input projection. Make
the model-facing field shape sparse: `name`, `category` and semantic
`required`, plus `values` only for enum/list and `entity_ref` only for a real
relation. Make tool actor scope use declared actor names; compile those names
to the existing internal one-based indexes. Preserve the internal
`WorldArchitecture`, every downstream Artifact/edge, correction budget,
backend and route.

Do not split the node, add a schema library, add retries, change models, add a
Skill, or redesign downstream contracts. This diagnosis authorizes no code
change or live retry.
