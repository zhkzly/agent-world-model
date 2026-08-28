# TaskSemantics Project Contract

Write one standalone Python 3.12 uv project implementing a release-local,
read-only `TaskSemantics` factory. The project is proposed code; Host execution
and Qualification alone decide whether it is usable.

## Immutable inputs

- `EXPECTED_TASK_SEMANTICS.json`: accepted Requirement dispositions and the
  expected capability/workflow/composition/condition relations.
- `PUBLIC_SURFACE.json`: public schemas, ToolSpecs, real public probe facts and
  the exact candidate-view manifest.
- `candidate-view/`: read-only actor source/native format documentation exposed
  only after expected semantics were frozen.

Do not edit these files. Do not copy Host digests, manifests, run IDs or verdicts
into generated semantic records.

## Required factory surface

Expose one `module:factory` that returns an object with exactly these methods:

```python
start_cases(seed: int, limit: int) -> tuple[StartCase, ...]
inspect(instance_directory: Path) -> JSONValue
capabilities() -> tuple[CapabilitySpec, ...]
enumerate_bindings(capability_id: str, facts: JSONValue) -> tuple[BindingCandidate, ...]
evaluate_atom(request: AtomCheckRequest) -> AtomCheckResult
evaluate_condition(request: ConditionCheckRequest) -> ConditionCheckResult
```

The JSON shapes are those defined by `agent_env_foundry.semantics`. The generated
project must encode the same fields without importing the Host package at
runtime; its lockfile must contain every dependency it uses.

## Separation and state rules

- The semantics project must not import the actor package or call actor business
  functions as an answer oracle.
- `inspect`, `capabilities`, `enumerate_bindings`, `evaluate_atom` and
  `evaluate_condition` must not mutate the instance directory.
- Native state may be decoded with independent standard readers appropriate to
  the generated representation.
- Protected bindings/native fields must never be copied into public descriptors,
  labels or rendering text.
- `public_tool` facets and conditions require an exact ToolSpec output-schema
  pointer and must agree with real public facts.
- Composition and condition branches may only use the frozen Requirement,
  workflow and capability relations.
- Return structured values; do not return scalar rewards or terminal verdicts.

## Project requirements

The project must include `pyproject.toml`, `uv.lock`, source, and diagnostic
tests. `uv sync --frozen --all-groups`, build, tests, and Host schema/import/
no-mutation checks must pass. A model-written success message is never evidence.
