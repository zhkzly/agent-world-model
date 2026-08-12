# Parent plan digest — Direct contract closure C6

- Lineage: `complete-v1-direct-contract-closure`
- Revision: C6, first revision after the independent Direct implementation block
- Eighteen-file aggregate SHA-256:
  `6e3d4c9cebc4836ce7a872cce11e7fe687e1d3d6154d0ce77460371811186f0e`
- Embedded Direct digest:
  `ed917488dc2ba845c7577a4bf7770c66ff4691a6412650fa2af8a55a9e8fe570`

```text
5d54acb103f6752f2543b683201643ca7c5c0b8af802f6fb54ccce74c657a8e2  .trellis/tasks/08-11-foundry-complete-v1/prd.md
2e993c838294a0ceae24a79553caf6c0d5d74e88f097960b1cfab73f09402a9d  .trellis/tasks/08-11-foundry-complete-v1/design.md
bd46f2b334c4d3d8783bfa8be0a4e75f44f8a3d76a683d9c0999d8e6c1a4aaec  .trellis/tasks/08-11-foundry-complete-v1/implement.md
e66db882234cf501290a82855ca9618962589be1ab8bd1041a6c0bae053da1e3  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
523731535e3bb07a0d6c8b0907706ca6b744738ec1ca8789456ed664a4953e6d  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
5fd12d2cb336da78f67b5da8679622f91d444243a7720ecd06bfdc776cc0a132  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
0c339420a889eacf51dd65a9531d7619230bdb0c44a82d9aa1fa8faa87ede299  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
c134d9dae6cdc30e32c4061b61823be9007e0324441fd20ed7acb7069321ff47  .trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c5-check-block.md
1c089063e35ec56260aac0aa2d64a3ae0856ef6df0767eecb10063830da4983c  .trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c6-contract-closure-plan.md
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

The aggregate hashes the exact concatenation of those newline-terminated
lines. C6 strengthens Direct's existing shared handoffs and does not implement
or redesign Repair, Expand or Consumer. This record proves plan identity only.
