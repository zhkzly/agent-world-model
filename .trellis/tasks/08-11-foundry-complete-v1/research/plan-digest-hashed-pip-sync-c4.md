# Parent plan digest - hashed pip sync C4

- Lineage: `complete-v1-hashed-pip-sync`
- Revision: C4 revision 1 after the tested C3 installer contradiction
- Aggregate SHA-256:
  `6e98efdd14d7ee57ce526ecbccb3c238418c12c4da3e7836b055bd6fbf65e929`
- Embedded Direct digest:
  `97dd80a73160ccf8895ed202186006a23eb44903fff4c72d272c8f87b250616c`

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  .trellis/tasks/08-11-foundry-complete-v1/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  .trellis/tasks/08-11-foundry-complete-v1/design.md
906437a5b7eb1f3c2303c3cd536fd66a391b57ffdc3340a21cc43a4cbbb53223  .trellis/tasks/08-11-foundry-complete-v1/implement.md
d3034f514dcdcebcaf093c1e62a742766af4ce1d747f2b79de50a107770b3a61  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
886c3ecfacdbec1585e17ed501babe3b0b38cbfa201b576ec2717f9997625723  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
df7a7eb702c12c97044cb7704ef6bf4eb320f1aba0a58b497ac0be3cb94e50d3  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
779c7c0779515d1eb6455777be8316351741ded2b43ea7429b44e85854ec05f5  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
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

The aggregate hashes the exact concatenation of those newline-terminated lines.
Only the four Direct planning files changed. Repair, Expand and Consumer retain
the same immutable Artifact/package/runtime handoffs and gain no installer or
dependency authority. This is planning identity, not product evidence.
