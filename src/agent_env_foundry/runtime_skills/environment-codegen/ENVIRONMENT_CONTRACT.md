# Environment Candidate Contract

Build a complete uv-managed Python project. The project must be independently
usable from its workspace and must not depend on the foundry repository at
runtime.

## Public environment surface

Expose a standard factory named by `release.json`. The factory receives one
caller-owned instance directory and returns an object implementing:

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

## Release envelope

Write `release.json` and `payload-manifest.json` at the project root. The host
loader parses both strictly: missing fields, guessed alias field names and
unknown extra fields are rejected, never normalized. `release.json` contains
exactly these fields and nothing else:

- `format`: `"environment-release/1"`
- `canonicalization`: `"rfc8785"`
- `hash`: `"sha256"`
- `payload_manifest`: `"payload-manifest.json"`
- `payload_digest`: SHA-256 hex of the RFC 8785 canonical JSON bytes of the
  payload-manifest document
- `environment_factory`: the factory's `module:factory` import path
- `start_schema`: release-relative path of the start schema file
- `reset_observation_schema`: release-relative path of the reset-observation
  schema file

The digest in this example is a placeholder with the required shape; compute
the real value from your actual manifest bytes:

```json
{
  "format": "environment-release/1",
  "canonicalization": "rfc8785",
  "hash": "sha256",
  "payload_manifest": "payload-manifest.json",
  "payload_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "environment_factory": "generated_environment.release:make_environment",
  "start_schema": "docs/schemas/start.json",
  "reset_observation_schema": "docs/schemas/reset-observation.json"
}
```

The payload-manifest document is exactly `{"files": [records...]}` with no
other keys. Records are sorted by path and each record has exactly `path`,
`type`, `mode` and `digest`: `type` is `"file"`, `mode` is the integer
normalized file mode, and `digest` is the lowercase SHA-256 hex of the member
bytes. The manifest lists both named schema files (further members may be
listed the same way) and never lists itself or `release.json`. Digests below
are placeholders with the required shape:

```json
{
  "files": [
    {
      "path": "docs/schemas/reset-observation.json",
      "type": "file",
      "mode": 420,
      "digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    },
    {
      "path": "docs/schemas/start.json",
      "type": "file",
      "mode": 420,
      "digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    }
  ]
}
```

Both schemas are self-contained Draft 2020-12 documents that may reference
local fragments only; the start schema has an object root. The named factory
and schema files must be included in the project/build output.

## Project quality

Include meaningful package data, diagnostic tests, `uv.lock`, and all declared
dependencies. Tests must exercise multi-step state changes and a refusal with no
prohibited mutation. A dictionary response map, canned result, mock backend,
empty world, repository template, Task, verifier, reward, trajectory, MCP, HTTP,
or training-specific behavior does not satisfy this contract.
