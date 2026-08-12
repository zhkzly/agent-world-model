# Plan digest - difficulty closure C2

- Lineage: `complete-v1-difficulty-closure`
- Revision: C2, revision 1 after Direct critic block `baddd746...`
- Aggregate SHA-256:
  `734a274a6b3092f0b526530fd264d105dd65bf068b1aee74fe67984219d7f117`
- Predecessor parent allow: `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`
- Predecessor Direct block: `cross-layer-review-baddd746.md`
- Scope: close the framework-owned difficulty producer/consumer contract across
  Direct, Expand, package and Consumer planning; Repair and runtime model routes
  are unchanged.

The aggregate is SHA-256 over the exact concatenation of these standard
newline-terminated `sha256sum` lines in order:

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  .trellis/tasks/08-11-foundry-complete-v1/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  .trellis/tasks/08-11-foundry-complete-v1/design.md
906437a5b7eb1f3c2303c3cd536fd66a391b57ffdc3340a21cc43a4cbbb53223  .trellis/tasks/08-11-foundry-complete-v1/implement.md
1588121e64142a1c7dfc1bf4b4bedfe89aba0180da4f96dbf2551ef52fee1001  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
21296fdc71f3e10999af344eff073b9cda0858f1261b6a81a1195434b5e77962  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
94a76a0f6318728a42daffc1d2480c0abb5b6ad49dbe24780062b32016318e4c  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
6c841542e2228fa3fef41f5fa51c9da229947dad690cd700e24d4afa2c85c644  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
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

C2 defines one semantic producer and one framework compiler: Curriculum
proposes ordered finite dimensions/levels; framework compiles the per-family
schema. TaskRequirement, candidate protocol, Integration, Judge, package,
Expand child Design and Consumer reuse it. It adds no graph node, schema
service, scheduler, second Judge/Registry or compatibility path.

This record proves planning identity only. It does not authorize implementation
or prove Direct, Repair, Expand, Consumer, SFT/RL or product completion.
