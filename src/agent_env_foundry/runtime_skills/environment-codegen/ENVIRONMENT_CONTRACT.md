# Environment Candidate Contract

Build a complete uv-managed Python project. The project must be independently
usable from its workspace and must not depend on the foundry repository at
runtime.

## Public environment surface

Expose the fixed `generated_environment.release:make_environment` factory. The
factory receives one caller-owned instance directory and returns an object
implementing:

```python
reset(start: dict | None = None) -> JSONValue
tools() -> tuple[ToolSpec, ...]
invoke(tool_name: str, arguments: dict) -> ToolObservation
close() -> None
```

The same project also exposes the fixed protected entrypoint:

```python
generated_environment.release:read_state(instance_directory) -> JSONValue
```

`read_state` reads real persistent bytes without mutation and returns a
deterministic, task-neutral state projection. It does not declare capabilities,
goals, answers, checkers or rewards and is never a public Agent tool.

Every `ToolSpec` returned by `tools()` is a plain mapping with exactly the keys
`name`, `description`, Draft 2020-12 `input_schema`, and Draft 2020-12
`output_schema` — never a dataclass or object requiring attribute access. Every
invocation returns exactly:

```text
success: {"ok": true, "data": <schema-valid JSON>, "error": null}
failure: {"ok": false, "data": null,
          "error": {"code": str, "message": str, "details"?: JSON}}
```

`output_schema` describes only the value inside a successful observation's
`data` field. It must never describe or repeat the outer `{ok,data,error}`
ToolObservation envelope; that envelope is fixed and validated by the Host.

Tool outputs must be structured and machine-addressable so a returned value can
be passed to a later tool. Do not hide identifiers or state facts in prose.
Every emitted public leaf in a reset result or successful ToolObservation
`data` must be explicitly described along its complete schema path. A bare
`{"type":"object"}`, an object property without nested `properties`, or an
array without an `items` schema cannot authorize its hidden descendants. Use
self-contained schemas that type the actual identifiers, timestamps, statuses,
relationships and other values the public Agent may read or reuse.

## State and reset

- `reset(None)` creates a meaningful package-owned default world.
- The reset result is the Agent's initial observation, not a dump of every
  public fact in native state. It may expose stable discovery anchors and the
  context needed to choose a public read, but it must not already contain the
  complete answer tuple of an accepted query/read Requirement. A query whose
  final answer can be copied entirely from reset is not a taskable public read;
  keep those answer values behind the appropriate public tool instead of
  requiring a redundant tool call in a later checker.
- The public start schema and reset implementation provide enough legal
  reset-only beginning situations for every accepted workflow precondition to
  be reachable. A workflow that begins from an intermediate business state
  (for example an already submitted item awaiting review) must be constructible
  by a declared reset input or coexist in the default world; do not use hidden setup
  tool calls, native writes, or snapshot restoration. These are reusable world
  regimes derived from the frozen Requirements, not hard-coded downstream Tasks.
- `reset` returns that public reset observation directly, never wrapped in the
  invocation `ok`/`data`/`error` record. Every reset result must validate
  against the release's published `reset_observation_schema`.
- Factory construction attaches the caller-owned instance and allocates only
  implementation resources; it does not initialize or reset domain state.
  Domain-state construction happens only when the caller explicitly invokes
  `reset`.
- Use real native persistent state under the supplied instance directory, such
  as SQLite or ordinary files appropriate to the selected world.
- Separate instance directories are independent.
- Successful state-changing tools perform real native mutations.
- Business refusals have stable domain error codes and perform every declared
  prohibited mutation exactly zero times.
- `close()` releases resources without deleting committed state.

## Actor-project handoff

Produce only the actor uv project. Use the fixed
`generated_environment.release:make_environment` factory and publish the
self-contained Draft 2020-12 start schema at `docs/schemas/start.json` and reset
observation schema at `docs/schemas/reset.json`. These exact mechanical paths
let the Host stage one unambiguous public surface; schema meaning remains the
Builder's domain decision.
Use the fixed `generated_environment.release:read_state` protected entrypoint
and publish its self-contained schema at `docs/schemas/state.json`. Every
persistent entity/relation needed to distinguish real state transitions must be
observable there, with deterministic ordering where collections are unordered.
Do not write `release.json`, `payload-manifest.json`, conformance receipts or
digests. The Host creates the sole EnvironmentRelease/3 descriptor.

## Project quality

Include meaningful package data, diagnostic tests, `uv.lock`, and all declared
dependencies. Tests must exercise multi-step state changes and a refusal with no
prohibited mutation. The diagnostic matrix must execute every public tool at
least once on a representative real success or refusal and validate the full
returned envelope against the fixed ToolObservation rules. For a success,
validate `observation["data"]` against the exact ToolSpec's `output_schema`; for a
refusal, validate the fixed error shape. Checking selected business fields
without schema validation is insufficient. A dictionary response map,
canned result, mock backend, empty world, repository template, Task, verifier,
reward, trajectory, MCP, HTTP, or training-specific behavior does not satisfy
this contract.

For native identifiers and state projections, tests must compare the structured
value with independent backend truth (for example the actual database row,
filesystem bytes, or native command result). Schema self-validation and
round-tripping the same parser do not prove that an identifier is exact.
