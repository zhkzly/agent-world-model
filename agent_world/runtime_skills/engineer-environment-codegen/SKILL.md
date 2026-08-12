---
name: engineer-environment-codegen
description: Write the candidate Materializer and five-operation Runtime from frozen inputs.
---

Write only `materializer.py`, `runtime.py`, `pyproject.toml`, `uv.lock`, and
`LICENSE` as the candidate source closure requested by the frozen implementation
contract. Prefer the standard library for the first proof. Ordinary registry-wheel
dependencies are allowed only when they are represented exactly in both
`pyproject.toml` and `uv.lock`; framework admission decides whether their bytes
exist. Never install, download, select an index, choose a hash, or claim a wheel
is available. Build backends, indexes, URLs, paths, editables, Git, and source
distributions are forbidden.
The Materializer exact-echoes its request in the contract's ordered response for every
declared family and difficulty schema. Implement all typed world/shared/local rules and
declared tools; never assume a first family/tool.
The Runtime implements the exact handshake, reset, invoke with framework-provided
idempotency keys, private snapshot, and acknowledged close shapes. Implement the
frozen `tool_semantics` section exactly: after reset, every snapshot state is
`{"tools": {tool_name: {result_field: json_value}}}` for every declared tool and
result field; preserve it across the required reset -> pre-snapshot -> invoke ->
result -> post-snapshot lifecycle. The snapshot is framework-private: never put
its values in candidate completion text or any public response. `errors` and
`reject` semantics remain design/package facts only in Direct v1; do not invent
an error response ABI. Never write package, manifest, hash, verifier, Judge,
reward, termination, or release facts.
Return only this bounded JSON completion after writing source:

```json
{"summary":"...","self_checks":[{"name":"...","observed":"passed","note":"..."}],"known_limits":["..."]}
```
