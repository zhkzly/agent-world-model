---
name: engineer-agent-world
description: Design, implement, or repair an Agent World executable environment from typed Foundry artifacts. Use for WorldSpec/design synthesis, real Runtime and Task Materializer v3 code generation, or same-session candidate repair without evaluator authority or sealed evaluation.
---

# Engineer Agent World

Build a real programmatic environment whose observable behavior is defined by `WorldSpec`.

## Design mode

1. Use evidence claims for real-world facts; mark unsupported choices as bounded product
   decisions or unknowns.
2. Define state, ToolSurface, ToolSemantics, transition constraints, permissions, observations,
   errors, idempotency, transactions, rollback, concurrency, and task distributions together.
3. Keep tasks, runtime behavior, and verification requirements derived from the same WorldSpec.
4. Return exactly the requested structured contract version.

## WorldRules semantic ownership

When the requested output is `WorldRuleSemanticsSourceDraft`, author only two semantic sections:

- `initial_state_rules.initial_state_constraints` contains reset-validity Rules and every Rule uses
  family `initial_state`.
- `invariants` contains cross-tool Rules that hold after reset and every tool transition, and every
  Rule uses family `invariant`.

`RuleDraft.rule_id` is a framework IR identity, not business meaning. Omit this optional field for
WorldRules even if it appears in the output schema. Framework code derives stable
`rule:state:<ordinal>` and `rule:world:<ordinal>` values from the frozen section and ordinal; do
not guess, copy, repair, or satisfy an ID-prefix convention in model output.

Use only the frozen architecture, state schemas, committed ToolSemantics, and evidence claims. A
WorldRule is a general executable property, never a fixed scenario, task goal, expected answer, or
trajectory. Do not restate schema validity as a full `schema_valid` invariant when framework code
already owns schema validation, and never read evaluator-only `task_goal`.

## CurriculumPlan semantic ownership

When the requested output is `CurriculumPlanSourceDraft`, author only the compact, ordered
task-family plan. Choose the smallest semantically distinct end-to-end families needed for the
frozen WorldModel. A plan owns task-family identity, reachable objective, actor/tool scope,
difficulty, sampling, and design-stage coverage; it does **not** own any task-local Rule section.
Do not enumerate task instances, trajectories, examples, variants, success/failure/terminal Rules,
schemas, evaluator bindings, reward, verification policy, code, solutions, or release decisions.

`task_plans` is a physical fan-out authority: framework code freezes exactly one independent
TaskRequirement Agent turn for each ordered entry. Therefore choose only a small complete family
set; do not add a family merely to describe a variant. `coverage_dimensions[*].rule_ids` is a
closed reference field: copy literal IDs only from the runtime Prompt's `coverage_rule_catalog`,
which contains the frozen world Rule closure. Do not mint an ID or use a task/sampling Rule ID;
`rule_ids` may be empty when no existing world Rule directly supports that coverage dimension.

`difficulty_dimensions` is also a closed top-level catalog, not a place to invent generic axes.
Return one `DifficultyDimension` for every id in the runtime Prompt's `task_dimension_catalog`
(or `world.task_dimensions`), exactly once and in that exact order; do not add, remove, rename,
or reorder any id. A `task_plans[*].difficulty_dimensions` list may select only applicable ids
from that complete catalog. Before returning, compare the top-level dimension-id sequence against
the supplied catalog literally.

Sampling Rules use family `sampling` and never read evaluator-only `task_goal`. Omit
`RuleDraft.rule_id`: framework code derives `rule:sampling:<ordinal>` after it validates the plan.

## TaskRequirement semantic ownership

When the requested output is `TaskRequirementSourceDraft`, author exactly one task family for the
provided frozen `target_task_plan`. Preserve its `task_type`, objective, allowed actors, required
tools, difficulty dimensions, and minimum tool calls exactly. Do not add, remove, rename, reorder,
or infer another task family. The framework owns task schemas, evaluator bindings, reward,
verification closure, materialization policy, the physical loop, and Rule identities.

Include all four Rule-list fields even when a permitted list is empty:
`initial_state_constraints` (may be empty), `success_conditions` (non-empty),
`failure_conditions` (may be empty), and `terminal_conditions` (non-empty). Every task—not merely
the curriculum as a whole—needs at least one terminal Rule.

Use these exact Rule-family and source boundaries:

- Initial-state Rules use `initial_state` and may read reset_config/pre_state but never `task_goal`.
- Success Rules use `task_success`; failure Rules use `task_failure`; terminal Rules use
  `task_terminal`.
- Every task has at least one success Rule and at least one terminal Rule that read `task_goal`.
  Every such pointer is non-root, RFC 6901, scalar (`null`, `boolean`, `number`, or `string`), and
  non-overlapping with every other task-goal pointer in that task.
- Evaluator Rules never read Runtime-reported `terminated` or `truncated`.

Omit `RuleDraft.rule_id` from every task Rule. Framework code derives
`rule:task:<task_type>:<section>:<ordinal>` from the already frozen target; never guess a prefix,
repair an ID, copy a world Rule ID into a task Rule, or make task semantics depend on an ID
convention.

Use only frozen actors, tools, state paths, existing world Rule IDs, and exact evidence claim IDs.
Do not author sampling or coverage, initial-config/public/evaluator JSON Schemas, evaluator
bindings, reward values, verification policy, task instances, replay cases, trajectories, expected
answers, or release decisions. Those are framework-owned projections from the frozen world and
your one-family Rule semantics. `TrainingSemanticSourceDraft` is assembled only by the framework's
deterministic join; a production Engineer turn must never author the complete aggregate directly.

## Closed evidence-claim binding

`evidence_claim_catalog[*].claim_id` is a closed enum for every
`evidence_claim_ids` field. Copy an id byte-for-byte from that frozen catalog only after checking
that it supports the factual statement. Never mint, rename, infer, or describe a claim id from the
business meaning, a field name, a tool name, or a desired policy. Do this final literal check for
every evidence binding before returning the typed artifact.

For a `FidelityStatement` that records a synthetic policy or a bounded choice with no factual
support, do not invent an evidence id merely to populate the field. Leave `evidence_claim_ids`
empty only where that requested schema permits it, and state the required bounded divergence or
unresolved limit. Fields whose requested schema requires at least one evidence id must instead use
one or more exact frozen catalog ids.

## Tool-semantics root and scope

When the requested output is `ToolSemanticsBatchSourceDraft`, return the complete logical root
directly as `{"tools":[...]}`. Do not wrap it in `tool_semantics`, `artifact_json`, a summary,
or any other outer object. The `tools` array contains exactly the one or two frozen target tool ids
in their supplied order. Each TOOL is complete: conditions, state_transition, errors,
access_observation, and reliability. Do not add a sibling tool merely to explain a dependency.

`ToolRuleDraft.rule_id` is framework-owned identity. Omit it everywhere in a tool batch; framework
code derives the stable tool/section/ordinal namespace after validation. Never infer or satisfy an
ID-prefix convention in model output.

## Tool-semantics representation audit

Before returning a `ToolSemanticsBatchSourceDraft`, run a separate JSON-shape pass for **every**
TOOL. Copy its exact enclosing `tool_id` into each required nested section:
`conditions.tool_id`, `state_transition.tool_id`, `errors.tool_id`,
`access_observation.tool_id`, and `reliability.tool_id`. A parent id never makes a nested id
implicit.

The following values are one non-empty JSON string, never a list or object: every
`RuleDraft.description`, `errors.errors[*].observation`,
`access_observation.permission.denied_observation`,
`reliability.idempotency.duplicate_observation`,
`reliability.transaction.commit_point`, `reliability.rollback.guarantees`,
`reliability.concurrency.conflict_detection`, and
`reliability.concurrency.ordering_guarantee`.

Check the rest of `reliability` by primitive kind, not merely by field name:

- `retry.maximum_attempts` is an integer at least 1; retryable/trigger/compensation code fields are
  arrays; `retry.requires_same_idempotency_key`, `transaction.partial_commit_observable`, and
  `rollback.supported` are booleans.
- `timeout.operation_timeout_seconds` is a positive number;
  `idempotency_key.retention_seconds` is null or a positive number; and
  `observation.staleness_bound_seconds` is null or a non-negative number.
- `concurrency.conflict_error_code` is null or one identifier string. Do not use explanatory prose
  in place of a boolean, number, null, identifier, or array.

## Tool-semantics scalar observations

When authoring `ToolSemanticsBatchSourceDraft`, the following are **one non-empty string**, never
an object, list, Rule, evidence record, or nested explanation:

- `errors.errors[*].observation`
- `access_observation.permission.denied_observation`
- `reliability.idempotency.duplicate_observation`

Write each as one concrete user-visible sentence, then mechanically check its JSON type is a
string before returning. Keep every `errors.errors` array non-empty and return exactly the frozen
one- or two-tool batch; do not compensate for a scalar field by nesting another schema fragment
inside it.

## Tool-semantics Rule clause closure

For every `ToolSemanticsBatchSourceDraft` Rule clause, choose fields from its exact operator branch:

- `equal`, `not_equal`, `contains`, and `not_contains` use `clause_id`, `operator`, `left`,
  `right`, and optional `negate`; they **must omit** `ordering`.
- `greater_than`, `greater_or_equal`, `less_than`, and `less_or_equal` require `ordering` exactly
  once as `number`, `date`, or `date-time`.

Before returning, mechanically inspect each clause: never copy `ordering` from a comparison clause
onto an equality or containment clause. The output objects are closed; a field legal for one
operator is still forbidden on every other operator.

Arithmetic is deliberately **non-recursive**: `arithmetic.left` and `arithmetic.right` are each one
atom — a constant, a context reference, or a bound lookup — and `value_type` must be `number` on
both. Never nest another `arithmetic` (or a clause) inside an operand. Express a multi-step
computation as a declared numeric state field or a bound lookup, not as a nested expression tree;
there is no expression language here.

Every `state_transition.transition` array is non-empty: a tool that changes state must declare at
least one transition Rule. Do not emit an empty transition list and rely on prose elsewhere.

Every `binding_id` is a closed enum, and **each term type draws from its own catalog**. The
namespaces are not interchangeable: pick the term type first, then copy an id byte-for-byte from
that term's catalog in the provided rule context.

| term type | catalog in the rule context | alias shape |
| --- | --- | --- |
| direct reference | `reference_bindings` | `ref-NN` |
| lookup by literal key | `lookup_binding_groups[*].value_bindings` | `lookup-NN` |
| lookup by reference key | `lookup_reference_binding_groups[*].reference_key_bindings` | `lookup-ref-NN` |

Copy the alias exactly as listed, including its zero padding (`ref-03`, never `ref-3`). Never use a
`ref-NN` where the term is a lookup, never use a `lookup-ref-NN` for a direct reference, and never
mint an id or renumber the sequence. This applies to every term position, including `left` and
`right` of any `state_transition` clause. Before returning, walk each clause term and confirm its
`binding_id` appears verbatim in that term type's own catalog.

Lookup keys use one flat, closed variant. For a reference key, use
`bound_lookup_by_reference` with the single composite `binding_id` listed in
`lookup_reference_binding_groups`; never combine a lookup alias with a separate reference alias.
For a literal key, use `bound_lookup_by_constant` with one lookup `binding_id`, `key_value_type`,
and `key_value`. Never emit `key_binding_id`, a nested `key`, arithmetic as a key, another lookup
as a key, or raw reference/pointer fields.

## Tool-semantics reliability closure

Every error code named anywhere in `reliability` is a closed enum drawn from the **same tool's own**
`errors.errors[*].error_code`. Author that `errors` array first, then reference only codes it
declares:

- `reliability.timeout.timeout_error_code`
- `reliability.rollback.rollback_trigger_codes[*]`
- `reliability.concurrency.conflict_error_code` (when not null)
- `reliability.retry.retryable_error_codes[*]`, which additionally require the referenced error to
  be declared `retryable: true`

`reliability.rollback.compensation_tools` is likewise a closed enum over the frozen tool inventory. Never
invent an operational error code, reuse one from a sibling tool in the batch, or describe a failure
mode the `errors` section never declared. Before returning, mechanically list this tool's declared
`error_code` values and confirm every reliability reference is a member of that set, and that each
retryable reference points at a `retryable: true` error.

## Tool-semantics shared-contract closure

`shared_contracts` is a frozen cross-tool input, not background prose. For every target tool,
mechanically compare `reliability.transaction.atomicity`, `reliability.concurrency.isolation`, and
`reliability.idempotency.mode` with its matching shared domains. For every
`source.error_policies` entry whose `member_tool_ids` contains that tool, declare at least one
error whose final `error_code` identifier segment equals `required_error_suffix` and whose
`retryable` value equals the policy's `retryable` value. For each compensation edge where the tool
is `failure_tool_id`, include its `compensation_tool_id` in
`reliability.rollback.compensation_tools`. Do this literal comparison before returning; do not
replace a frozen shared choice with a plausible local alternative.

## Tool-semantics access closure

`access_observation.permission.required_scopes_by_actor` is the non-empty allowed-actor map. Its
keys are exactly the frozen actors permitted to use the tool; never emit a separate
`allowed_actors` field because framework code derives that Runtime/Judge projection. Each listed
scope must be one of that actor's frozen boundary authorities, while an empty scope list remains
valid. `visible_fields_by_actor` covers every frozen boundary actor and uses only exact top-level
fields from that tool's frozen observation schema.

When `required_scopes_by_actor` covers **every** frozen boundary actor and a `condition` is present,
that condition is universal and its `case_sensitivity` must be `positive_and_negative`: a rule that
admits all actors has to state both the positive and the negative case. A condition must use family
`permission` and omit `rule_id`. Before returning, check whether the map keys are exhaustive and,
if they are, that `case_sensitivity` is `positive_and_negative`.

Candidate planning and code generation use their own exact-node Runtime Skills
(`engineer-build-planning` and `engineer-environment-codegen`). Do not apply
their workspace-write instructions to a semantic design turn.
