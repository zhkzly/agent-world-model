# S4 Verified Agent Learning — Completion Checklist

## Project and stage alignment

- [ ] Does this checkpoint answer the S4 learning-utility question rather than
  merely demonstrate a training framework feature?
- [ ] Does it consume completed S1–S3 authority without generating, repairing or
  weakening EnvironmentRelease, TaskPack, Corpus or checker truth?
- [ ] Is one unseen-Release result described as bounded evidence rather than a
  universal cross-Need claim?
- [ ] Is a valid negative or insufficient-data outcome accepted?

## Formal cohort

- [ ] Was the teacher PolicySpec, matching fresh-driver route/provider sampling
  config, Corpus, slot budget/order and output root frozen before collection?
- [ ] Did existing `run_episode_batch` retain every requested success, failure,
  abstain or blocked slot without retry/backfill?
- [ ] Is every primary SFT Episode in the exact batch/policy allowlist?
- [ ] Are scripted, failed, abstained, duplicate and non-cold-valid Episodes
  excluded from primary SFT?
- [ ] Are split roles bound only to existing `release_id`, `structure_id` and
  `task_pack_id` authority?
- [ ] Are `/tmp` acceptance fixtures excluded from canonical training authority
  unless explicitly recollected into the formal batch?

## SFT data and checkpoint

- [ ] Does each row use only public `TrainingEpisodeView` fields?
- [ ] Is the frozen target tokenizer/chat template applied deterministically
  once rather than through competing render paths?
- [ ] Are assistant tool-call/final-answer spans trainable and prompt/tool
  observation spans masked out?
- [ ] Does the plan avoid claiming preservation of unavailable teacher token IDs?
- [ ] Is one real checkpoint saved and cold-loaded before behavior claims?
- [ ] Did a real optimizer step change a trainable tensor digest, and does the
  HF-compatible cold-loaded handoff have the saved logical tensor digest?
- [ ] Is loss treated as a diagnostic rather than learning evidence?

## S3/veRL bridge

- [ ] Was the existing `PolicyDriver`/`run_task_episode` path attempted before
  proposing any new S3 seam?
- [ ] Do all public actions still pass through the existing Host validation,
  dispatch and trace path?
- [ ] Does terminal reward still come only from existing close/reopen/checker
  truth?
- [ ] Are exact online model IDs retained while decoded text is parsing-only?
- [ ] Does the target pass pinned v0.9.0 Continuous Token model-family and
  chat-template compatibility without a second Foundry codec?
- [ ] Are model tokens mask `1`, environment tokens mask `0`, with equal lengths?
- [ ] Are model-server and trusted-path failures attributed without becoming
  healthy policy failures?
- [ ] Do Base and SFT use the same adapter, template, slots and budget?

## GRPO

- [ ] Does each group bind one exact TaskPack and fresh isolated instances?
- [ ] Does every trainable member bind one matching cold S3 Episode and numeric
  terminal reward?
- [ ] Does any abstention abort the entire optimizer step before advantage or
  update, leaving parameters unchanged?
- [ ] Is pinned v0.9.0 `main_ppo` using V1 sync, one group per step and the
  pin-specific fail-closed ReplayBuffer with no refill/resampling?
- [ ] Are all-equal groups reported as zero signal rather than shaped or hidden?
- [ ] Has a real nonzero-signal update, save, cold reload and continued rollout
  run?
- [ ] Are rollout weights synchronized after update?

## Final held-out evidence

- [ ] Were code/config/checkpoints, primary contrast/metric/direction, statistical
  unit, exact CI implementation, decision rule, checkpoint selection and slot
  budget frozen before the final Release?
- [ ] Are the terminal checkpoints at the exact frozen step budgets used, with no
  best-of-run selection?
- [ ] Did the parent Foundry operator deliver exact post-freeze S1–S3 artifacts
  before S4 made any final model call?
- [ ] Is the final Need/Release absent from all training and tuning history?
- [ ] Are Base, SFT and SFT→GRPO evaluated on the same S3 slots?
- [ ] Are all failures and abstentions retained in requested-slot accounting,
  with null excluded only from the predeclared paired numeric estimate?
- [ ] Are only metrics/raw codes with existing S3 producers reported?
- [ ] Can exact source, config, checkpoint and Episode identities reconstruct the
  result?

## Anti-overdesign and execution discipline

- [ ] Is there one normal veRL path with no Foundry CPU/GPU fork or remote runner?
- [ ] Is there no predesigned incremental S3 session, second Host or evaluator?
- [ ] Is there no trainer/model/algorithm/codec/artifact registry?
- [ ] Is there no shaping, reward model, LLM judge, retry, replacement, requeue,
  scheduler, service or curriculum?
- [ ] Does every new file/type/field have a current producer and consumer?
- [ ] Did the checkpoint begin with reachable behavioral RED, pass mutation and
  full checks, receive independent review and land in its own commit?
