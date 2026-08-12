# Plan digest — release-public-handoff R1

- Lineage: `release-public-handoff`
- Revision: R1
- Aggregate SHA-256:
  `b34be66905d2e1f1690278da03aeddcd1d24191581ff44a6c24619c67462fd69`
- Predecessor review:
  `cross-layer-review-42ac2771.md` (`needs_human`)
- Decision source: user confirmed the three requested product policies on
  2026-08-11.

The digest follows the algorithm in parent `implement.md`: hash each raw file
in the listed order, emit standard newline-terminated `sha256sum` lines, then
SHA-256 their exact concatenation. This record and review/manifests are not
inputs.

```text
2f4b2df8b249d3532a38479cb7d40adc8417b5bc358f1b621b83c9faf7c5c973  .trellis/tasks/08-11-foundry-complete-v1/prd.md
9736b6854a0a858826c3d1575e05fac24ec41a14308f7107e301735ac60e12e2  .trellis/tasks/08-11-foundry-complete-v1/design.md
d090e08349444b6a6024b0adde0b653d722ec62b8ed05e4f3e8f630c88303817  .trellis/tasks/08-11-foundry-complete-v1/implement.md
eb375b4b8ecc26964301f449647ddbb78237f98d7be4f4a05ff94b502e6c7932  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
b27f003fdd040b5539a04cbefea4d0792950201cfcf92f52059d227dee01c77e  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
35821202337bf46e8e98bf5eb48a512c1b5d6a1ea80e1c12e26e869133ad983b  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
7145915fd5ad0d828f302c76260e7edebc2846e39163213a460283082842c5c2  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  .trellis/tasks/08-11-foundry-bounded-repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  .trellis/tasks/08-11-foundry-bounded-repair/design.md
d0a5fe43ae96412dded179792cfa0b1b31f9a8932b85b0fd019d84be183d2344  .trellis/tasks/08-11-foundry-bounded-repair/implement.md
d4fe8cd03700d7866e499d8ba1ff0f43cdf66bcdaefbb7816c3361b7e2a22482  .trellis/tasks/08-11-foundry-expand-multiparent/prd.md
77e68fc18e3d5213c0effacbd9938a7a484e6fa2720cf9070f0f4e177ff3d816  .trellis/tasks/08-11-foundry-expand-multiparent/design.md
c3a3e2b99abb817a43bfed0f6deb6b512f4eee4682796e1071980db8243eb082  .trellis/tasks/08-11-foundry-expand-multiparent/implement.md
a0f05fbe7ecfc11c1e5f88f39478d65048b1a0fcd211df05c71f7d641b40c318  .trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
528d10a7b02b14f63dd8bd307c06a4926dae6da40e5887fdf7009064be789ed5  .trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
3dec3490e627f37b0aae02ec54c8f30516b14cee08289a8a6b81ab302d285067  .trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

Only parent, Expand and Consumer planning files changed from the predecessor
lineage. Direct and Repair inputs remain unchanged. This digest proves planning
identity only; it is not implementation, live execution, package release,
Expand diversity or SFT/RL evidence.
