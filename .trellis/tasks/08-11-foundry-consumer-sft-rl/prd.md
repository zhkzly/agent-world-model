# Foundry Consumer SFT and RL proof

## Goal

Prove that exact released environments are genuinely usable downstream for SFT
and online RL through one isolated, public Episode contract, without coupling a
trainer or training feedback into Generation, Repair, Expand or release.

This is child 4 of `08-11-foundry-complete-v1`.

## Explicit dependency

- Hard dependency: the exact Registry package/Runtime/Materializer contracts
  frozen by the completed Direct child, including each task family's exact
  `DifficultySchema` digest.
- Final integrated acceptance additionally consumes at least one exact released
  package from the completed Expand child, preferably the multi-parent child.
- Record package refs, upstream commits and contract digests before critic
  review. Any public/private or reward/termination contract change expires this
  plan.

## Requirements

- Resolve exact released `EnvironmentPackageRef`s (id, version, package digest,
  manifest digest, Registry receipt and release-closure refs) into a
  `SuiteSnapshot`; mutable selectors are resolved only before the snapshot is
  committed.
- Before every new Episode, framework rechecks the selected exact package's
  current Registry record and persists a `PackageUseAdmission`. Quarantine,
  supersession, non-release or identity mismatch blocks startup without
  rewriting the Suite.
- Framework-owned Consumer materializes unknown-seed tasks and supervises one
  isolated Runtime process per Episode using package-relative execution.
- External Episode admission accepts only suite/package and task-selection
  fields. The caller cannot provide `initial_config`; framework obtains it from
  the exact MaterializerResult and carries it to Runtime in a private internal
  handoff.
- `EpisodeRequest.difficulty` is the exact complete ordered selection for the
  selected package's TaskRequirement. Consumer cold-reads that package schema
  and rejects missing, extra, duplicate, reordered or unknown levels before
  invoking Materializer; it does not define defaults or another difficulty
  domain.
- Public surface contains only PublicTask, observation, tool schema/action,
  public result/error, scalar reward, termination/truncation and safe episode
  identity.
- Full state, evaluator goal, verifier IR, sealed cases, source, release policy
  and private snapshots never reach the training caller.
- Reward and termination are computed/verified by framework-owned rules; an
  environment or training caller cannot award itself success.
- One SFT exporter converts a public trajectory to a documented row format with
  exact package/task commitments and no private fields.
- One thin online RL adapter exposes reset/step over the same Episode service.
  It does not implement optimization, model serving or a trainer.
- Optional aggregate capability feedback is computed only from committed public
  outcomes and may be consumed later as Expand priority. It is never evidence
  or a release gate.
- Observe projects safe Suite/Episode lifecycle and package refs without
  exposing training data that contains private evaluator state.

## Acceptance criteria

- [ ] An immutable Suite contains exact package digests, including one released
  Expand package, manifest commitments and Registry receipts, and remains
  reproducible across cwd/process restart.
- [ ] Quarantine/supersession after Suite freeze leaves Suite bytes unchanged,
  appends a safe blocked admission and prevents a new Episode.
- [ ] Unknown-seed Episodes execute materialize -> reset -> multiple invoke
      steps -> termination/close in isolated candidate processes.
- [ ] At least two package-admitted difficulty selections execute through the
      same Episode API and retain exact echoes; malformed or out-of-domain
      selections are rejected before candidate execution using the same schema
      digest that Registry cold-read.
- [ ] Caller-supplied `initial_config` is rejected, and the private
  Materializer reset value is absent from public API records, RL reset input,
  SFT rows, logs and Observe.
- [ ] A leak test proves public task, trajectory, SFT row, RL observations and
  Observe scene contain no private evaluator/state/sealed/source fields.
- [ ] One real SFT trajectory is exported from actual Episode steps rather than
  a fixed saved trajectory.
- [ ] One online RL-compatible loop completes an Episode through reset/step and
  receives framework-owned rewards/termination.
- [ ] Deleting the SFT/RL adapter modules leaves Direct and Expand tests and
  entry points operational.
- [ ] Running Expand without capability feedback produces the same admission,
  evidence and release semantics.

## Out of scope

- Training a model, implementing PPO/GRPO/veRL, distributed rollout workers,
  replay buffers, optimizer/checkpoint/token accounting or model serving.
- Publishing Episodes or trajectories as EnvironmentPackages.
- Allowing a training framework to mount package source or private Judge state.

## Blocking open questions

None. V1 proves interfaces and real consumption, not model quality improvement.
