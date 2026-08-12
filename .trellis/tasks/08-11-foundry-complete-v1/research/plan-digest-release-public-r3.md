# Plan digest - release-public-handoff R3

- Lineage: `release-public-handoff`
- Revision: R3, dispatch-amendment revision 2 of 2
- Aggregate SHA-256:
  `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`
- Predecessor dispatch review:
  `cross-layer-review-b34be669-terra-dispatch.md` (`block`)
- Scope: planning-only development-worker dispatch selection.

R3 addresses the block by making research/critic, implementation and check
spawns explicit in the parent and every child:
`--provider codex --model gpt-5.6-terra`. The Trellis agent profiles are also
pinned to Terra, but explicit dispatch remains required and auditable. The
runtime product `direct`/`agent` route table, Search/Fetch/Extract provider,
graph contracts, public APIs, ownership, persistence, validation, repair,
release, Expand, Consumer and Observe semantics are unchanged.

The aggregate is SHA-256 over the exact concatenation of these standard
newline-terminated `sha256sum` lines in order:

```text
5ed8e751b1497c2f7153e89f13350fe3f95a3569ab7baa54410035a80efd9b73  .trellis/tasks/08-11-foundry-complete-v1/prd.md
82c65a90809c77accfd825912d7942d0cffe044d191311a856903b0afae5a2e2  .trellis/tasks/08-11-foundry-complete-v1/design.md
fc96298ec3480d268b8bc29f6f12af2e984669f7d21d554dce9f45ddf150712c  .trellis/tasks/08-11-foundry-complete-v1/implement.md
03573288978f3c52d92bb85e9265b00155c22bae1113b2197695a3437c8c3e88  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
b27f003fdd040b5539a04cbefea4d0792950201cfcf92f52059d227dee01c77e  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
35821202337bf46e8e98bf5eb48a512c1b5d6a1ea80e1c12e26e869133ad983b  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
b88628cc87418bfde175bb4d8e411d64e8a52928ab67640dfc4e9bad110a43e6  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  .trellis/tasks/08-11-foundry-bounded-repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  .trellis/tasks/08-11-foundry-bounded-repair/design.md
f6445cb6ba97b0e32280f30718f8c28bdc51d4514771cd48418dd007d50aedc1  .trellis/tasks/08-11-foundry-bounded-repair/implement.md
d4fe8cd03700d7866e499d8ba1ff0f43cdf66bcdaefbb7816c3361b7e2a22482  .trellis/tasks/08-11-foundry-expand-multiparent/prd.md
77e68fc18e3d5213c0effacbd9938a7a484e6fa2720cf9070f0f4e177ff3d816  .trellis/tasks/08-11-foundry-expand-multiparent/design.md
f810e99ade9091ea18c2f11d2b8066e306d809282ef8cc792d32b5ebbe715d79  .trellis/tasks/08-11-foundry-expand-multiparent/implement.md
a0f05fbe7ecfc11c1e5f88f39478d65048b1a0fcd211df05c71f7d641b40c318  .trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
528d10a7b02b14f63dd8bd307c06a4926dae6da40e5887fdf7009064be789ed5  .trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
a28874c73080713f4acfa7fa65544a3cb37c54a545c728d7338b4a080c0c8bb3  .trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

Deterministic pre-review checks show no development Spark instruction in the
parent/child dispatch surface and no product diff under `agent_world/`,
`tests/`, `config/`, `pyproject.toml`, or `README.md` relative to the clean
baseline. This record is not implementation, runtime evidence or product
completion.
