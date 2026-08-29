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

Every `ToolSpec` returned by `tools()` is a plain mapping with exactly the keys
`name`, `description`, Draft 2020-12 `input_schema`, and Draft 2020-12
`output_schema` — never a dataclass or object requiring attribute access. Every
invocation returns exactly:

```text
success: {"ok": true, "data": <schema-valid JSON>, "error": null}
failure: {"ok": false, "data": null,
          "error": {"code": str, "message": str, "details"?: JSON}}
```

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
self-contained Draft 2020-12 start/reset schemas under `docs/schemas/`.
Do not write `release.json`, `payload-manifest.json`, qualification receipts or
digests. The Host combines this project with the independently authored
TaskSemantics project and creates the sole EnvironmentRelease v2 descriptor.

## Project quality

Include meaningful package data, diagnostic tests, `uv.lock`, and all declared
dependencies. Tests must exercise multi-step state changes and a refusal with no
prohibited mutation. A dictionary response map, canned result, mock backend,
empty world, repository template, Task, verifier, reward, trajectory, MCP, HTTP,
or training-specific behavior does not satisfy this contract.
