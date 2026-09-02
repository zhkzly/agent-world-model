# Task Checker Project Contract

Build one standalone uv-managed Python project for exactly the candidate in
`CANDIDATE_TASK_CONTRACT.json`. `PROPOSAL_EVIDENCE.json` is one real positive
example and provenance, not a reference trajectory that future attempts must
copy.

Expose exactly:

```python
generated_task_checker.release:check_task(request: dict) -> dict
```

The request contains exactly:

```text
format: task-check-request/1
task_id
before_state
after_state
public_trace
final_answer
```

Return exactly:

```text
format: task-check-result/1
passed: bool
goal: bool
answer: bool
required_effects: bool
forbidden_effects: bool
process: bool
reason_codes: sorted unique string[]
```

`passed` is the conjunction of all five axes. A passing result has no reason
codes; a failure has at least one. The checker is the sole Task semantic
authority after its source is frozen.

Implement task-specific ordinary Python over the supplied JSON values. Check
the requested entity and outcome, the exact answer, required changes, forbidden
collateral, and only genuinely required public process evidence. Accept any
valid execution that satisfies those predicates; never require equality with
the proposal trace, exact call count, incidental ordering, or one reference
answer serialization.

The checker is pure and deterministic. It must not import or execute the actor,
the Host package, TaskSemantics, another verifier, an LLM, network, subprocess,
filesystem, environment variables, wall clock, randomness, or mutable global
state. It receives all authority through the request.

Proposal evidence demonstrates one feasible binding, not the only valid entity
choice. If the public instruction says to select or choose a qualifying entity,
derive that binding from the evaluated request's public trace and final answer,
then check its preconditions and effects in before/after state. Do not embed an
identifier selected only by proposal evidence as a source constant. An exact ID
may be constant only when the public instruction itself names that ID.

Write meaningful tests for the supplied positive example, an unchanged no-op
and a schema-valid wrong answer. Add ordinary task-specific semantic unit tests
when useful, but do not create an adversarial execution pipeline or additional
Task admission categories. Tests are diagnostic; Host checks decide
acceptance.

Do not write a TaskContract, TaskPack, receipt, reward, witness, assessment or
corpus artifact. Do not edit the immutable input files.
