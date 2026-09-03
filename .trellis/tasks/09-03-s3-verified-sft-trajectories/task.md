# S3 Verified SFT Trajectories
Goal: turn the exact 69 current TaskPacks into 552 fresh, verified Luna Episodes suitable for later SFT projection.
Invariant: policy input and TrainingEpisodeView contain public data only; protected Goal/state/evaluator truth stays trusted.
Invariant: reward is derived after real close/reopen by the common Goal evaluator as exactly 1.0, 0.0, or null.
Invariant: every rollout slot is retained once; no retry-until-success, old Checker, compatibility reader, or domain branch.
Not doing: no S1/S2 mutation, 50-environment expansion, SFT curation, tokenizer, Parquet, veRL, training, Registry, or sandbox framework.
Gold: S1 `486dd234...a09ad7d`; S2 Corpus `7ce6f077...f186e`; current `load_task_pack`, `capture_public_episode`, and `evaluate_goal` paths.

## Append-only decisions

- 2026-09-03: RFC 8785 encodes integral `1.0/0.0` as JSON `1/0`; the strict reader mechanically restores only those exact values to floats before applying the unchanged RewardOutcome truth table. String, boolean, null and other numeric rewards remain invalid.
