# Qualification Native-Audit Project Contract

Write one standalone Python 3.12 uv project exposing:

```text
generated_qualification_verifier.release:make_verifier
```

The factory returns an object with:

```python
verify_transition(request: dict) -> dict
```

## Authority

This is an audit-only native-state reader. It may see frozen Expected
TaskSemantics meaning, public schemas/ToolSpecs, and the read-only actor
source/native-format view. It must not see or import TaskSemantics source,
outputs, tests, or repair history. It must not import/call the actor package or
the Host package as an oracle.

## Request

The request contains exactly:

```text
capability_id
start_case_id
public_descriptor
public_trace
before_instance_directory
after_instance_directory
```

It never contains protected bindings, TaskSemantics facts, final answers,
checkers, Tasks, reference solutions, or verdicts. Resolve the intended native
referent from the public descriptor and trace. If that is impossible without a
hidden identifier, return a structured failure instead of guessing.

The public trace may be empty for a physical no-op case. When the public
descriptor already identifies the selected referent, an empty trace must not
turn that referent into `UNRESOLVED`. Evaluate the unchanged before/after state:
the required effect may be absent, while `collateral_ok` remains independently
true when no prohibited native state changed. Diagnostic tests must cover this
case for every state-changing capability.

Every trace event has `seq`, `tool_name`, `arguments`, and the exact public
`observation`. Trace may identify the selected attempted operation, but this
verifier must not become a second public-answer or process evaluator.

## Result

Return exactly:

```text
required_effects_ok: boolean
collateral_ok: boolean
failure_codes: unique string array
```

`required_effects_ok` states whether the capability's required native relation
holds across before/after for the selected referent. `collateral_ok` states
whether forbidden unrelated native state changed. Keep the two axes
independent. Use failure codes only for native-state audit diagnostics.

Do not derive final answers, `report_values`, public process truth, scalar
rewards, or a pass verdict. The Host validates public AnswerField sources, and
TaskSemantics evaluates public process/final-answer truth.

The verifier must be read-only. Do not write marker files, mutate instances,
call public tools, or restore snapshots.

## Project requirements

Include `pyproject.toml`, `uv.lock`, source, and focused diagnostic tests for
the required-effect and collateral rules of every Taskable capability.
Framework owns lock/sync/build/test/source/import/factory checks and the final
Qualification verdict.
