# CandidateBuild 到 E2E — 执行设计

## 边界

本任务不重新设计 WorldSpec 或调用控制面。它消费一个已有、冻结、仍被当前定义接受的
Design/ImplementationPlan 闭包，验证从 Code Agent 创建 Candidate 到 Registry 的真实后缀。

项目执行 Agent 的 context surface 是这一任务的前置可观测性边界，而非 Runtime Agent
的 Prompt/Skill 表面：SessionStart/每轮 hook 只给紧凑导航；项目拥有的高频 Skill
在被选中后只加载短入口，再根据明确的阶段路径读取一级 references。运行时 Candidate
仍只由 its resolved profile、mounted Runtime Skill、Prompt、workspace 和授权 feedback
决定。

```text
valid committed parent closure
  -> CandidateBuild (real Codex Agent)
  -> Integration (clean isolated Candidate)
  -> required Verifier batches / Judge assurance
  -> Package
  -> Registry publication
  -> new-request E2E confirmation
```

实际 WorkGraph 决定 verifier 的物理 batch 数与并发资格；此图不虚构固定数量的节点。

## Workspace ownership

| 层 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| Code Agent | 在当前工作区读 `inputs/`、写/测 `candidate/`、返回完整 CandidateCompletion | 宿主路径、后续 mount、Integration cwd、目录搬运 |
| Builder / Judge framework | input materialization、Candidate snapshot、clean build、`workspace/candidate` 投影、runner/import root、isolation | 替 Agent 写业务代码 |
| Integration / Judge | 独立运行并产生证据、区分 Candidate failure 与 infrastructure error | 接纳 Agent 自述的完成 |
| Scheduler | 预算、RepairAction、retry/fallback、DAG 前进 | 发明语义修复 |

因此只有先通过 framework-owned workspace projection probe 后，公开测试/运行时失败才可被
归属为 Candidate-facing feedback。投影失败直接由 `judge_infrastructure` 处理。

## Node protocol

每个节点遵循同一状态机：

1. 读取最新 scene 与 control/attempt record，确认无 active/orphan call。
2. 验证本节点的 immutable parent closure 与当前 definition。
3. 运行一个真实节点边界；调用期间按 2–3 分钟读取安全 telemetry/scene。
4. 终态后按五-lens 和 chronological role-play 归因。
5. 只修首个被证实的因果边界；先运行该边界的真实本地/Agent proof。
6. 仅在节点 `committed` 或控制面明确准入后进入其真实下游。

`failed/error/repair_authorized` 从不等同于已完成。不同 failure 产生新的调查，不携带上
一个错误的修复假设。

## Repair selection

- Agent 没收到必要语义或方法：改有效 Prompt/input 或其唯一 mounted Runtime Skill，随后跑
  同种真实 Agent node。
- Agent 收到完整语义但输出局部不满足：只有反馈含稳定、Candidate-visible、可行动条件且有
  RepairAction 时，发一次受限 repair。
- 框架路径、mount、cwd、toolchain、isolation、adapter、scheduler、transport 或 Provider：
  改 framework/configuration 或走 typed recovery；不把原始错误转成 Agent 文本。
- 无法定位：先补 scene/diagnostic/Agent view，再运行构造的真实边界；不改语义。

## Rollback

不删除任何已有 state。每个新真实尝试使用可区分的 state root/request id；已提交父
Artifact 不重跑，未提交的草稿不越过 Candidate validator。
