# S3 Verified SFT Trajectories
Goal: turn the exact 69 current TaskPacks into 552 fresh, verified Luna Episodes suitable for later SFT projection.
Invariant: policy input and TrainingEpisodeView contain public data only; protected Goal/state/evaluator truth stays trusted.
Invariant: reward is derived after real close/reopen by the common Goal evaluator as exactly 1.0, 0.0, or null.
Invariant: every rollout slot is retained once; no retry-until-success, old Checker, compatibility reader, or domain branch.
Not doing: no S1/S2 mutation, 50-environment expansion, SFT curation, tokenizer, Parquet, veRL, training, Registry, or sandbox framework.
Gold: S1 `486dd234...a09ad7d`; S2 Corpus `7ce6f077...f186e`; current `load_task_pack`, `capture_public_episode`, and `evaluate_goal` paths.

## Append-only decisions

- 2026-09-03: RFC 8785 encodes integral `1.0/0.0` as JSON `1/0`; the strict reader mechanically restores only those exact values to floats before applying the unchanged RewardOutcome truth table. String, boolean, null and other numeric rewards remain invalid.
- 2026-09-03: one physical counter Release passed the same current runtime for success (`1.0`), correct-state/wrong-answer failure (`0.0`) and a post-mutation provider defect (`null`). S3 reuses `capture_public_episode` and the shared evaluator-trace projection; no second policy loop or Checker was introduced.
- 2026-09-04: the strict current loader recomputed the exact frozen artifacts as 69 TaskPacks across 20 Release IDs and planned 552 unique request IDs. Batch identity is completion-order independent; terminal slot files are the only resume authority and preserve blocked phase plus original error details.
- 2026-09-04: real Luna canary root `/home/kelong/pycodes/foundry-s3-canary-20260904-5752879` executed the retained Atom (`0c287d10...`), All (`1d77819b...`), If (`01f49abc...`) and ForEach (`713f9747...`) TaskPacks through current Release/3 processes. All four passed reset/before/post-reopen state, answer schema/value and Goal evaluation with rewards `1.0`; their `(calls, turns)` were `(2,3)`, `(2,3)`, `(8,6)` and `(3,3)`.
- 2026-09-04: diagnostic campaign `33eaab17...b4626` completed 552/552 with 520 success, 18 policy failure, 14 provider abstentions and 0 blocked, covering 69/69 Tasks. All abstentions were generic `responses_request_failed` because `PublicEpisodeCapture` discarded its already-derived machine details. Current `EpisodeRecord/3` now binds those details; `/2` remains diagnostic-only and is not read through compatibility.
