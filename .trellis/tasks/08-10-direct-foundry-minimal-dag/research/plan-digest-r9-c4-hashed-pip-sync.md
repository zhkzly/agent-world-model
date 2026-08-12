# Direct R9-C4 plan digest

- Child plan revision: R9-C4 framework-compiled hashed pip sync
- Five-file aggregate SHA-256:
  `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`
- Current parent plan digest:
  `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`
- Predecessor full-scope allow:
  `cross-layer-review-dec00ffe-complete-direct.md`

```text
d3034f514dcdcebcaf093c1e62a742766af4ce1d747f2b79de50a107770b3a61  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
886c3ecfacdbec1585e17ed501babe3b0b38cbfa201b576ec2717f9997625723  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
df7a7eb702c12c97044cb7704ef6bf4eb320f1aba0a58b497ac0be3cb94e50d3  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
779c7c0779515d1eb6455777be8316351741ded2b43ea7429b44e85854ec05f5  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
8a8d324e833beee78b7cfb9ca6624e15315a6895e228b4eef584c00b06a8509e  docs/direct-rewrite-execution-map.zh.md
```

The aggregate hashes the exact concatenation of those newline-terminated
`sha256sum` lines in order.

C4 changes only the framework-owned install transaction. A deterministic valid
wheel proof established that tested `uv 0.11.29` rejects
`uv sync --frozen --no-sources`; without `--no-sources`, frozen sync still
follows the remote artifact URL recorded in `uv.lock` instead of the admitted
flat wheel store. This is a static check failure, not a product terminal.

Framework therefore retains its canonical lock parser and exact hash/size wheel
admission, compiles the complete admitted closure into a temporary exact-pinned
requirements file with hashes, creates a fresh venv, and runs fixed
`uv pip sync --require-hashes --offline --no-index --find-links --no-build`.
The pip command never receives candidate metadata or source roots. A local
real-wheel probe proved this exact documented mechanism installs successfully
with no network.

This introduces no resolver service, downloader, index client, candidate
configuration, cache mutation, graph node or compatibility path. All graph,
Runtime, Judge, Package, Registry, Observe and future-child contracts are
unchanged. This record proves plan identity only.
