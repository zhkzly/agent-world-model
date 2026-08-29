# Checkpoint C1 shared materializer evidence

## Implemented boundary

- One `materialize_project(ProjectMaterializationInput, runtime_root, settings)`
  replaces the former actor/semantics-only `_prepare_runtime`.
- Actor, semantics, verifier authors, release verification and materialization
  share one canonical project identity: exact relative path, normalized mode and
  content digest.
- Materialization filtered-copies only bound project files, then runs the
  existing `uv sync --frozen --all-groups --link-mode copy`, origin checks and
  all declared forbidden-module probes.
- `prepare_release` continues to materialize/expose actor and semantics only.

## Real verifier handoff

The accepted B verifier raw author workspace was materialized directly:

```text
source: /tmp/foundry-s2-b3-reauthor-nuvmk933/verifier
accepted/materialized digest:
  a9784a74ec963d962a5b11c8b891d270863c8792faa1ba9a06e11fbeeddeeb0e
runtime: /tmp/foundry-s2-c1-live-web903zt/runtime/project
role: verifier
forbidden: generated_environment, generated_task_semantics, agent_env_foundry
```

The fresh locked runtime excluded Expected Semantics, Public Surface, verifier
contract, actor-view manifest, `actor-view/` and the old author `.venv`. The B
query/state/refusal/no-op/wrong-answer/missing-process matrix remained GREEN
after the identity refactor.

## Negative evidence

- Changed source rejects before copy/sync.
- Included symlinks reject; excluded author-runtime bytes are not copied.
- Copy-time source change is cleaned and attributed to the selected role.
- Verifier import leak is `VerifierDefect`, not Environment/Semantics success.
- No `_prepare_runtime`, second uv path, transport, cache, sandbox, receipt or
  Qualification runner was added.

This is C1 physical infrastructure only. It does not compare TaskSemantics with
the verifier, run Qualification cases, create evidence/receipt, publish a
release or implement S2.

Two independent read-only reviewers returned `ALLOW` after the first reviewer
blocked the fake semantics-as-verifier test and the corrected implementation
materialized the actual accepted B verifier.
