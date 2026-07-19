# Programmatic Environment Foundry v2 — Product Requirements

> 状态：结构已批准，进入 clean-break 实现。
>
> Source of truth：`docs/agent-world-environment-generation.zh.md`

## 1. Goal

用户提供一条自然语言环境需求，系统自动完成需求研究、工具发现、世界建模、任务与评测设计、真实程序生成、独立验证、定向修复和发布，得到可复现、可验证、可部署的 `EnvironmentPackage`。

因为需求文档、单次模型研究和人工检索覆盖有限，系统还要能围绕 request、package、外部资料和 EnvironmentPool 自动执行更大范围的 Search/Evolve，纵向补全现有环境或横向产生新环境。

训练是 package 的后续可选用途。Generation 和 Expansion 均不得依赖先进行 rollout 或训练。

## 2. Confirmed Decisions

- Direct Generation 是核心必需路径；一个 request 可以独立完成到 package release。
- 开启 Evolve 不改变 Direct Generation：首包始终直接生成；低成本 Discovery 可并行，但使用独立预算且不阻塞首包。
- Expansion 是独立可选路径，主要解决需求和检索覆盖不足。
- Expansion 同时支持纵向 package revision 与横向 new package。
- Training/veRL 是下游 consumer；CapabilityFeedback 只是 Expansion 的可选输入。
- EnvironmentPackage 是唯一发布单位，不建立 Family/CompositeFamily。
- Runtime 状态转移由真实程序执行，不由 LLM 文本模拟。
- 使用真实 InvocationBackend/Codex SDK，不允许 template/mock 成为生产 fallback。
- Release authority 属于 framework Gate，不属于 Agent、Runtime、unit test 或 LLM judge。
- 后置失败必须支持 owning-artifact rework 和传递 invalidation，不盲信上游。
- 删除旧 awm、ABI v1、replay 和固定 stage 兼容路径。
- 专用 Agent 必须隔离 Skills、Hooks、Tools/MCP、HOME、workspace、network、credentials 和 sealed namespace，不能只更换 prompt。
- Expansion 以 tool surface、tool semantics、transition constraints 和 task scope 为主要变异轴；源码 workspace 变异只是 Builder 实现策略。
- 项目和测试均不提供 mock/fake/stub 成功路径；外部能力缺失时诚实失败、skip 或 needs_human。

## 3. Product Modes

### 3.1 Generate

输入：EnvironmentRequest。

输出：released EnvironmentPackage，或结构化 rejected/needs_human/budget_exhausted。

成功条件：真实 Agent + 真实 Runtime + framework verification + clean package；无需 Pool、Expansion 或 Training。

### 3.2 Expand

输入：ExpansionCampaignSpec，包含 request/package anchors、CoverageMap、sources、policy、budget 和 Pool snapshot。

输出：零个或多个 released package revision/new package，以及所有 CandidateOutcome。

成功条件：没有训练反馈时仍可完整 discovery/ask/mutate/compile/tell/checkpoint。

### 3.3 Consume

输入：一个或多个精确 package version。

输出：SuiteSnapshot、rollout/evaluation/training result 和可选 CapabilityFeedback。

成功条件：consumer 不修改历史 release verdict；移除 consumer 不影响 Generate/Expand。

### 3.4 Five Top-level Components

第一版产品结构只实现五个顶层组件：

- FoundryController；
- EnvironmentDesigner；
- EnvironmentBuilder；
- EnvironmentJudge；
- EnvironmentRegistry。

EvidenceGraph、CoverageMap、Agent profiles、Artifact revisions、Runtime supervisor、Verifier IR 和 RepairRouter 必须存在，但作为五个组件的内部机制，不分别建设成顶层服务。Training consumer 在系统外部。

`EnvironmentJob`、`EnvironmentDesign`、`EnvironmentCandidate`、`JudgeReport` 和 released `EnvironmentPackage` 是稳定工作 envelope。Discovery、Expansion 和 lineage 使用这些 envelope 中的 typed Artifact refs 交接，不能因为增加内部 Artifact 就增加顶层服务。

## 4. Product Objects

### 4.1 EnvironmentRequest

包含 need、supplied assets、allowed sources、fidelity、permissions、risk、budget 和 release profile。人不需要预先写完整 WorldSpec。

### 4.2 EvidenceGraph

保存 source、version/hash、time/license、claims、conflicts、inference、assumption 和 tool surface。模型记忆不能冒充 evidence。

### 4.3 CoverageMap

分别记录 evidence discovered、WorldSpec modelled、Runtime implemented、Verifier covered 和 unknown：

- actors/roles；
- entities/resources；
- tools/actions；
- transitions/pre/postconditions；
- errors/partial failure/rollback；
- permission/visibility；
- time/order/expiry；
- concurrency/idempotency；
- constraints/invariants；
- task/difficulty/termination；
- fidelity/divergence。

CoverageMap 是向量与缺口集合，不是单一 coverage score。

### 4.4 WorldSpec

任务、Runtime 和 verifier 的 typed semantic source of truth。包含 WorldBoundary、状态、工具、规则、错误、权限、不变量、task dimensions、fidelity 和 rule-to-evidence links。

### 4.5 EnvironmentPackage

由 stable package_id + immutable version 标识，包含 Runtime、generator、curriculum、public verifier、consumer adapter 和可发布 evidence。不是固定 task/replay。

### 4.6 ExpansionCampaignSpec

包含 anchor refs、coverage/diversity objective、sources、policy、operator catalog、external injection、Pool/Inbox snapshot、optional feedback、release profile、独立 budget、max in-flight、seed 和 stop policy。

### 4.7 ExpansionProposal

Policy 首先产生 `MutationIntent`，Designer 再将其完整化为 typed `SemanticDelta` 和 `ExpansionProposal`。Proposal 必须声明 `target_kind=package_revision|new_package`、anchors/parents、coverage hypothesis、evidence/source、变异前后 ToolContractSet/WorldSpec refs、identity rationale、risk/cost 和 unresolved questions。

### 4.8 CandidateOutcome

包含 terminal status、hard Gate results、coverage gain、behavior descriptors、evidence refs、findings、cost、repair depth、lineage 和 optional training metrics。Core 不生成通用 advantage/fitness。

### 4.9 EnvironmentPool / EnvironmentSuiteSnapshot

Pool 是 Registry query view；SuiteSnapshot 是 consumer 使用的精确 package hashes/versions/weights/curriculum，不共享环境状态。

### 4.10 Discovery、Mutation 与 Lineage Artifacts

- `DiscoveryRunSpec` 绑定 origin GenerateJob、request revision、真实 source/profile、独立预算、权限、优先级和 seed；
- `ExpansionClue` 保存 evidence、tool/workflow hypothesis、coverage 维度、scope relation、feasibility、risk 和 dedup fingerprint；
- `DiscoveryAdmissionDecision` 将 clue 分类为 `hard_correction|in_scope_extension|expansion|reject`，并路由到 Finding、当前 research、Inbox 或 drop；
- `DesignBaselineCheckpoint` 固定首个通过 Modeling Gate 的 request/evidence/coverage/WorldSpec revisions 和 scope cutoff；
- `ExpansionInboxSnapshot` 是 Campaign 消费的不可变 clue/gap 快照；
- `MutationIntent` 保存 parents、clues、operator id/version、parameters、seed 和目标维度；
- `SemanticDelta` 保存 tool surface、tool semantics、state/transition constraints 和 task-scope 变化；
- `SemanticLineage` 保存 parents、clues/evidence、operator trace、变异前后语义 hash 和 IdentityDecision；`ImplementationLineage` 单独保存 workspace、Builder profile/session、dependency/build provenance。

## 5. Generation Requirements

### GEN-01 Request Research

- Research Agent 必须迭代生成 ResearchPlan、调用真实 Web/repo/MCP/API/SDK/CLI/schema tools、检查 gap/conflict 后才完成。
- 原始用户请求、模型记忆或空 search 结果不能伪装成外部 evidence。
- observed fact、inference、product decision 和 assumption 必须区分。

### GEN-02 Coverage

- 每个关键 WorldSpec rule 必须关联 evidence、显式 product decision 或 bounded assumption。
- ReleaseProfile 定义最低 coverage，而非要求现实世界无限完备。
- Unknown 必须显式保留；高风险 unknown 进入 research rework 或 needs_human。

### GEN-03 World Modelling

- WorldSpec 必须通过 schema、reference、reachability、permission、invariant、error/rollback、task satisfiability 和 evidence coverage Gate。
- Task、Runtime、Verifier 只能从同一有效 WorldSpec revision 编译。

### GEN-04 Parallel Compilation

- WorldSpec 有效后，Task/Curriculum、VerifierProposal 和 ImplementationContract 可并行。
- Runtime code generation 不接收 sealed cases 或 expected result。
- Verifier generation/challenge 与 Runtime code generation 使用隔离 session。

### GEN-05 Real Agent Implementation

- 所有开放语义节点通过真实 InvocationBackend。
- Codex SDK adapter 必须支持 stable workspace、thread continuation 和 per-turn sandbox。
- 关闭真实 backend 后 production run 必须 fail/needs_human，不得 template/mock fallback。

### GEN-06 Runtime

- Runtime ABI v2 task-agnostic、versioned、out-of-process。
- 支持 handshake/setup/reset/invoke/observe/close/shutdown。
- Runtime request 不含 task id、case label、expected answer/state、verifier IR 或 release metadata。
- reset seed 可复现；episode 隔离；idempotency key 不重复副作用。

### GEN-07 Verification

- generated unit tests 只作公开诊断证据。
- framework 必须运行 static/type/lint、protocol、property/metamorphic、repair regression、sealed release 和 clean deployment checks。
- LLM 只生成 VerifierProposal；framework compiler 将其限制为 typed IR。
- hard Gate 不能被 novelty、judge score、训练收益或成本抵消。

### GEN-08 Rework

- Gate failure 规范化为 Finding，包含 category、severity、subject revision、evidence、fingerprint 和 disclosure。
- RepairRouter 必须选择 owning Artifact 和 repair scope。
- 实现 bug 优先继续同一 Engineer thread；上游语义修改 invalidates 依赖后代。
- repeated/no-progress 扩大 scope、reject 或 needs_human，不能无限重试。

### GEN-09 Packaging

- envpkg v2 不包含 sealed cases、secret、expected output corpus、absolute workspace path 或 Agent transcript。
- 从空目录/clean container 安装并执行 start/health/reset/invoke/restart/concurrency/teardown/package-relative checks。

## 6. Expansion Requirements

### EXP-01 Independent of Training

- ExpansionCampaign 不要求 CapabilityFeedback 字段存在。
- 所有内置 policy 必须在 optional feedback 为空时可执行。
- Release/selection report 不得把 training utility 设为必填。

### EXP-02 Expansion Sources

至少支持 RequirementGap、WebWorkflow、ToolEcosystem、Repository、PoolNeighborhood、RandomTheme 和 optional CapabilityGap source。

Source 输出 clue + evidence + dedup + risk + unresolved question，不直接输出 released candidate。

### EXP-03 Cheap Admission

在 code generation 前检查：

- relevance to campaign；
- evidence/feasibility；
- permission/risk；
- duplicate/near-duplicate；
- predicted coverage gain；
- budget affordability。

Admission 是成本过滤，不是 release proof。

### EXP-04 Vertical Revision

适用于 WorldBoundary 身份保持的补全：规则、状态、失败、权限、时间、并发、工具、任务和难度。

- 同 package_id，新 immutable version；
- 父 WorldSpec 可作输入，但产出完整新 WorldSpec；
- Runtime/Task/Verifier/Release evidence 全部重新生成或重新证明；
- 旧 version 保持可复现。

### EXP-05 Lateral Package

适用于核心 WorldBoundary 改变、相邻 workflow、工具迁移、跨系统协作、多父代组合或外部新主题。

- 新 package_id；
- parent 只提供 lineage/evidence clue；
- 多父代默认 lateral；
- 必须完整通过 Generate trust path。

### EXP-06 Identity Decision

Proposal 必须根据 actors/authority、system-of-record、resource graph、transition authority、tool namespace 和 core invariants 给出 identity rationale。Framework policy 验证 revision/new-package 声明；不确定时默认 new package，避免污染已有身份。

### EXP-07 Replaceable Policy

Core 只提供 `ask(context_snapshot, checkpoint, budget)->MutationIntentBatch`、`tell(checkpoint, outcomes)->PolicyCheckpoint`、`should_stop(checkpoint, remaining_budget)`。Wide Search、Random、Evolutionary Archive、MAP-Elites/MCTS/Bayesian/RL 可替换，不修改 Generation core。

Policy 只能从固定 Artifact/Pool/Inbox snapshot 选择 parents、clues、operator 和 parameters，不得直接生成 Runtime、修改 Artifact 或绕过 Gate。`tell` 必须对 outcome id 幂等；infrastructure error 不能伪装成低 fitness。

### EXP-08 Search Signals

Policy 可使用 evidence coverage、semantic/structural/behavioral novelty、fidelity、risk、release yield、cost、repair depth 和 optional training utility。Core 不定义强制标量 fitness。

### EXP-09 External Injection

即使采用 parent-based evolution，也必须按 campaign policy 注入外部 search/random clues，避免 Pool 封闭、自我复制和 benchmark overfitting。

### EXP-10 Complete Reverification

Expansion candidate 不继承 parent release verdict、sealed evidence 或 verifier coverage。所有结果回到相同 Generation/Verification/Release path。

### EXP-11 Tool-first Operators

- `ToolSurfaceOperator` 改变 Agent 可见工具集合、namespace、argument/result/error schema、依赖、角色可见性和 observation surface；
- `ToolSemanticsOperator` 改变工具 pre/transition/postcondition、权限效果、错误/partial failure、幂等、retry/timeout、transaction、rollback 或 compensation；
- `TransitionConstraintOperator` 改变 state schema、状态机、资源/时间/顺序/并发约束和跨工具不变量；
- `TaskScopeOperator` 只在既有 ToolContract/WorldSpec 内改变 goal/initial-state distribution、工具组合、难度、规模、可观察性和终止条件；需要新工具或状态时必须升级为语义 operator；
- `CompositeOperator` 可组合上述 delta；WorldBoundary 变化由 framework Identity Gate 从完整 SemanticDelta 判定，不作为主要原子 operator；
- workspace 复用/重构/重写只属于 Builder implementation strategy，不属于 Expansion operator，也不能用源码 diff 冒充环境 novelty。

新增工具必须至少同时具有 ToolSurfaceDelta 和 ToolSemanticsDelta；涉及状态时还必须具有 TransitionConstraintDelta。Operator 必须输出 typed delta、parents、evidence/clue refs、identity intent 和预期 behavior descriptor；实际变化由相同 Judge 行为验证。Workspace 若改变可观察行为却没有对应 SemanticDelta，必须作为未声明行为漂移拒绝。

### EXP-12 Discovery Timing

- Foundry Controller 为 GenerateJob 自动创建可关闭、低优先级、独立预算的 DiscoveryLane；Discovery 不得绕过 Controller 直接修改 Design；
- 基线前、属于原需求且预算允许的 clue 可以更新当前 EvidenceGraph/CoverageMap；
- 基线后或相邻空间的普通扩展 clue 写入 Expansion Inbox，不 invalidates 或阻塞首包；
- 任意时刻若新证据证明当前 hard claim、工具语义、安全或 fidelity 声明错误，必须产生 Finding/rework；已发布时按严重性 quarantine 或 corrective revision；
- 完整 parent-based Evolve 只消费固定 Artifact/Pool/Inbox snapshot，并产生独立 Campaign/Outcome；
- Evolve 失败不能改变原 GenerateJob 或父 package 的 release verdict。

## 7. Shared System Requirements

### SYS-01 Control Plane

使用 immutable Artifact revisions、dependency DAG、events、Gate、budgets、permissions、findings、invalidation、checkpoint 和 release state；不使用固定 S0-S7 pipeline contract。

Direct Generation 使用前台保留容量；Discovery/Evolve 使用独立 budget partition 和并发上限。新 GenerateJob 不得被持续运行的 ExpansionCampaign 饿死。

### SYS-02 Agent Profiles

只定义 Researcher、EnvironmentEngineer、Challenger 三类复用 profile。静态检查、执行器、Verifier compiler 和 release decision 是 framework code，不包装成额外 Agent。

每次 invocation 必须物化不可变 `ResolvedAgentProfile`：backend/model、instructions、Skill hashes、Hook hashes、typed tool/MCP allowlist、sandbox、独立 HOME/workspace、network domains、credential handles、budget、output/completion contract 和 continuation policy。生产调用不得继承 ambient user Skills/Hooks/MCP；未声明 capability 默认拒绝并审计。

### SYS-03 Invocation Adapter

Backend SDK 差异停留在 adapter；pipeline/control core 不直接调用 Codex/OpenAI SDK。Profile 明确 Skills、Hooks、tools、sandbox、workspace、permissions、budget、output contract 和 continuation。

### SYS-04 Registry

保存 package/version/hash、WorldBoundary、lineage、CoverageMap、fingerprints、Gate、findings、cost、Expansion outcomes 和 optional consumer metrics。Registry 是唯一 metadata truth。

### SYS-05 Security

Generated code 默认不可信；network/filesystem/process/secret/cost least privilege。Secret 和 sealed data 使用不同 access namespace，均不进入 prompt/package/log。

### SYS-06 Observability

每个 run/campaign 可查看 artifact DAG、active findings、agent sessions、Gate evidence、budget、repair history、lineage、terminal reason 和 next ready work。

### SYS-07 Feedback and bounded Agent transactions

- 每个 validator、Gate、LLM review 和 repair trigger 必须有完整 FeedbackContract；
- JSON/schema/ref/type/protocol/budget/retry/router/invalidation/release 由代码拥有；
- LLM 只拥有 evidence/world/tool/task/adversarial 语义 proposal，输出仍由 framework 编译；
- 首次真实 Build 前 Agent turn 硬上限 9、典型 7，调用数不得按实体数量线性增长；
- Tool Semantics 按 2–3 个共享状态/namespace 的工具有界分批；
- 每个语义批次最多一次普通 correction；generic root error 不得重复调用模型；
- 自动 backjump 最大 1，且必须有 causal evidence；Research 只接受 hard external correction；
- 当前不引入第二 DiagnosticCandidate；Builder commit 后立即运行的 Integration 必须绑定最终 candidate digest。未来 staged Builder 只有在 live metrics 达到预先声明阈值后才能立项，且所有最终 Gate 必须对 final digest 重跑。

## 8. Optional Consumption Requirements

- Framework-neutral local consumer 先提供 reset/step/reward/termination/trace contract。
- veRL adapter 只映射 environment side；model inference、tokenization、loss mask 和 optimization 由 veRL 所有。
- SuiteSnapshot 精确固定 package hash/version、weight、curriculum 和 adapter version。
- CapabilityFeedback 可生成 Expansion clue，但不能修改历史 release verdict。
- 删除所有 training/feedback components 后，Generate 与 Expand acceptance tests 仍必须通过。

## 9. Acceptance Criteria

### AC-1 Direct Generation

从一个从未写入 fixture 的自然语言需求开始：真实 research、WorldSpec、Codex codegen、真实失败 same-thread repair、ABI v2 execution、sealed evaluation、clean deployment 和 envpkg v2 release 全部运行；无 backend 时诚实失败。

### AC-2 Unknown Episodes

Package 对未见 seed/entity/valid parameter/action order 产生有效 episode；不能仅回放生成时 task。

### AC-3 Upstream Rework

后置 property failure 能定位 WorldSpec/Runtime/Task/Verifier owner，创建新 revision，只重新编译受影响后代，并保留审计。

### AC-4 Training-free Expansion

在 CapabilityFeedback 为空时，从一个 released anchor 执行 ExpansionCampaign，产生至少一个 vertical 和一个 lateral proposal，二者进入同一 trust path；至少一个候选被诚实拒绝。

### AC-5 Policy Comparison

相同 anchor/Pool snapshot/release profile/budget 下运行 Wide Search、Random Baseline 和 Evolutionary Archive，报告 coverage、diversity、yield、cost 和 lineage；更换 policy 不改 Generation code。

至少一个实验分别覆盖 ToolSurface、ToolSemantics/TransitionConstraint 和 TaskScope 变异，并由真实 Runtime handshake/trace 证明行为或任务分布差异；只修改 workspace 源码不计入 evolution success，未声明行为漂移必须被拒绝。

### AC-6 Optional Consumption

多个 package 组成 Suite，可由 local consumer/veRL adapter 使用；训练反馈可选回流，缺失时 Expansion 行为有效。

### AC-7 No Legacy Success Path

旧 awm、ABI v1、replay、generated verify、in-process verifier、fixed stage 和 stub runner 不可到达 production success。

### AC-8 Non-blocking Discovery and Lineage

- 真实 Discovery 成功时，clue 保存来源 provenance 并经过 Admission 进入当前 research、Finding 或 Expansion Inbox；
- Discovery 权限拒绝、provider 失败或预算耗尽时，Direct Generation 仍可独立发布；
- 基线后的 adjacent clue 不移动首包范围，hard correction 则真实触发 Finding/rework；
- 发布的 Expansion result 可追溯到 SemanticLineage 和独立 ImplementationLineage；
- 涉及 Agent、Search、Runtime、Judge 和 Release 的 acceptance 不得使用 mock/fake/stub；外部能力缺失只能明确 skip/needs_human，不能计作 PASS。

## 10. Out of Scope

- 在第一个 package 发布前要求训练 Agent；
- 用训练收益证明 environment correctness；
- 重写 veRL 或其他训练框架；
- 自动保证 local simulation 与生产系统完全等价；
- 为旧 awm/ABI/package 保留 compatibility facade；
- 用固定环境或预写 fixture 作为 Foundry 成功证明。

## 11. Resolved Product Decision

每次 GenerateJob 默认创建独立小预算的 DiscoveryLane，但它不阻塞首包。首包发布后，仅当 request/campaign 明确分配 Expansion budget 时自动启动后台 ExpansionCampaign；否则 clue 保留在 Expansion Inbox，等待显式 `expand`。这保证主动发现不会消失，同时不隐式产生无限模型与执行成本。
