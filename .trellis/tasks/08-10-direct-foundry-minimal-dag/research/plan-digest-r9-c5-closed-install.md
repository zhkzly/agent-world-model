# Direct R9-C5 plan digest

- Child plan revision: R9-C5 closed install transaction
- Five-file aggregate SHA-256:
  `37988f7016afd19a1b0414e619b8e3c572e8f4ccd3ccc8a9f2bb0c9cda56bf1a`
- Current parent plan digest:
  `3c9098e3948727f5e4bd8eaa11e4243ee595c0365bfedda3d4b75db63a4030de`
- Predecessor review: `cross-layer-review-97dd80a7-complete-direct.md`
  (`block`)
- Revision count: first and final plan revision after that block

```text
e66db882234cf501290a82855ca9618962589be1ab8bd1041a6c0bae053da1e3  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
523731535e3bb07a0d6c8b0907706ca6b744738ec1ca8789456ed664a4953e6d  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
fa405100e4e6d5074a1b2bcc4f5fc6aa1bb5ada78d4c0e8b24b9fe20de723a86  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
31d0c718f48e42b6caa4b696d9064826387c29b6a3c767303bb3af031568b901  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
8a8d324e833beee78b7cfb9ca6624e15315a6895e228b4eef584c00b06a8509e  docs/direct-rewrite-execution-map.zh.md
```

The aggregate hashes the exact concatenation of those newline-terminated lines.

C5 addresses every C4 block item without changing architecture: it defines one
finite `AdmittedLockClosure` and exact post-install set equality; rejects
markers/extras/forks/multiple versions rather than becoming a resolver; runs
both uv commands from a fresh framework directory; adds `uv venv --no-project`
and `uv pip sync --allow-empty-requirements`; and updates active lineage gates.
Local tested-uv probes verified both the real wheel and empty stdlib commands.

No product code changed while producing C5. Existing partial C3 supply-chain
code remains unauthorized implementation evidence until a matching allow. This
record proves plan identity only.
