# S4 Verified SFT/GRPO Core — Completion Checklist

## Current-stage alignment

- [ ] Does the checkpoint build the real SFT/GRPO path rather than an experiment
  or generic training platform?
- [ ] Does it consume completed S1–S3 authority without generating, repairing or
  weakening Release, Task, Corpus, checker or reward truth?
- [ ] Are improvement, held-out and statistical claims explicitly absent?
- [ ] Is a valid `DATA_INSUFFICIENT`/`NO_GRPO_SIGNAL` stop accepted?

## Formal teacher cohort

- [ ] Are Corpus, teacher PolicySpec, matching fresh-driver route, collection
  budget and output root frozen?
- [ ] Does existing `run_episode_batch` retain every requested slot without
  retry/backfill?
- [ ] Does every primary SFT Episode belong to the exact batch/policy allowlist?
- [ ] Are scripted, failed, abstained, duplicate and non-cold-valid sources
  excluded from primary SFT?
- [ ] Are unpublished-run recovery and published-manifest finality distinct?
- [ ] Are existing S3 artifacts/manifests reused without a new artifact framework?

## SFT

- [ ] Does the mapper emit only public `messages/tools` plus source identities?
- [ ] Are tool calls built from validated `parsed_arguments`?
- [ ] Does pinned veRL own template application and assistant-only loss mask?
- [ ] Is there no custom tokenizer, codec, dataset class or trainer?
- [ ] Did a real optimizer step change a trainable-tensor digest?
- [ ] Does the HF export cold-load with the saved logical tensor digest?
- [ ] Is loss treated only as a diagnostic?

## AgentLoop/S3 boundary

- [ ] Was the current PolicyDriver/thread bridge attempted before any S3 seam?
- [ ] Does every call still pass through the existing Host and every reward through
  existing close/reopen/checker truth?
- [ ] Does the target pass v0.9 Continuous Token/chat-template compatibility?
- [ ] Are exact model IDs retained and decoded text parsing-only?
- [ ] Are model spans mask `1` and environment/tool spans mask `0`?
- [ ] Does every rollout use a fresh matching driver/native instance?
- [ ] Does each rollout receipt bind exact token/mask evidence to one Episode ID
  and matching S3 reward?

## GRPO

- [ ] Is v0.9 V1 sync configured with one prompt group per step and frozen `G`?
- [ ] Does the one pin-specific ReplayBuffer reject failure, incomplete sibling
  count, non-numeric reward and all-equal signal before materialization?
- [ ] Is refill/retry/padding/survivor filtering/replacement disabled?
- [ ] Does an injected abstain leave the parameter digest unchanged?
- [ ] Did one complete nonzero-signal group produce a real actor update?
- [ ] Does the checkpoint save, cold-load and continue a fresh S3 rollout with
  synchronized weights?

## Anti-overdesign and execution discipline

- [ ] Are production additions limited to `learning_data.py`,
  `verl_agent_loop.py`, `s4_collect.py`, two configs and focused tests?
- [ ] Is there no custom trainer/checkpoint/device layer, Registry, service,
  scheduler or experiment/evaluation framework?
- [ ] Does every new field/type/file have a current adjacent producer/consumer?
- [ ] Did the checkpoint begin with reachable behavioral RED, pass mutation/full
  checks, receive independent review and land in its own commit?
