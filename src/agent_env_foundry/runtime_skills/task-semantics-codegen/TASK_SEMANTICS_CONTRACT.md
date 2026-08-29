# TaskSemantics Project Contract

> **Status: Checkpoint-A target — not executable at current HEAD.** The current
> Host decoders still use the pre-reclosure fields and would reject the
> `public_source`, `public_sources` and `evaluation_context` records below. Land
> this contract, Host models/decoders and tests atomically. Do not run the
> Semantics Author before that change is complete.

Write one standalone Python 3.12 uv project implementing a release-local,
read-only `TaskSemantics` factory. The project is proposed code; Host execution
and Qualification alone decide whether it is usable.

## Immutable inputs

- `EXPECTED_TASK_SEMANTICS.json`: accepted Requirement dispositions and the
  expected capability/workflow/composition/condition relations, including the
  exact answer field IDs and public labels later checked by v2 Qualification.
- `PUBLIC_SURFACE.json`: the actor factory, public schemas, ToolSpecs, public
  documents and the exact candidate-view digest.
- `candidate-view/`: read-only actor source/native format documentation exposed
  only after expected semantics were frozen.

Do not edit these files. Do not copy Host digests, manifests, run IDs or verdicts
into generated semantic records.

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

Nested records have exactly:

```text
CompositionRule:
  rule_id, workflow_id, kind="all", capability_ids, max_occurrences
FacetSpec:
  name, public_label, value_schema, allowed_operators, public_source
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

`PublicValueSource.kind` is exactly `task_literal`, `reset`, `tool_output`, or
`tool_schema_constant`. Task literals supply `value`; reset sources supply an
RFC 6901 reset-observation pointer; tool sources supply a tool name and exact
schema pointer. Unused fields are null. Broad object schemas do not authorize a
descendant path.

Every generated capability must preserve the exact `field_id`/`public_label`
pairs frozen in its expected capability record. You author the release-local
Draft 2020-12 value schema, but the schema does not authorize a new field or a
different semantic label.

`BindingCandidateDocument` has exactly:

```text
semantic_key, eligible, reason_codes,
protected_binding, public_descriptor, facets, public_sources
```

Eligible bindings have no reason codes. Ineligible bindings have at least one.
The three projections are JSON objects and must validate against the capability
schemas/facets.
`public_sources` maps every public descriptor/facet leaf pointer to an exact
`PublicValueSource`. No leaf may rely on prose, a protected value or an
undeclared object descendant.
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
Every `task_kind="query"` capability declares at least one `answer_fields`
record and a non-null rendering `answer_phrase`; requiring `final_answer`
without publishing its answer contract is invalid.

For every declared answer field, compute the expected value from independently
decoded native facts and the qualified public trace, put that value under the
same field ID in `report_values`, and compare the submitted `final_answer`
exactly. A missing, schema-valid wrong or stale answer must set
`answer_ok=false` and `satisfied=false`. Never read an undeclared final-answer
field or treat mere field presence as semantic agreement.

A query capability must be demonstrable through a real public read and must not
require a successful state-changing call. A process capability must reject the
same terminal state with an empty trace or a trace that omits its required
public process. Compute `required_effects_ok`, `collateral_ok`, `answer_ok` and
`process_ok` from their distinct obligations; do not copy one `satisfied`
boolean into every field.

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
