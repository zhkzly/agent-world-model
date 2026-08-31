# S4 Core Task Contract
Goal: deliver one real config-first teacher→SFT→S3 AgentLoop→GRPO checkpoint path.
Invariant: S3 Host/close-reopen/checker remains the only action and reward authority.
Invariant: primary SFT uses cold-valid real-teacher verified successes only.
Invariant: online model IDs/masks bind exactly to one Episode and `1.0/0.0/null` outcome.
Do not: add experiments, held-out statistics, custom trainer/codec, S3 seam, retry or platform layers.
Gold: S3 live batch `655b1fd8…` under `/tmp/foundry-s3-cp6-responses-sf7nu478/output` and pinned veRL v0.9.0 source research.
Acceptance: four checkpoints pass real physical exits, mutation licences, drift reviews and separate commits.

## 追加

- Chosen: latest stable veRL v0.9.0 exact SHA with native SFT/Continuous Token/V1 sync config.
- Alternative rejected: legacy trainer or custom training framework; both duplicate or bypass current upstream behavior.
- Reconsider only if the exact-pin compatibility RED proves the documented extension point cannot preserve S3 truth.
- Chosen: `configs/s4/core.json` freezes semantic IDs/model/policy/budgets; artifact locators remain invocation-local CLI arguments.
- Alternative rejected: checked-in absolute machine paths, because paths are operational and the user will run the same config after clone.
- Reconsider only if an existing project config owner already provides the same exact consumed fields.
- Chosen: `TeacherCohort.json` binds the config and S3 batch identities, then partitions only public cold `TrainingEpisodeView` values in manifest order.
- Alternative rejected: reading private EpisodeRecord fields, duplicating blocked slots, or selecting successes outside the published batch.
- Reconsider only if the current paired public reader can no longer cold-return every sealable manifest Episode without a new S3 surface.
- Chosen: CP0 physical authority is batch `6affea4a…`, cohort `296e742f…`, with 3/3 real Responses verified successes and every published slot retained.
- Alternative rejected: promote the older acceptance batch without a new frozen collection, because the active task now has its own exact request/config identity.
- Reconsider only if cold replay of this output disproves manifest/view/cohort binding before CP1 consumes it.
- CP0 physical exit: the exact CLI ran once into `.artifacts/cp0-formal-teacher-no-listener-20260831`, exited `0`, and published Batch `6a92bd643f29c8623c477b02c7f486d65756ca657e036c2c7e81fded432d8df0` plus Cohort `376bcc276022a2c702e40b1b8acc683daa0687074852c94728b4ace2453c743d`.
- Evidence: all three manifest Episodes cold-read through `read_episode_bundle` as `verified_success/1.0`; the cohort contains all three in primary SFT, none in analysis, and all eight JSON files are canonical.
- Boundary: no proxy/S3 change, retry, backfill, or second output root was used; persisted authority, not the earlier listener observation or silent terminal, determines the result.
- Correction: batch `6a92bd64…` / cohort `376bcc27…` was published first and is the sole CP0 authority; later batch `6affea4a…` was an accidental concurrent duplicate by the supervisor and is rejected.
- Redline: two sessions issued the same frozen collection concurrently; no further collection is permitted, and the duplicate output is quarantined outside `.artifacts`.
- Evidence: manifest mtimes are 19:06:42 for `6a92…` and 19:09:24 for `6aff…`; identical request IDs prove repetition rather than a new logical cohort.
- Chosen: CP0 freezes target `Qwen/Qwen3-0.6B@c1899de…`, tokenizer at the same revision, chat template `tokenizer_config.json`, Continuous Token family `qwen`, and tool parser `hermes`.
- Alternative rejected: freeze SFT/GRPO runtime configs in CP0; their native compatibility belongs to CP1/CP2/CP3 and has no CP0 consumer.
- Reconsider only if the pinned tokenizer revision no longer contains the bound template/parser format.
- Chosen: `read_teacher_cohort(output_root, config)` now derives its exact manifest and every sealable public view from persisted bytes; the collector enters that same internal boundary with the returned `batch_id` before cohort publication.
- Alternative rejected: caller-injected manifest/views, an S3 private reader, a new S3 API, or a generic batch reader; each would weaken or widen the required cross-process trust boundary.
- Reconsider only if the public `EpisodeBatchManifest` or `read_episode_bundle` contract changes under a separately reviewed upstream task.
- Chosen: current `TeacherCohort` identity contains only the complete manifest-ordered `verified_success/1.0` primary list; nonprimary Episodes and blocked slots remain solely in the bound S3 artifacts.
- Alternative rejected: retain the producer-less analysis partition or infer collection age from a structurally legal batch; the `655b1fd8…` fixture remains a positive structural gold while temporal task authority remains the exact physical root/IDs above.
- Reconsider only if a future producer and consumer define a new evidence-backed nonprimary cohort field under a later checkpoint.
- Rework evidence: the cold-reader RED failed on missing `manifest/views`, and the schema RED failed on present `analysis_episode_ids`; both are now green. Mutation licences killed persisted-batch binding, the `verified_success/1.0` filter, and collector use of the returned batch identity.
- Verification: 31 focused tests and 517 full tests pass; Ruff passes `src tests scripts`; strict mypy passes `src scripts/s4_collect.py`; `git diff --check` is clean.
- Scope evidence: `.artifacts` still contains only `cp0-formal-teacher-no-listener-20260831`, with unchanged 19:06:42 manifest/cohort mtimes, eight JSON files, batch `6a92bd64…`, and cohort `376bcc27…`; no collection command, S1–S3 edit, later-checkpoint edit, Alignment Patrol, commit, or push occurred.
- Chosen: preserve the authoritative physical cohort bytes and fail closed on their now-legacy shape rather than silently add compatibility or rewrite published identity.
- Alternative rejected: mutate `TeacherCohort.json` to the new identity or accept its removed field; the former violates published finality and cohort `376bcc27…`, while the latter violates the required clean-break schema.
- Reconsider only with explicit authority to republish cohort metadata under a new ID or to introduce a reviewed legacy exception; neither is authorized by this rework.
- Consistency evidence: the unchanged physical cohort has config digest `3731821c…`, cohort `376bcc27…`, and the removed analysis field; the mandated target-complete config has digest `b5ec0434…` and derives cohort `09cecd90…`. The exact `6a92bd64…` manifest and all three paired bundles still cold-read successfully.
- Authorized correction: republish only the derived cohort metadata for the sole authoritative batch `6a92bd64…`; the Responses rollout, batch manifest and all three paired Episode bundles were not rerun or rewritten.
- Current physical authority: cohort `09cecd906974dcb102aa95f762848b003f049fe7091e97d302a3ac23697fb579`, config digest `b5ec0434b30ebab4d5560724c22137555b759cd9579f9120fb83769a1775770f`, and the same three manifest-ordered verified-success Episode IDs.
- Preservation evidence: the prior cohort bytes (`sha256:e16ec754…`, ID `376bcc27…`) are recoverable at `/tmp/foundry-s4-cp0-pre-rework-cohort-376bcc27.json`; manifest `sha256:dcd642eb…` and EpisodeRecord hashes `20b8c70d…` / `9d940a22…` / `dc8a23b4…` remained unchanged.
- Final CP0 review: independent cold reconstruction and the complete 31/517/Ruff/mypy/diff gate returned ACCEPTED with no product or stage blocker; an unrelated reviewer verdict that cited no S4 file and discussed absent harness/Consumer/Registry scope was rejected as context drift.
- Mutation evidence completed: a fourth licence removed both `_require_primary_teacher` call sites and was killed by the scripted-policy, wrong-route and collector-preflight tests; the teacher allowlist and disposition filter now each have direct semantic mutation evidence.
- Chosen: retain the six-line field-specific cohort-authority mismatch diagnostic before whole-cohort equality, because it identifies the exact failed binding consumed by a cold handoff.
- Alternative rejected: collapse every mismatch to one generic error merely to reduce line count; reconsider only if the cold-reader contract no longer promises actionable binding errors.
- Cross-review closure: the context-drifted reviewer explicitly retracted every unsupported harness/Consumer/Registry claim and returned CP0 ACCEPTED with no blocker after checking the activated S4 task, exact collector/selector lines and physical cohort; both independent reviewers now agree.
