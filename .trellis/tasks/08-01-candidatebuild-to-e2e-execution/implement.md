# 执行计划

0. **项目执行 Skill 入口瘦身**：确认 hook 只提供导航；把高频、项目拥有的 Agent World
   Skills 的常驻入口缩至触发边界和 references 导航，验证 Skill 格式与 hook 输出，不触碰
   Runtime Agent context。已完成。
1. **选择 Candidate 起点**：枚举已提交的 Design + ImplementationPlan 闭包，使用控制面/API
   验证 definition/acceptance/currentness；记录选择或拒绝旧 r9/r10 的原因。
2. **CandidateBuild**：以真实 Codex Agent 执行一个冻结节点；每 2–3 分钟观察。若失败，读
   scene/attempt，做五-lens + role-play，修首因并跑最窄真实证明，再按 RepairAction/route
   policy 重试或 fallback。
3. **Integration**：Candidate commit 后立即用真实 clean isolation 执行 Integration。只有
   Candidate-visible失败可产生 Builder correction；framework projection/clean-build isolation
   问题先在框架层修复和重证。
4. **Verifier 与 Judge 后缀**：从 final graph manifest 逐个执行仍缺的 verifier batch 和所有
   依赖就绪的 Judge/assurance 节点。对每个新终态重新归因，不把 Integration 假设带入。
5. **Package/Registry**：仅在 required hard gates 通过后运行，读取真实发布状态和 Artifact
   closure。
6. **新的完整 E2E**：以上后缀单点通过后，以新 state/new request-id 运行简单需求至 Registry；
   观察并记录最终 scene。

## 验证

- 每次确定性代码改动：相关真实局部边界 + `uv run --offline ruff format/check`、`mypy`、
  相关 pytest。
- Prompt/Skill/profile/route 改动：实际 Agent/Direct 节点，不用 mock 或另一种调用模式替代。
- Candidate 变更：真实 Candidate validator + Integration。
- 任何 repair/retry 路径：正常 Scheduler/RepairAction 路径。
- 最终：`trellis-check` 以及真实 E2E；两者不可互相替代。

## Observation cadence

- 调用开始即记录 scope、coordinate、attempt、profile/model 与首 Provider progress。
- 每 2–3 分钟只读检查 scene、attempt progress、operation owner；约五分钟无进展则停止链式推进
  并调查 liveness/transport。
- 不硬 kill 正常 generate；不以 PID 存在当作实际进展。
