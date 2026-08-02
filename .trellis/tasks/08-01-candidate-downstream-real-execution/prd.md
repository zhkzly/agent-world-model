# Candidate 后置节点真实执行

## Goal

以已经由项目执行 Agent 修复、且候选验收已通过的同一份 Candidate 源码为输入，逐个真实
执行 Candidate 后置 DAG 的节点：Integration、Verifier 关联路径、ReleaseAssurance、
Observability、Package 与 Registry。目标是得到每一站的真实终态和明确归因，而不是重跑
CandidateBuild、只跑 pytest，或把手工诊断产物冒充正式发布。

## Confirmed facts

- 候选源码位于
  `.agent-world-staged/candidate-substitute-Y8tKX3/workspace/candidate`；其已验证的
  `EnvironmentCandidate` revision 是
  `sha256:85354c475df9f6120cd7ca52d2ebe3a6849f7b0222f8f280906b43e75ddf2d22`。
- 该源码曾由真实 `EnvironmentJudge` 的诊断 harness 产生 ready Integration 和 pass 的
  Release Judge 证据；同一 store 中也有历史 failed/error 尝试，不能从文件存在推断当前
  成功，必须在本任务重新选择并运行一个可区分的尝试。
- 该 Candidate 不是 Scheduler 的真实 `WorkCommit`，因此不得将其诊断 Artifact 直接称为
  生产 Package/Registry 发布；生产路径应在该处作出明确、可解释的拒绝。
- 用户已明确授权移除项目中所有进程级 bwrap/namespace 隔离。Candidate、clean build 与
  Runtime Judge 都直接在本机启动；逻辑 Rule/tool `namespace` 仍是业务标识，不属于本次删除。
- 上游 CurriculumPlan 的 Direct LLM 路由目前仍有两次零 Provider event 的 retryable 终态；
  它不阻止本机确定性后置节点的诊断，但阻止将本任务结果表述为完整新需求 E2E。

## Requirements

- R1：冻结 Candidate 源码和其已知 Design/WorldSpec/ImplementationContract/Verifier 输入，
  不重跑或重写 CandidateBuild。
- R2：删除 `IsolationPolicy`、bwrap/unshare 绑定、虚拟 `/workspace`/`/state` 路径和所有
  兼容分支，改为唯一的本机进程执行边界。Candidate 仍只在自己的工作目录中运行，框架负责
  cwd、解释器与路径投影；不得把框架路径转换作为 Agent feedback。
- R3：依序运行真实 Integration、ReleaseAssurance、Observability、Package、Registry 实现
  边界。Verifier 若为已存在的冻结输入，验证其完整性/绑定而不无故重跑；若必须执行新的
  Verifier batch，使用真实 Direct LLM 调用并记录其独立终态。
- R4：每个新终态先读可观测证据，并按项目执行 Agent view、有效 Prompt/input、Runtime
  Skill、代码/Provider/profile/adapter、feedback/observability 五个 lens 归因。Node 的
  确定性路径不能被错误地归因到 Prompt 或 Skill。
- R5：所有本机节点都输出安全、可行动的结构化结果；Provider 原文、凭证、Base URL、私有
  session、未提交草稿均不得写入 Artifact 或日志。
- R6：对正式 Scheduler/Registry 运行单独验证 provenance gate。若它拒绝这份诊断
  Candidate，则将其记录为正确的生产门禁，而非绕过或硬编码接受。
- R7：若节点真实失败，只修该节点第一个已证实的因果偏差；完成该节点的真实重测后再继续。
  不因为后续节点尚未测试就修改 Candidate、Prompt 或 Runtime Skill。

## Acceptance Criteria

- [ ] AC1：同一 Candidate revision 在新的实际本机 Integration 中得到一个新的
  typed terminal；若失败，存在安全 scene/报告和五-lens 归因。
- [ ] AC2：Verifier 输入的精确绑定已验证；需要执行的 VerifierBatch 有真实终态，不以旧
  文件或单元测试替代。
- [ ] AC3：ReleaseAssurance 对相同 Candidate、Integration 与 Verifier 闭包得到一个新的
  真实终态。
- [ ] AC4：Observability、Package 和 Registry 的实际边界均被执行或因明确的前置失败而
  typed terminal；不把不能到达误报为“已通过”。
- [ ] AC5：生产 provenance gate 的行为有独立证据；诊断 Candidate 不会被偷渡为正式
  Registry release。
- [ ] AC6：每项通过都注明它证明什么、未证明什么；完整新需求 E2E 仍需在有效上游闭包和
  正式 Candidate WorkCommit 后另行执行。

## Out of scope

- 重跑 CandidateBuild、把项目执行 Agent 手工修复的 Candidate 伪装成 Scheduler WorkCommit，
  或修改 Design 业务语义来绕过下游门禁。
- 因 Direct LLM 路由故障而猜测性改 Prompt、Skill 或 Candidate 源码。
