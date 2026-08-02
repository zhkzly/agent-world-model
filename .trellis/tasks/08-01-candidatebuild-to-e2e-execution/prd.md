# CandidateBuild 到真实 E2E 执行

## Goal

从一份仍然有效、直接父项均已提交的 CandidateBuild 冻结输入闭包开始，真实执行
CandidateBuild 及所有实际依赖的下游节点，逐节点诊断和修复，最后以一条新的自然语言
需求真实运行至 Registry。目标是可运行的 Agent World 环境，不是凑齐 pytest 或伪造
Artifact。

## Confirmed Facts

- Codex 的默认渐进加载是：先给项目执行 Agent Skill 的名称/description，选中后才读该
  Skill 的完整入口文件；它不是把全部 Skill 正文塞入会话。当前项目 hook 实测只注入
  2,365 字符的 SessionStart 索引和每轮短 workflow breadcrumb，未读取任务正文或全部
  Skill。项目能改的风险面是过长的、容易被选中的入口 SKILL.md，不是绕过宿主的
  selected-Skill 读取语义。
- 高频、项目拥有的 Agent World project-execution Skills 已改为短入口加一级
  references/：入口仅含触发边界、最小流程和加载条件；细节不在初始全文入口中。
  这不改变 Runtime Candidate Skill、Direct LLM no-Skill 约束或 project hook 的权限。
- 旧的 r9 CandidateBuild 曾真实启动，但没有提交 `EnvironmentCandidate`；它不能直接作为
  Integration 输入，也不能假装是可恢复 Artifact。
- 当前 r10 普通 E2E 的 `BuildImplementationPlan`、一条 Verifier batch、Research
  Acquisition 处于失败头，且 WorldArchitecture 仍是 `repair_authorized`；它不能被不加
  验证地当作本任务的 Candidate 起点。
- 框架已验证 Candidate 工作区投影：Code Agent 只看见其 `inputs/`、`candidate/` 和
  provisioned tools；后续 Judge/Integration 的路径、cwd、mount、解释器与沙箱投影是
  framework-owned，绝不能变成 Builder feedback。
- 这项任务沿用项目的真实 `InvocationBackend`、冻结 Artifact 闭包、预算与 RepairAction
  权威；不允许模板/fixture 代码生成、手填 Candidate 或把诊断产物当作发布产物。

## Requirements

- R0：项目执行 Agent 的 Skill 入口遵守官方 progressive disclosure：不自动注入所有
  Skill 正文；被选中 Skill 的入口保持紧凑，细节通过明确的一层 references 按需读取。
  不修改宿主系统规则，不用 hook 假装 Runtime Agent 的上下文。
- R1：在发起任何 Candidate Agent 调用前，确定性验证其 exact immutable parent closure、
  definition/current acceptance 与预算；若旧闭包已 stale，则建立新的、合法的 Candidate
  起点，而不是从失败/未提交工作目录续写。
- R2：CandidateBuild 必须使用真实 Codex Agent、实际 mounted
  `engineer-environment-codegen` Runtime Skill、真实工作区写入与真实 Candidate validator。
  Code Agent 只在自己的相对工作区实现和自测，不承担任何路径转换、Judge mount 或宿主
  环境推理。
- R3：每一个节点先执行它的真实边界，获得 `committed` 或明确的 typed terminal 后才进入
  下游。失败时先读 scene、attempt/control record 和最小相关输入，显式按五个 lens
  （项目执行 Agent view、Prompt/input、Runtime Skill、代码/Provider/profile/adapter、
  feedback/observability）归因；不盲目重试。
- R4：对于 Agent/LLM 的不确定结果，使用按时间顺序的角色扮演审查实际可见信息，定位
  首个因果偏差。修复可选择 Prompt、Agent-only Skill、确定性代码/配置、可行动 feedback、
  有授权的 repair、或经证实的 transient retry/fallback；不能由错误症状直接决定手段。
- R5：feedback 只可描述 Agent 当前工作区可见且能通过源码/配置/测试修复的稳定事实。路径、
  mount、cwd、framework toolchain、隔离、transport 和控制面事实必须在框架层修复或终态化，
  不得塞给 Code Agent。
- R6：Candidate 提交后，按实际 DAG 执行 Integration、所需 Verifier batch、Judge/
  release assurance、Package 与 Registry。只在真实依赖独立、状态根/预算/写入独立时并行；
  默认逐个通过再串联。
- R7：每次真实 Provider/Agent 调用每 2–3 分钟只读观察；约五分钟无首个 Provider 事件或
  无实际进展时进入 liveness/transport 调查。不得硬杀 generate，不能让无进展调用静默占用
  数小时。
- R8：不新增任意模型输入/输出上限来掩盖调用问题；保留已声明的物理生命周期、预算和
  Provider 限制，并将任何真实容量、超时或回包问题按调用层策略记录。

## Acceptance Criteria

- [ ] AC1：存在一份经实际控制面验证的 CandidateBuild 输入闭包；任何不能复用的旧状态有
  明确的安全原因，未被偷偷采用。
- [ ] AC2：一次真实 CandidateBuild 以真实 Agent 完成并提交完整 Candidate；若第一次失败，
  每次修复均有五-lens 归因、单边界证明和授权的下一次尝试记录。
- [ ] AC3：提交的 Candidate 经过真实 Integration；路径/投影/隔离失败绝不路由回 Builder，
  Candidate 可见失败才可形成受限修复。
- [ ] AC4：所有本次最终 DAG 所需的 Verifier、Judge/assurance、Package 与 Registry 节点都
  有真实终态；不得以诊断、fixture、单元测试或旧候选替代。
- [ ] AC5：在下游单点均通过后，使用一条新的简单需求运行一次真实 Generate 至 Registry，
  并读取最终 scene、Artifact 闭包和发布状态。
- [ ] AC6：每项代码/Prompt/Skill/feedback/调用层修改都有相应的真实边界证明；pytest、
  类型检查和 lint 只作为回归保护，不被表述为 E2E 成功。
- [ ] AC7：不泄露 Provider 原文、凭证、端点、私有 session 或未提交 Candidate 草稿到 Artifact、
  scene、feedback 或提交内容。

## Out of Scope

- 为了跳过失败而重跑已经 committed 的上游语义节点，或手工改写 Artifact/WorkHead。
- 因 Code Agent 的不确定性而增加业务硬编码、固定环境、固定任务、模板或特例成功路径。
- 将 uncommitted Candidate 草稿交给 Integration、fallback 模型或 Registry。
