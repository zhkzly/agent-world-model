# TaskSemantics Project Contract

> **Status: Checkpoint-A contract implemented.** Host models/decoders and tests
> use this exact shape. A model run belongs to a later checkpoint and cannot by
> itself authorize Qualification or Publication.

Write one standalone Python 3.12 uv project implementing a release-local,
read-only `TaskSemantics` factory. The project is proposed code; Host execution
and Qualification alone decide whether it is usable.

## Immutable inputs

- `EXPECTED_TASK_SEMANTICS.json`: accepted Requirement dispositions and the
  expected capability/workflow/composition/condition relations, including the
  exact answer field IDs and public labels later checked by v2 Qualification.
- `PUBLIC_SURFACE.json`: the actor factory, public schemas, ToolSpecs, public
  documents and the exact candidate-view digest.
- `TASK_SEMANTICS_WIRE.json`: machine-readable exact wire schemas plus minimal
  examples already accepted by the Host decoders. It is the authority for
  record shape when prose is ambiguous.
- `candidate-view/`: read-only actor source/native format documentation exposed
  only after expected semantics were frozen.

Do not edit these files. Do not copy Host digests, manifests, run IDs or verdicts
into generated semantic records.

Generated diagnostic tests must validate representative `start_cases`,
`capabilities`, `enumerate_bindings`, atom results and condition results against
`TASK_SEMANTICS_WIRE.json` before reporting completion.

## Required factory surface

Expose one `module:factory` that returns an object with exactly these methods:

```python
start_cases(seed: int, limit: int) -> list[StartCaseDocument]
inspect(instance_directory: Path) -> JSONValue
capabilities() -> list[CapabilitySpecDocument]
enumerate_bindings(capability_id: str, facts: JSONValue) -> list[BindingCandidateDocument]
evaluate_atom(request: AtomCheckRequestDocument) -> AtomCheckResultDocument
evaluate_condition(request: ConditionCheckRequestDocument) -> ConditionCheckResultDocument
```

Every document must be JSON-compatible and contain the exact fields defined by
`agent_env_foundry.semantics`; the Host decodes those documents into its own
typed values. The generated project must not import the Host package at runtime;
its lockfile must contain every dependency it uses.

## Exact JSON records

`StartCaseDocument` has exactly:

```text
case_id: non-empty whitespace-free string
reset_input: object or null
regime_tags: unique string array
```

`CapabilitySpecDocument` has exactly:

```text
capability_id, requirement_ids, workflow_ids, composition_rules,
actor_role, task_kind, intent_label,
protected_binding_schema, public_descriptor_schema,
facets, conditions, answer_fields,
supported_goal_kinds, rendering
```

`task_kind` has precedence semantics, not a loose style label:

- `state_change`: successful completion requires any business-state change,
  even when a multi-step public process is also required;
- `process`: successful completion requires public action/process evidence but
  no business-state change, such as a stable refusal;
- `query`: successful completion requires no business-state change and returns
  one or more public answer fields.

Qualification compares `inspect(before)` and `inspect(after)` and rejects a
catalog whose declared kind disagrees with the physical semantic transition.

Nested records have exactly:

```text
CompositionRule:
  rule_id, workflow_id, kind="all", capability_ids, max_occurrences
FacetSpec:
  name, public_label, value_schema, allowed_operators
ConditionSpec:
  condition_id, public_label, binding_scope,
  true_capability_ids, false_capability_ids, report_field, public_source
AnswerFieldSpec:
  field_id, schema, public_label, public_source
RenderingSpec:
  imperative, target_noun, answer_phrase
PublicValueSource:
  kind, tool_name, json_pointer, value
```

Schemas are self-contained Draft 2020-12 JSON Schema objects. Protected/public
binding schemas must have object roots. Every capability supports `atom`;
additional goal kinds are only `all`, `if`, and `foreach`. Facet operators are
only `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `min`, and `max`.

`PublicValueSource.kind` is exactly `task_literal`, `task_descriptor`, `reset`,
`tool_observation`, or `tool_schema_constant`. Binding-leaf task literals supply
their actual `value`; task-descriptor and reset sources supply an RFC 6901
pointer; tool-observation pointers are rooted at the complete public
`{ok,data,error}` observation. Tool schema constants supply a tool input-schema
pointer and exact value. Unused fields are null. Broad object schemas do not
authorize a descendant path.

Every generated capability must preserve the exact `field_id`/`public_label`
pairs frozen in its expected capability record. You author the release-local
Draft 2020-12 value schema, but the schema does not authorize a new field or a
different semantic label.

`BindingCandidateDocument` has exactly:

```text
semantic_key, eligible, reason_codes,
protected_binding, public_descriptor, facets, public_sources
```

`public_sources` is an array of exact `PublicFieldSource` records, never a JSON
object/map. Each record has exactly:

```text
field_pointer: RFC 6901 pointer rooted at /public_descriptor or /facets
source: one PublicValueSource document
```

For example, a descriptor leaf `{"charge_reference": "CHG-1"}` uses
`field_pointer="/public_descriptor/charge_reference"`. Every descriptor/facet
leaf appears exactly once; do not shorten the pointer to `/charge_reference`.

Eligible bindings have no reason codes. Ineligible bindings have at least one.
The three projections are JSON objects and must validate against the capability
schemas/facets.
`public_sources` maps every public descriptor/facet leaf pointer to an exact
`PublicValueSource`. No leaf may rely on prose, a protected value or an
undeclared object descendant. The binding owns this per-leaf source so different
bindings may carry different literal values without duplicating them in the
capability-wide FacetSpec.
Within one StartCase and capability, different semantic keys must not expose the
same public binding document. Public descriptors/facets must identify the
intended referent using values available from schema-qualified reset or tool
observations; protected-only identity cannot resolve a public ambiguity.

`AtomCheckResultDocument` has exactly:

```text
initially_satisfied, satisfied, required_effects_ok, collateral_ok,
answer_ok, process_ok, report_values, failure_codes
```

`answer_ok` and `process_ok` are boolean or null. A satisfied result cannot have
failed required effects/collateral/answer/process or non-empty failure codes.
`initially_satisfied` means that the entire Task goal would already pass for
the selected referent in the before state, before any public action, tool
observation, final answer, or process evidence is credited. It is not capability eligibility,
a workflow precondition, or a refusal condition. An eligible object still
requiring a mutation is not initially satisfied; neither is a query still
requiring a public read and correct answer. A genuinely already-complete goal
may return true so the S2 compiler can reject that Blueprint as trivial.
Every Taskable capability declares at least one `answer_fields` record,
including state-change and process/refusal capabilities. Every Task therefore
has a structured public final answer; requiring `final_answer` without
publishing its answer contract is invalid. Capabilities licensed by the same
ConditionSpec may use different answer field IDs and schemas. Each capability
declares only values needed by its own user objective; state/process/collateral
evidence is not padded into another branch's final answer.

Every answer-field schema must also be accepted as a strict structured-output
subschema. Recursively, every array declares an `items` schema. Every object
declares `properties`, lists every property in `required`, and sets
`additionalProperties` to `false`; these rules also apply inside nullable types
and `anyOf`/`oneOf`/`allOf` branches. Draft-valid broad arrays or objects are not
acceptable because the public Responses runner cannot submit them.

For every declared answer field, compute the expected value from independently
decoded native facts and the qualified public trace, put that value under the
same field ID in `report_values`, and compare the submitted `final_answer`
exactly. Return `report_values` with exactly the declared answer field IDs of
the capability. Use JSON `null` only when that capability's own field contract
permits a missing public occurrence. Compare source-bound exact public values,
not synonyms, reformattings, or
near-equivalents. A missing, schema-valid wrong or stale answer must set
`answer_ok=false` and `satisfied=false`. Never read an undeclared final-answer
field or treat mere field presence as semantic agreement.

A query capability must be demonstrable through a real public read and must not
require a successful state-changing call. A process capability must reject the
same terminal state with an empty trace or a trace that omits its required
public process. Compute `required_effects_ok`, `collateral_ok`, `answer_ok` and
`process_ok` from their distinct obligations; do not copy one `satisfied`
boolean into every field.

For every capability, `collateral_ok` is independent of whether its required
effect occurred. If `before_facts` and `after_facts` are identical, no
prohibited collateral mutation occurred: a missing required effect may make
`required_effects_ok=false`, but it must not by itself make
`collateral_ok=false`. Generated tests must cover this no-op axis separation.

For a query, "real public read" means evidence carried by a successful public
ToolObservation for the selected referent, not one hard-coded tool name or one
reference sequence. When the frozen public surface exposes the same qualified
answer through more than one read tool, accept every such schema-valid route
and compare the submitted answer against independently decoded native truth.
Generated tests must exercise an equivalent alternate public read when one
exists. Conversely, if the complete answer is already present in the reset
observation, do not invent a mandatory tool call to make the query appear
non-trivial: report the upstream environment defect instead of authoring a
path-bound checker.

The query axes are independent and have one fixed interpretation:

- `required_effects_ok=true` for a supported selected query because it has no
  state-effect obligation;
- `collateral_ok` is exact permitted before/after native-state equality and is
  independent of whether a read occurred;
- `answer_ok` compares the submitted answer with native `report_values` and is
  independent of process evidence;
- `process_ok` alone records whether an equivalent selected public read
  occurred.

`ConditionCheckResultDocument` has exactly:

```text
status: "true" | "false" | "abstain"
report_values: object
failure_codes: unique string array
```

Requests passed to evaluators are JSON objects:

```text
AtomCheckRequest:
  capability_id, before_facts, after_facts, protected_binding,
  trace_projection, final_answer, evaluation_context
ConditionCheckRequest:
  condition_id, before_facts, protected_binding, trace_projection
TraceEvent:
  seq, tool_name, arguments, observation
GoalEvaluationContext:
  current_slot, resolved_bindings, composition_rule_id,
  foreach_selector_id, permitted_sibling_slots
```

Every evaluator scopes public process evidence to its current selected binding.
A successful or refused sibling call may be permitted collateral, but it must
not satisfy the current binding's required effect or process axis. Validate the
target arguments/referent and the corresponding outcome or stable refusal code.

The evaluation context contains the exact run-local protected bindings selected
for the current Goal. `permitted_sibling_slots` must match the qualified
CompositionRule or ForEach selection. Evaluators may allow those sibling effects
without treating unrelated mutations as collateral. Do not invent or interpret
a generic read/write-scope algebra.

`start_cases` must return deterministic, schema-valid reset-only world regimes.
Case IDs alone do not create different world regimes. Repeated `(seed, limit)`
calls return identical records.

## Separation and state rules

- The semantics project must not import the actor package or call actor business
  functions as an answer oracle.
- The semantics project never receives the independent Qualification Verifier
  source, outputs, tests or repair history and must not attempt to discover them.
- `inspect`, `capabilities`, `enumerate_bindings`, `evaluate_atom` and
  `evaluate_condition` must not mutate the instance directory.
- Native state may be decoded with independent standard readers appropriate to
  the generated representation.
- Protected bindings/native fields must never be copied into public descriptors,
  labels or rendering text.
- Every binding, facet, condition and answer operand requires an exact public
  source and must agree with real public execution during Qualification.
- Composition and condition branches may only use the frozen Requirement,
  workflow and capability relations.
- Return structured values; do not return scalar rewards or terminal verdicts.

## Project requirements

The project must include `pyproject.toml`, `uv.lock`, source, and diagnostic
tests. `uv sync --frozen --all-groups`, build, tests, and Host schema/import/
no-mutation checks must pass. A model-written success message is never evidence.
Diagnostic tests must include no-op, wrong-target or near-miss, schema-valid
wrong/stale answer, prohibited collateral and empty/wrong process trace cases
where the corresponding capability declares those obligations.
