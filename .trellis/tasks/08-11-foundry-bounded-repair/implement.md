# Foundry bounded automatic repair — implementation plan

1. Record the exact completed Direct commit and shared contract digest. Verify
   the clean worktree and legacy-reference firewall.
2. Add this task's current parent requirements and source/spec references to
   `implement.jsonl` and `check.jsonl`.
3. Close serialization and Node re-entry details against the actual Direct
   graph implementation; update this design if any producer/consumer changes.
4. Dispatch a fresh read-only critic with explicit
   `--provider codex --model gpt-5.6-terra`. Implement only after an
   exact-digest `allow` is present in both manifests.
5. Dispatch implementation with explicit
   `--provider codex --model gpt-5.6-terra`, then implement Finding
   owner/condition re-verification, `RepairDeclaration`,
   `RepairLedger`, deterministic target resolution, budget/no-progress checks,
   `RepairDecision`, append-only `WorkInvalidation` and graph re-entry in the
   smallest existing modules.
6. Add safe Observe revision projection and Product Alignment Checkpoints.
7. Run deterministic routing/invalidation regressions and the full Direct test
   suite.
8. Run one real negative-to-repaired proof without manual Artifact edits,
   fixture success paths or weakened validators; read Observe at both
   terminals.
9. Dispatch check with explicit
   `--provider codex --model gpt-5.6-terra`, resolve only
   in-scope mechanical findings, and freeze the exact commit/evidence for the
   Expand child.

Stop and revise the plan if implementation requires more than one-hop routing,
a new authority, a shared contract change or an extra retry mechanism.
