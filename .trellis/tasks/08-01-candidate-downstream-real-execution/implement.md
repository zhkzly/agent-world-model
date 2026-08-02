# 执行计划

1. 读取旧 Candidate diagnostic store 的最新 safe reports，选出同一 Candidate revision 的
   ready Integration 与匹配 Verifier evidence；记录历史 error/failed 不作为当前结论。
2. 删除 `IsolationPolicy`、bwrap/unshare、namespace 路径和兼容分支；重构
   `CleanCandidateBuilder` 与 `RuntimeSupervisor` 使用唯一的本机进程边界，并以构造的真实
   子进程先证明 cwd/env/path 映射。
3. 用该 adapter 运行一次新的 `EnvironmentJudge.evaluate_integration`，读取完整 report 和
   evidence，必要时按五-lens 修复第一个机械偏差。
4. 校验 Verifier projection 与 Candidate 的 Design/WorldSpec closure；缺失时执行实际
   VerifierBatch，否则记录为何不能/不应重跑已有冻结 Direct 输出。
5. 运行一次新的 `EnvironmentJudge.evaluate` ReleaseAssurance；再读 Judge report。
6. 通过真实 `ObservabilityLeaf`、`PackageLeaf`、`RegistryPublicationLeaf` 或等价的生产实现
   边界逐站执行。
7. 对正式 Registry provenance 执行负向验证，确保诊断 Candidate 不会被接受为生产 release。
8. 对修改的 adapter 和控制面运行 focused pytest、ruff、mypy；这些仅作回归保护。最后汇报
   每个节点的真实终态、剩余 E2E 前提与下一条不确定路径。
