# Plan digest - trusted wheel ingestion C3

- Lineage: `complete-v1-wheel-ingestion`
- Revision: C3, revision 1 after the pre-execution installer contradiction
- Aggregate SHA-256:
  `d39632e88ff13a1b447e490beb379540fe22dcb839690cfdbf6138f114d1efe5`
- Predecessor parent allow: `734a274a6b3092f0b526530fd264d105dd65bf068b1aee74fe67984219d7f117`
- Scope: correct only the shared Direct package-install boundary; Repair,
  Expand and Consumer retain the exact released-package handoff and do not
  gain a second installer or dependency authority.

The aggregate is SHA-256 over the exact concatenation of these standard
newline-terminated `sha256sum` lines in order:

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  .trellis/tasks/08-11-foundry-complete-v1/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  .trellis/tasks/08-11-foundry-complete-v1/design.md
906437a5b7eb1f3c2303c3cd536fd66a391b57ffdc3340a21cc43a4cbbb53223  .trellis/tasks/08-11-foundry-complete-v1/implement.md
743b0403360a8732f0554a6cb39379d80745da2e6a319d6dbfc7f45391e90ab7  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
99279bfa4cb038d3fc1db8e8677bdaaabd6d4c3afc6ed115a638ed2397f48121  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
ecf3990c5cca78bd5126ed22794f05f2e036e0c690546f01de3f642622bc11dc  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
ae5de1997f8b8ca72250a8883d9e0d0811c95554fea4e749887a5d16fe3d6bf1  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
95fa444c3e8519df90cac7680a1ce9c256100dd47a84b493462d28d843b57149  .trellis/tasks/08-11-foundry-bounded-repair/prd.md
cbfee29d2392182eb908495e6d23652a508a1c33dea4f2c0cacff3659a1b1af5  .trellis/tasks/08-11-foundry-bounded-repair/design.md
f6445cb6ba97b0e32280f30718f8c28bdc51d4514771cd48418dd007d50aedc1  .trellis/tasks/08-11-foundry-bounded-repair/implement.md
bf10d6b5c7d44a810e97c28499663fc150b1d3abd5f7fec5f30586605a289cca  .trellis/tasks/08-11-foundry-expand-multiparent/prd.md
fc55bb580858493222a21c0482e247faba85095bbbb5cd66a1149ef0dc41cefd  .trellis/tasks/08-11-foundry-expand-multiparent/design.md
d60a0534bb77267248605b4bedf0dcd4525b129e7e047c2d85c87440430dad9f  .trellis/tasks/08-11-foundry-expand-multiparent/implement.md
fbb3b46ca05c31047029e6a1c68e215f2fd7edd47d68bf363c4c7290324d1038  .trellis/tasks/08-11-foundry-consumer-sft-rl/prd.md
f8bd06ed66cfdcd0abf03606ff2573ae10dea51a68966e922b3602b808c6369d  .trellis/tasks/08-11-foundry-consumer-sft-rl/design.md
490d985ed2915430167722c6673ddd11fe84de2ec7686c1439e723d472265cd8  .trellis/tasks/08-11-foundry-consumer-sft-rl/implement.md
```

Only four Direct planning files changed. The shared package and Registry
contracts, future Repair invalidation, Expand re-entry, Consumer cold-read,
model routes, graph topology and authority ownership are unchanged. This is a
planning-identity record, not implementation or product evidence.
