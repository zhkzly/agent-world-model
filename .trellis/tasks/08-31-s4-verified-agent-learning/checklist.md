# S4 Verified Agent Learning — Completion Checklist

## Reward and trust boundary

- [ ] Does every tool call receive only Host parse/schema/dispatch/observation checks rather than Task reward?
- [ ] Is Task success decided only by the existing S3 post-reopen frozen checker?
- [ ] Does final-answer correctness remain one checker axis rather than the sole truth for stateful Tasks?
- [ ] Is S3 `1.0 / 0.0 / null` transported exactly, with no LLM Judge or second verifier?
- [ ] Does any `abstain` block optimization rather than become zero or disappear?
- [ ] Are S2 witnesses, protected bindings, native facts and checker internals absent from model input and learning data?

## External veRL authority

- [ ] Is one exact official veRL commit/tag frozen and fail-closed?
- [ ] Is the integration an overlay rather than a vendored/fork-first copy?
- [ ] Has unmodified upstream extension-point compatibility been tested first?
- [ ] If a patch exists, is it minimal, based on one exact SHA, covered by a failing compatibility test and assigned a deletion condition?
- [ ] Are accelerator, PyTorch, rollout backend, model and tokenizer revisions recorded?

## Data readiness and split integrity

- [ ] Are Release, Task structure, TaskPack and Episode counts reported before training?
- [ ] Are verified-success SFT token counts sufficient for the declared run?
- [ ] Are base-policy success and candidate GRPO reward variance measured?
- [ ] Are zero-advantage-group and abstain rates reported?
- [ ] Are instance-, structure- and release-held-out roles disjoint and frozen?
- [ ] Is the final release-held-out Need selected only after S4 code/config freeze?

## SFT data and checkpoint

- [ ] Does every SFT sample cold-bind one verified-success Episode ID?
- [ ] Are system/user/reset/tool-observation tokens masked out?
- [ ] Are assistant tool-call and final-answer tokens trained?
- [ ] Are generated assistant tokens preserved rather than reconstructed by a second render pass?
- [ ] Are verified failures and abstentions excluded from positive SFT?
- [ ] Does the dataset manifest bind tokenizer/template/config/checksums?
- [ ] Is a real checkpoint saved, cold-loaded and evaluated through S3 against the base model?

## Shared S3 online seam

- [ ] Is there one current consumer-driven incremental Episode seam or a proven smaller adapter?
- [ ] Do Responses and veRL reuse the same Host tool validation/dispatch/trace path?
- [ ] Do they reuse the same close/reopen/checker/reward path?
- [ ] Can S4 neither reset twice nor inspect trusted state/checker?
- [ ] Are S3 EpisodeRecord, TrainingEpisodeView, TaskPack and Reward identities unchanged?

## veRL Agent Loop token truth

- [ ] Does one custom AgentLoop retain exact IDs returned by the rollout server?
- [ ] Is decoded text used only for parsing, never to replace generated token IDs?
- [ ] Are model tokens mask 1 and environment observation tokens mask 0?
- [ ] Do response IDs and response mask have identical length?
- [ ] Does each rollout use a fresh S3 native instance and exact Task group identity?
- [ ] Does each trainable AgentLoopOutput bind one cold-valid Episode ID and matching terminal reward?
- [ ] Does an injected S3 abstain prevent the optimizer group from updating?

## GRPO and checkpointing

- [ ] Does each group contain rollouts from one exact TaskPack/split group?
- [ ] Does every member have numeric S3 reward and at least one model-generated token?
- [ ] Are all-equal groups reported rather than hidden or shaped?
- [ ] Has one nonzero-signal GRPO optimizer update physically run?
- [ ] Are rollout weights synchronized after update?
- [ ] Does checkpoint save/reload preserve model/tokenizer/parent/config/data/veRL identities?
- [ ] Can training continue from the reloaded checkpoint?

## Final learning utility

- [ ] Are base, SFT and SFT->GRPO evaluated with the same frozen S3 budget?
- [ ] Are verified success, structure/release macro results and repeated reliability reported?
- [ ] Are wrong-target, partial, collateral and wrong-answer errors retained?
- [ ] Are calls, turns, tokens, latency and abstain owners retained?
- [ ] Is the final held-out result accompanied by confidence intervals and exact artifact/config identities?
- [ ] Is a valid negative/no-gain result accepted without changing S1–S3 truth?

## Anti-overdesign

- [ ] Is there no trainer/model/algorithm registry?
- [ ] Is there no HTTP Episode service, queue or extra Ray environment platform?
- [ ] Is there no reward DSL or per-tool shaping path?
- [ ] Is there no automatic curriculum/Task evolution?
- [ ] Is only one model family, one veRL pin and one GRPO path required for completion?
- [ ] Does every added field/module have one current producer and consumer?
