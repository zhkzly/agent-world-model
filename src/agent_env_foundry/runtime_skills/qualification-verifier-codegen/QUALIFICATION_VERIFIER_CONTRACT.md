# Qualification Verifier Project Contract

Write one standalone Python 3.12 uv project exposing the fixed factory:

```text
generated_qualification_verifier.release:make_verifier
```

The factory returns an object with one method:

```python
verify_transition(request: dict) -> dict
```

## Authority and visibility

The project is audit-only proposal code. It may read:

- frozen Expected TaskSemantics meaning;
- public schemas, ToolSpecs and documents;
- the read-only actor source/native-format view.

It must not see or import TaskSemantics source, outputs, tests or repair history.
It must not import/call the actor package, actor business functions or the Host
package as an expected-answer oracle.

## Exact request

The request contains exactly:

```text
capability_id
start_case_id
public_descriptor
public_trace
final_answer
before_instance_directory
after_instance_directory
```

It never contains a protected binding, TaskSemantics facts, checker, Task,
reference solution or verdict. Identify the native referent from the public
descriptor/trace. If that is impossible without a hidden ID, return a structured
unsupported failure; never guess or inspect TaskSemantics.

Every `public_trace` item has exactly `seq`, `tool_name`, `arguments`, and
`observation`. `observation` is the public ToolObservation returned by the
actor. A business refusal is an executed process: its observation has
`ok=false`, `data=null`, and a structured domain `error`. When a refusal
capability expects that error code, do not mistake `ok=false` for a missing or
failed process.

## Exact result

Return exactly:

```text
initially_satisfied: boolean
satisfied: boolean
required_effects_ok: boolean
collateral_ok: boolean
answer_ok: boolean or null
process_ok: boolean or null
report_values: object
failure_codes: unique string array
```

A satisfied result requires required effects and collateral to pass, all
applicable answer/process axes not to be false, and no failure codes.

`initially_satisfied` means that the entire Task goal would already pass for
the selected referent in the before state, before any public action, tool
observation, final answer, or process evidence is credited. It is not capability eligibility,
a workflow precondition, or a refusal condition. For example, an eligible
object still requiring a mutation is not initially satisfied; neither is a
query still requiring a public read and correct answer. Keep this value
independent from final `satisfied` so the Host can later reject trivial goals.

Compute each result axis from its own obligation. `required_effects_ok` asks
whether the intended outcome occurred; `collateral_ok` asks only whether
forbidden unrelated state changed; `answer_ok` checks the submitted answer; and
`process_ok` checks the required public calls/observations. A no-op may therefore
have `required_effects_ok=false` while `collateral_ok=true`. Never gate one axis
on another merely to make them match final `satisfied`.

For every `answer_fields` entry of the selected capability in
`EXPECTED_TASK_SEMANTICS.json`, independently derive the expected value from
native before/after state and the qualified public trace, return it under the
same field ID in `report_values`, and compare the submitted `final_answer`
against it. A capability with declared answer fields must not return an empty
`report_values`. Missing, wrong, or stale answers set `answer_ok=false` without
changing the other independently computed axes.

Read the two instance directories with independent standard/native readers.
`verify_transition` must be read-only. Do not write marker files, mutate state,
call public tools, restore snapshots or return a scalar reward.

## Project requirements

Include `pyproject.toml`, `uv.lock`, source and diagnostic tests. Declare every
dependency. Tests should cover supported success/no-op/wrong-target/collateral/
wrong-answer/process cases implied by the frozen expectations. Cover every
Taskable capability, its declared report fields, initial truth, expected
business refusal, and the no-op distinction between required effects and
collateral. Framework owns
lock/sync/build/test/source/import/factory checks and later physical mutation
evidence. The model must not write a qualification receipt or pass verdict.
