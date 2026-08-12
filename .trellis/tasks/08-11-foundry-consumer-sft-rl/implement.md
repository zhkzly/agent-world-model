# Foundry Consumer SFT and RL proof — implementation plan

1. Record exact upstream commits, package refs and Runtime/Materializer/public-
   private contract digests. Verify at least one selected Expand package through
   Registry again.
2. Curate task manifests and close exact serialization/lifecycle details against
   the implemented package/runtime code, including reuse of the package's exact
   per-family difficulty schema and validator.
3. Dispatch a fresh read-only Consumer/public-boundary critic using explicit
   `--provider codex --model gpt-5.6-terra`; implement only after exact-digest
   `allow`.
4. Dispatch implementation with explicit
   `--provider codex --model gpt-5.6-terra`, then implement immutable Suite
   resolution from full released
   `EnvironmentPackageRef`s, cold receipt/package/manifest revalidation and a
   current Registry `PackageUseAdmission`, plus a small framework-owned
   Consumer using the existing isolated Runtime protocol.
5. Implement allowlist public serializers, lifecycle cleanup, reward/
   termination verification, private Materializer-to-Runtime reset handoff and
   safe Observe projection.
6. Implement one SFT exporter and one reset/step online RL adapter over the same
   Episode API.
7. Run deterministic contract, reproducibility, restart, post-freeze
   quarantine/supersession, caller-reset rejection, concurrency, cleanup,
   digest and private-canary leak tests across API/SFT/RL/logs/Observe. Include
   two valid difficulty selections plus missing/extra/duplicate/reordered and
   unknown-level rejection before Materializer execution.
8. Run actual unknown-seed Episodes, export one real SFT example and complete
   one online RL-compatible Episode.
9. Remove/disable adapters in a verification checkout and prove Direct/Expand
   remain functional; prove Expand works with no capability feedback.
10. Dispatch check with explicit
    `--provider codex --model gpt-5.6-terra` and freeze final evidence
    for parent integration review.

Stop and revise the plan if implementation needs access to package source,
private evaluator state, a second reward owner, a trainer or a change to the
generation/release path.
