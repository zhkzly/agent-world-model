# Direct 重写：节点执行类型与权限地图

> 本文是 [环境生成主文档](agent-world-environment-generation.zh.md) 的派生执行索引，
> 用来消除实现时对“组件、逻辑节点、LLM、Agent、候选进程”的混淆。主文档仍是唯一
> 产品事实来源；二者冲突时以主文档为准。本文不增加运行时组件、Gate 或配置系统。

## 不变的产品目标

将任意自然语言 `EnvironmentRequest` 变成有真实证据支撑、能在不可信隔离进程中执行、
被独立 Judge 验证、并由 Registry 原子发布的不可变 `EnvironmentPackage`；`Observe`
只展示安全的持久事实。

图完成、模型返回结构化 JSON、单元测试通过、或出现 package 形状的文件，都不等于上述
产品目标已经达成。

## 先区分四个概念

| 名称 | 含义 | 是否模型调用 |
| --- | --- | --- |
| **组件** | 五个有权威边界的框架所有者：Controller、Designer、Builder、Judge、Registry。 | 不必然 |
| **逻辑节点 / Work** | 一次有明确输入、输出、Artifact 和 owner 的工作边界。 | 按需要 |
| **Direct LLM** | 只收到 `model + rendered prompt/input + 已授权反馈` 的结构化模型调用；没有 Skill、工具、workspace 或隐式上下文。 | 是 |
| **工具型 Codex Agent** | 通用 Codex + 本节点唯一运行时 Skill + 冻结输入/反馈 + 显式工具和 workspace；经 `InvocationBackend` 的 Codex adapter 调用。 | 是 |
| **框架 / 候选进程** | 框架代码负责确定性编译、Gate、Artifact、进程和发布；候选 Runtime 是不可信子进程。两者都不是 LLM 或 Agent。 | 否 |

因此，**Builder 是组件/框架所有者，`CandidateBuild` 才是它内部派发的写代码 Agent
工作**。`BuildImplementationPlan` 是另一个只读建议性 Agent 工作，绝不是第二个
Builder。

## Complete v1 共享的两个领域图

Direct 与 Expand 不共享一个巨型循环图，只共享两个有稳定输入输出的领域图：

```text
DesignGraph:
  DesignRequest -> Research / World / Tool / Task semantics
  -> Modeling Gate -> EnvironmentDesign

CandidateGraph:
  EnvironmentDesign -> BuildPlan -> CandidateBuild -> Integration ---+
  EnvironmentDesign -> VerifierIntent -------------------------------+-> Judge
  -> Package -> Registry
```

`FoundryController.generate` 依次调用两者。`ExpandCampaign` 在外层冻结 parent、source、
direction、operator 与预算，产生新的 `DesignRequest`，再调用同样的 DesignGraph 和
CandidateGraph。Observe 只读这两层的持久事实，不属于执行图。

实现只允许一个轻量 `NodeSpec`、一个 `EdgeSpec` 和确定性 runner；图在 Python 中闭合声明。
禁止 Node 子类体系、YAML DSL、动态插件/handler 注册、callback bus、通用 scheduler、
`SubgraphNode` 或第二套 Artifact/Repair/Release 权威。

每个 Node 是一个完整工作事务：精确输入 ArtifactRefs -> 最小 executor 投影 -> 一次
framework/Direct-LLM/Agent proposal 或执行 -> framework validation/assurance -> Artifact commit。
模型原始输出不走 Edge。只有中间结果存在独立消费者、repair owner 或 readiness 意义时才拆新
Node；不能为每次 compiler 调用机械地把节点翻倍。

实现任何 Node 前必须完成 Node Contract Card：目的/owner、图输入输出、模型可见投影、route、
Prompt、输出模型、Skill/工具/workspace、validation/commit、局部 feedback、跨节点 repair、
下游消费者和真实 proof。Prompt、Skill 和 feedback 不能等 E2E 失败后再临时补。

## Direct 正常路径：每个节点的执行者

| 顺序 | 逻辑节点 | 执行者 | 可产出 | 明确不能做 |
| --- | --- | --- | --- | --- |
| 1 | Intake / admission / scope | Controller 框架 | canonical request、job/scope、权限与预算上下文 | 生成世界语义、替用户选择发布结果 |
| 2 | Budget lease / scheduling | Controller 框架 | lease、WorkAttempt、调度决定 | 让模型绕过预算或自行重试 |
| 3 | Research plan 与 evidence synthesis | **工具型 Researcher Agent** | ResearchPlan、evidence/coverage 的提议与解释 | 写候选代码、读取 sealed 数据、宣布研究完成或发布 |
| 4 | Search / Fetch / Extract | 框架工具 adapter，由 Researcher 显式调用 | 原始来源、抽取正文、provider 事实 | 作为“搜索 Agent”伪造证据；snippet 直接当 evidence |
| 5 | Evidence normalize / provenance / coverage gate | Designer/Controller 框架 | EvidenceGraph、CoverageMap、typed finding | 接受 Agent 自报的 coverage 或 provenance |
| 6 | WorldArchitecture | **Direct LLM Engineer** | `WorldArchitectureSourceDraft`：世界边界、实体/关系、工具边界的业务语义 | JSON Schema、rule id、reward、Gate、seed、release 字段 |
| 7 | SharedToolSemantics（每个多工具组） | **Direct LLM Engineer** | 共享 atomicity/concurrency/idempotency/error-policy 的 source draft | 修改冻结 tool id、发明机械 closure |
| 8 | ToolSemantics（每个工具） | **Direct LLM Engineer** | 一个工具的业务 pre/post/error/transition 语义 draft | 写候选源码、决定 task evaluator |
| 9 | WorldRules | **Direct LLM Engineer** | 跨工具/实体的必要业务 invariant `RuleDraft` | 重复 schema、用恒真规则凑数、定义奖励 |
| 10 | CurriculumPlan 与 TaskRequirement source | **Direct LLM Engineer** | task family、objective、可见 actor/tool scope、难度与业务规则 draft | task id/seed、公开/密封划分、reward/termination 的最终合同 |
| 11 | Design compiler + Modeling Gate | Designer 框架 | canonical WorldSpec/ToolContractSet、TaskRequirement、Verifier/Implementation contracts、Design Artifact | 相信模型直接交来的 schema、reward、Gate 或 release 结论 |
| 12a | BuildImplementationPlan | **工具型 Engineer Agent，严格只读** | advisory implementation plan | 写 `candidate/`、运行候选、修改 Design/Task/Verifier、成为 source checkpoint |
| 12b | VerifierIntent | **工具型 Challenger Agent，严格只读** | typed `VerifierIntent`（攻击语义、轨迹骨架、metamorphic/property 建议） | 读取 sealed case、候选可写 workspace、定义 release verdict |
| 13 | Verifier compiler | Judge/Designer 框架 | closed Verifier IR、framework-owned public/sealed 配对 | 执行任意模型代码或让 LLM 选择 case id/seed |
| 14 | CandidateBuild | **工具型 Engineer/Codex Agent，可写候选 workspace** | Runtime、Task Materializer、候选源码；一个不可信 `CandidateCompletion` | 计算/声称 hash、文件大小、source manifest、Gate、Judge 或 release 成功 |
| 15 | source closure / CandidateManifest | Builder 框架 | 对物理 workspace 重新扫描得到的文件清单、hash、size、lockfile 和 manifest | 信任 Agent 文本中的 metadata；读取 sealed 数据 |
| 16 | Integration | Builder/Judge 框架 + 不可信候选进程 | clean install、handshake、unknown-seed public smoke、restart/concurrency/teardown 的 IntegrationReport | 发布；把 Verifier 缺失伪装成 Integration 失败 |
| 17 | independent Judge | Judge 框架 + 不可信候选进程 | materialization/reachability/protocol/property/sealed/deploy Gate 的 JudgeReport/Finding | 修改候选、相信 Builder 自测、以 LLM 分数代替 hard gate |
| 18 | Repair routing / lease | Controller 框架 | owning Artifact、最小 invalidation、RepairAction、预算授权 | 让失败节点无限节点内重试或跨越 owner 盲目重跑 |
| 19 | 定向语义/源码返工（仅出现 Finding 时） | 由 owner 选择：Researcher Agent、Direct LLM Engineer 或 CandidateBuild Agent；路由本身仍由框架决定 | 新 revision 的最小上游提议或候选源码 | 把失败报告当成 Agent 的 release 权力；复用失效 evidence |
| 20 | Package / ReleaseKernel | Controller 框架 | 只在 required hard claims 已满足时形成 ReleaseDossier、package bytes/digest | 修改 Judge verdict、放宽 policy、复制 sealed/secret/evaluator 数据进入包 |
| 21 | Registry publication | Registry 框架 | 复验后原子 `released` EnvironmentPackage / 或诚实终态 | 生成、修复、重新解释 Judge 证据、形成第二个 release verdict |
| 22 | Observe | 框架只读 projection | request/node/artifact/finding/budget/gate/release 的安全 scene | 重试、写 Artifact、发布、暴露 prompt/secret/sealed/evaluator 内容 |

`VerifierIntent` 与 `Interactive Challenger fallback` 使用同一个 Challenger 角色，但不是同一个
Work：前者在 Modeling Gate 后以只读 Design/Task/public evidence 投影产生 verifier proposal；后者
只有参数化 reachability recipe 真实失败且 release policy 需要时，才在 Judge 边界以只读 public
episode 视图运行。二者均是工具型、隔离的 Challenger Agent；后者不是首个 Direct 重写切片的常驻
节点，也不形成第二套验证路径。

`BuildImplementationPlan` 与 `VerifierIntent` 是 Modeling Gate 后的 sibling。CandidateBuild
**只消费**冻结 Design/ImplementationContract 和 BuildImplementationPlan；它不能接收
VerifierIntent、Verifier IR、`.foundry-challenge.json`、sealed case、Judge trace 或 release
policy。Integration 只依赖 Design + Candidate，Candidate 一提交即可开始；慢 Verifier 不得阻塞
或抹掉已经完成的 Integration。Judge 才在 exact passed Integration 与 VerifierBundle 上 join。

## Agent 的唯一 Skill 与工作区

项目开发时的 `.agents/skills/` 不能自动挂入产品运行时。产品运行时只允许下列显式、单一
Skill 绑定：

| Agent Work | 运行时唯一 Skill | workspace / 工具 |
| --- | --- | --- |
| Researcher | `research-world-evidence` | staged evidence 只读目录；显式 search/fetch/extract |
| BuildImplementationPlan | `engineer-build-planning` | 只读的 Design/contract 投影；不能出现 `candidate/` 写入 |
| VerifierIntent / interactive Challenger fallback | `challenge-agent-world` | 只读 Design/Task/public episode 视图；不能读 sealed 或候选可写目录 |
| CandidateBuild | `engineer-environment-codegen` | 仅可写 candidate workspace；可使用受控 shell/`uv` 完成源码工作 |

Direct LLM 的 World 语义节点不加载 Skill、不获得工具、不使用 workspace。没有“环境默认
Skill”、项目 Agent hook、MCP 或全局凭证的隐式继承。

## 最小配置，不引入 profile 平台

配置只需要两个执行 route 和 Research provider；节点声明使用哪一个 route。`profile` 只是以后
审计所需的不可变解析结果，不应先实现为一套通用配置产品。

两条 route 都只能经 `InvocationBackend` 进入：`direct` 是无工具的 structured-chat
adapter，`agent` 是真实 Codex SDK/session/workspace adapter。pipeline core 不直接调用任一
provider 或 SDK。

当前 Direct cleanroom 的 `agent` adapter 就是实现上限：锁定的 `openai-codex` Python SDK、
三字段 `AgentRoute(model/base_url/api_key_env)`、一个 ephemeral `AsyncCodex` thread、固定
`Sandbox.full_access`、一个临时 `CODEX_HOME` 和一个 Runtime Skill bundle。不得从旧实现迁入
ProfileResolver、capability/permission matrix、可配置 sandbox、Hook/MCP 继承、SDK worker 协议或
profile/plugin DSL；临时 `CODEX_HOME` 只用于可验证 Skill discovery，不是新权限系统。

```yaml
routes:
  direct:
    kind: direct_llm
    primary: gpt-5.6-luna
    fallback: gpt-5.3-codex-spark # 仅 primary 给出 typed retryable failure 时
  agent:
    kind: codex_agent
    primary: gpt-5.6-luna        # 必须通过真实 SDK/session/tool/workspace preflight
    fallback: gpt-5.3-codex-spark

nodes:
  research: {route: agent, skill: research-world-evidence}
  world_semantics: {route: direct}
  build_implementation_plan: {route: agent, skill: engineer-build-planning}
  verifier_intent: {route: agent, skill: challenge-agent-world}
  candidate_build: {route: agent, skill: engineer-environment-codegen}
```

`gpt-5.6-luna` 的 OpenAI-compatible chat endpoint 可以优先承担 Direct LLM；它**不能**仅因
能返回 chat completion 就被称作 Codex Agent。只有通过真实 Agent SDK 的 session、Skill、工具与
workspace 验收，才可替换 `agent` route 的模型。否则 CandidateBuild/Research 必须使用已验证的
`gpt-5.6-luna`（或同等 Agent-capable fallback），不能退化成 HTTP 文本生成器。

Search/Fetch/Extract provider（例如 SearxNG、Jina Reader）是 `research` 配置，独立于模型 route；
它们是 Researcher 可调用的工具，不是 Agent 或 Design 的隐式能力。

## Complete v1 的分 child 实现边界

实现顺序由父任务 `08-11-foundry-complete-v1` 和四个可独立验收的 child 固定；树位置不替代
child 中写明的精确 commit/contract 依赖：

1. **Direct graph foundation**（`08-10-direct-foundry-minimal-dag`）先实现两个轻量领域图、
   Runtime/Materializer、独立 Judge、Registry 发布和最小 Observe，并用一次真实请求抵达 Registry。
   它只冻结 Repair/Expand/Consumer 会消费的 Work、Finding、package 与 lineage handoff，不实现
   后续控制行为。
2. **Bounded Repair**（`08-11-foundry-bounded-repair`）在精确 Direct commit 上增加 framework-owned
   定向返工、revision/invalidation 与全局小预算；不增加 LLM Router 或 scheduler 平台。
3. **Expand and multi-parent**（`08-11-foundry-expand-multiparent`）实现一个 `directed@1` Campaign、
   最小语义 Operator、真实技术证据、单父与有用双父证明。每次使用父 package 前读取当前 Registry
   状态；quarantine/supersession 只追加 blocked admission，不改冻结 CampaignSnapshot。候选的
   execution、hard-gate、release 状态分离，基础设施错误不当作低质量候选。
4. **Consumer/SFT/RL**（`08-11-foundry-consumer-sft-rl`）从精确 release 冻结 Suite，每个新 Episode
   再做当前 Registry admission。外部只提交 task selection；`initial_config` 由 Materializer 产生，
   经 Consumer 私有 handoff 进入 Runtime，不进入 SFT、RL 输入、日志或 Observe。

所有 child 复用同一 Artifact、Judge、ReleaseKernel、Registry 和两个领域图，不增加通用 Graph
engine、动态 scheduler、Policy/plugin 平台、自动源码 merger、第二个 Builder/Judge/Registry、训练器、
泛化 profile/权限系统或兼容旧 runtime 的路径。Observe 始终只是安全 read model；每个 child 的
单元测试、graph 绿灯或模型 JSON 都不能替代对应的真实边界证明。

## 每次改动前的阅读门

实现或修复上述任一逻辑边界前，先阅读主文档的相关段落和本文；写出产品目标、改变的 handoff、
下游消费者、唯一 owner、最小 proof 与非目标。随后提交跨层 critic；`block` 必须修订计划后再审，
只有 `allow` 可以派发实现 Agent。真实终态额外遵循 `Observe -> Debug -> plan -> critic -> proof -> Observe`。

## 实时回顾，不是一次性文档阅读

这不是新节点、Artifact 或 Agent。每个关键节点族的进入和退出、每个 child-task 边界、真实 proof
终态、release 决策以及 legacy disposition 都做一次极短的 Product Alignment Checkpoint：

1. 重述目标：自然语言需求是否仍在朝独立验证、可发布 EnvironmentPackage 前进；
2. 说明本次 handoff 的 producer、consumer、唯一 framework owner 和已提交 evidence；
3. 检查下一节点是否真的能消费语义，而非只满足 schema；
4. 明确仍未证明的下游边界，禁止把局部绿灯当作产品完成；
5. 若发现 drift、遗漏或跨节点不兼容，停止派发，回到 plan -> cross-layer critic；真实失败先读 Observe。

该 checkpoint 只写入活动任务和安全 Observe 事实，不包含 prompt、secret、sealed case 或 evaluator 内容。
