# R2 final repair plan — executable local-rule trace contract

## Lineage and scope

This is the final permitted revision for
`diagnosis-direct-e2e-tool-semantics-contract.md`. It incorporates the R1
producer/consumer/package closure at digest `573b78e1...` and changes only the
four executable details required by
`cross-layer-review-573b78e1-tool-semantics-r1.md`. All R1 file limits,
authorities, tests, proof order and non-goals remain binding.

The implementation remains one existing ToolSemantics transaction plus its
declared consumers. It adds no graph, node, model turn, Runtime public
operation/response, generic Rule platform, Repair, Expand or Consumer code.

## 1. Closed private snapshot projection

The framework-derived `SemanticBinding` from R1 is made executable by storing
these exact fields:

```text
SemanticBinding:
  index: positive one-based int
  source: "argument" | "tool_result" | "pre_state" | "post_state"
  name: frozen argument/result-field name
  path: exact tuple[str]
  value_category: "json_value"
```

Paths are derived, never model-authored:

- argument: `("arguments", argument_name)`
- tool result: `("result", result_field)`
- pre-state: `("pre_state", "tools", tool_name, result_field)`
- post-state: `("post_state", "tools", tool_name, result_field)`

`json_value` is exactly `null | boolean | integer | finite number | string |
list[null|boolean|integer|finite number|string]`; nested objects and nested
lists are rejected.

After reset, the candidate's framework-private `snapshot` response remains the
existing closed public-JSON envelope `{"state": object}`. The implementation
contract now requires `state` to contain exactly:

```text
{"tools": {tool_name: {result_field: json_value for every frozen result field}
                         for every frozen tool}}
```

Every declared path is required in both snapshots; missing, extra, wrong-type
or non-finite values fail `candidate_snapshot_projection_mismatch`. Snapshot
values never enter model prompts, package metadata, Observe, SFT or public
Episode APIs.

The one trace lifecycle is fixed and cannot be reordered:

```text
reset -> snapshot(pre) -> invoke -> result -> snapshot(post) -> close
```

This changes only framework-private validation around the existing `snapshot`
operation; the five-operation ABI and successful invoke response
`{"status":"ok","result":...}` are unchanged.

## 2. Narrow local evaluator

`agent_world/runtime.py` adds one private evaluator for the required Judge gate.
Its only inputs are the frozen selected `ToolDraft`, the framework-created
trace `{arguments, result, pre_state, post_state}`, and the exact assurance rule
IDs compiled at Modeling Gate. It returns only a safe gate result/code plus
framework commitments; it cannot invoke a model, route, repair, mutate the
candidate or release.

Binding resolution follows the exact paths above. Predicate operators have
only these meanings:

- `eq/ne/lt/le/gt/ge`: ordinary same-category scalar comparison;
- `contains/not_contains`: membership in a resolved list or substring in a
  resolved string;
- `exists/not_exists`: path presence only; `right` must be literal `null`.

Type mismatch, unsupported comparison, missing path or non-finite value fails
closed. A rule is applicable only when every `when` predicate is true. For an
applicable rule every effect is checked:

- `set`: target equals the resolved literal/reference value;
- `increment/decrement`: post/result numeric target equals the same-name
  pre-state number plus/minus a resolved finite numeric value;
- `add/remove`: post/result list equals the same-name pre-state list after the
  one resolved JSON value is added/removed;
- `preserve`: target equals the same-name pre-state value and effect value is
  `null`;
- `reject`: unsupported by this successful-invoke evaluator and cannot be an
  assurance-rule effect.

Rationale and citations are never executed. Rule IDs are framework-derived as
`tool:<tool_index>:<section>:<one-based ordinal>`.

## 3. Deterministic assurance coverage

R1 retains 1–6 transitions. R2 requires 1–6 preconditions as the minimal v1
success-path contract; postconditions and errors remain 0–6. The
ToolSemantics compiler still validates every declared rule, including errors,
but marks `reject` rules ineligible for current dynamic assurance.

After TaskRequirement freezes the selected first-tool `PublicStep`, Modeling
Gate evaluates rule predicates that use only `argument` and `tool_result`
bindings against the frozen step arguments/expected result. It deterministically
selects:

1. the lowest-ordinal applicable precondition with no `reject` effect;
2. the lowest-ordinal applicable transition with no `reject` effect and at
   least one effect targeting `tool_result` or `post_state`.

The resulting two exact rule IDs and their local-rules digest form the closed
`LocalRuleAssurancePlan` inside `DesignContract`. If either rule is absent,
unobservable, type-invalid or not applicable to the frozen step, Modeling Gate
fails `local_tool_semantics_assurance_unavailable` before Builder. This is a
deterministic Design validation, not an extra model retry or verifier guess.

Integration records the private trace only in memory and runs the same
evaluator as an early check. Judge independently creates a fresh trace and
evaluates exactly the two frozen rule IDs. Its required
`local_tool_semantics` gate fails on a digest mismatch, different selected
rule, missing snapshot path, false predicate, unsatisfied effect or absent
coverage. Safe gate evidence stores only tool/rule IDs, local-rules digest and
pass/failure code—not arguments, results or snapshot values.

## 4. Error/reject boundary

The Runtime ABI remains success-only in Direct v1. `errors` and `reject`
RuleDrafts are retained, digested, delivered to Builder and packaged as design
semantics, but they are not claimed as dynamically assured by this gate and
cannot satisfy the two-rule coverage plan. Package fidelity includes the fixed
known limit `error/reject behavior is not dynamically assured by Direct v1`.

No error response, exception envelope or Consumer-visible ABI is added. A
future contract change may add dynamic error assurance only through its own
plan and cross-child review; current release and Observe must not claim it.

## Preserved R1 closure

The following R1 requirements remain exact:

- the model output is `{tool_index, preconditions, transitions,
  postconditions, errors}` using closed RuleDraft/PredicateDraft/EffectDraft;
- framework derives tool surface, bindings, rule IDs and canonical local
  digest, and validates exact tool/citation/catalog ownership;
- `tool_semantics` receives the bounded evidence input edge;
- WorldRules cannot duplicate local rules; TaskRequirement cannot redefine
  them;
- Design, implementation contract, CandidateBuild Skill, Verifier/Judge input,
  package Rule IR and Registry cold-read carry/recompute the same closure;
- future Expand observes only the stable compiled local-rule value/digest;
  no Expand code is implemented;
- product changes remain limited to the six R1 product files, one existing
  Runtime Skill and three focused existing test files.

## Deterministic acceptance additions

In addition to every R1 test:

- reject missing/extra snapshot paths, nested/invalid values and lifecycle
  order different from reset/pre/invoke/post;
- evaluator tests cover each allowed predicate/effect operation and fail on
  missing binding, category mismatch, false selected predicate, wrong result or
  post-state, digest/rule-ID mismatch and `reject` selected for assurance;
- Modeling Gate selects the deterministic lowest applicable precondition and
  transition, and fails when either cannot be observed from the frozen step;
- Integration and Judge use separate traces; safe evidence contains no private
  values;
- package fidelity states the error/reject non-claim and Registry rejects
  altered rules, assurance IDs/digest or fidelity closure.

## True-boundary acceptance

After focused/full checks and independent check:

1. one fresh Luna ToolSemantics shard passes the exact revised contract;
2. a real CandidateBuild and offline install pass Integration, then a separate
   Judge trace passes `local_tool_semantics` for the frozen precondition and
   transition IDs; Observe is read after the terminal;
3. one fresh complete Direct request reaches Registry cold-read and safe
   terminal Observe before any Direct-complete claim.

Failure starts a new Diagnosis Record. No additional attempt, normalization,
model switch, public ABI expansion or later-child implementation is authorized
by R2.
