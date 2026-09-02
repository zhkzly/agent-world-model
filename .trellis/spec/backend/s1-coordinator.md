# S1 EnvironmentRelease/3 Coordinator Contract

## Scope

Use this contract for the sole direct Python path from one natural-language
Need to one cold EnvironmentRelease/3. S1 publishes an executable world; it
does not generate or qualify Tasks.

## Signature and order

```python
generate_environment(
    need_text: str,
    *,
    config: GenerationConfig,
) -> Released | NotReleased | Unsupported
```

```text
Need preservation
-> Research / Development Brief
-> actor Builder
-> public + protected-state surface freeze
-> environment conformance
-> EnvironmentRelease/3 publication
-> ZIP + cold verification/preparation
```

There is no v2 fallback, semantics-author branch, task-case Qualification or
provisional Release.

## Contracts

- Preserve `NeedRecord.original_need` exactly.
- Build one standalone uv project with public `make_environment` and protected
  task-neutral `read_state` entrypoints.
- Public behavior remains `reset / tools / invoke / close` over real persistent
  state.
- `read_state` is deterministic, schema-valid, read-only and invisible to an
  acting policy.
- Conformance binds exact actor bytes, ToolSpecs, start/reset/state schemas,
  task-free Host-executed diagnostic traces, physical replay/persistence/
  isolation evidence and cold package bytes.
- Any stage failure returns a typed non-release outcome and emits no later
  artifact.
- CapabilitySpecs, TaskSemantics, answer fields, Task checkers, witnesses and
  rewards are forbidden S1 output.

## Failure matrix

| Condition | Required result |
| --- | --- |
| empty or malformed Need | `NotReleased(invalid_need)` |
| Research cannot close | typed Research failure; no Builder |
| actor build/test/lock fails | Environment or Infrastructure; no conformance |
| public/state surface invalid | Environment defect; no publication |
| diagnostic tool coverage/outcome/state effect/replay invalid | Environment defect; return to Builder before publication |
| reset/replay/persistence/isolation/readback fails | conformance failure; no publication |
| receipt/layout/ZIP/cold prepare fails | Publication failure; no released ID |
| old format requested | unsupported; no conversion |
| downstream Task proposal fails | not an S1 event; Release remains valid |

## Required evidence

- Need wrapping equivalence and parent-workspace immutability;
- actor/state input and digest mutations;
- public versus protected visibility tests;
- real reset/invoke/persistence/isolation/readback;
- Builder-authored domain arguments executed twice by the Host with complete
  tool success coverage, refusal atomicity and per-step protected-state checks;
- readback no-mutation and close/reopen stability;
- filesystem/Git plus SQLite cold relocation;
- old TaskSemantics/Verifier production references equal zero.
