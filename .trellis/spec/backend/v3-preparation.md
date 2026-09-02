# EnvironmentRelease/3 Preparation Contract

## Scope

Preparation accepts only a canonical EnvironmentRelease/3 and materializes one
actor project. It exposes a public actor proxy and a physically separate
protected state-snapshot proxy; it does not generate Tasks or install a
release-local semantics/verifier project.

## Session boundary

```python
prepared = prepare_release(release_path, cache_root, settings=...)

with prepared.open(instance_directory) as session:
    session.actor.reset(...)
    session.actor.tools()
    session.actor.invoke(...)

snapshot = prepared.read_state(instance_directory)  # Host/checker only
```

- `open` never resets or deletes the caller-owned instance.
- Acting code receives only `ActorProxy`.
- `read_state` is callable only through the Host-owned protected projection.
- Public inputs and artifacts contain no protected factory, native path or
  snapshot value.

## Physical contracts

- Verify release descriptor, manifest, receipt, actor digest, schema digests,
  modes and paths before sync.
- Materialize identity-bound actor files only and run real
  `uv sync --frozen --all-groups --link-mode copy`.
- Launch project code only in its `.venv/bin/python -I -B`; scrub ambient
  Python environment and keep stdout wire isolation.
- Verify installed module origin and project bytes at every open/read.
- Validate reset results and every ToolObservation against sealed schemas.
- Validate protected state against `state.json`, repeat deterministically and
  reject any instance-tree mutation caused by reading.
- Preserve close/reopen state and keep simultaneous releases with identical
  package names non-aliased.
- ZIP extraction restores explicit directory entries and Unix modes.

## Failure ownership

| Condition | Result |
| --- | --- |
| malformed/tampered/old release | contract rejection before sync |
| source/copy/runtime digest mismatch | Environment defect |
| frozen sync or runtime resource unavailable | Infrastructure failure |
| actor startup/public invocation failure | Environment defect |
| protected read startup/schema/mutation failure | Environment defect |
| wire seq/shape/timeout failure after healthy use | typed Infrastructure or Environment failure |

## Forbidden

- semantics or verifier runtime;
- `TrustedProxy` capability/evaluate API;
- Host import or `sys.path` mutation;
- public exposure of protected state;
- implicit reset on open;
- compatibility reader or format switch.
