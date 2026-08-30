# S3 Verified Episode Runtime — Completion Checklist

- [ ] Does S3 consume only cold-verified current Release, TaskPack and optional
  CorpusManifest authority?
- [ ] Is there exactly one shared public-policy/tool/lifecycle path reused by S2
  witnesses/assessment and S3 episodes?
- [ ] Are complete partial trajectories retained for healthy policy failures?
- [ ] Are provider/infrastructure failures kept distinct from policy failures?
- [ ] Is the exact Task/checker preimage reconstructed before the first policy
  call, without changing TaskPack identity?
- [ ] Does every verifiable attempt use real close/reopen of the same native
  instance before frozen checker evaluation?
- [ ] Is base reward exactly `1.0` for verified success, `0.0` for valid policy
  failure, and `null` for typed trust/infrastructure abstention?
- [ ] Are TaskAssessment reliability and S2 witness traces incapable of changing
  Episode reward?
- [ ] Does TrainingEpisodeView exclude all protected Task, native and checker
  fields while retaining the full public tool trajectory and reward label?
- [ ] Are success, failure and abstention Episode artifacts canonical,
  identity-bound, immediately cold-read and relocatable?
- [ ] Does batch execution preserve every rollout/attempt and avoid
  retry-until-success?
- [ ] Can one current Responses policy and one second policy/driver identity use
  the same Host runtime without trusted access?
- [ ] Do Git, SQLite and the held-out maintenance release run without domain
  branches or weaker gates?
- [ ] Can an S4-shaped consumer read public trajectories/rewards without S3
  implementing tokenization, logprobs, optimizer or trainer formats?
- [ ] Are services, registries, queues, databases, plugin systems, hidden
  reasoning storage and LLM reward judges absent?
