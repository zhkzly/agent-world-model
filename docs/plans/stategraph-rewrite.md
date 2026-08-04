# StateGraph 重写：自持有的确定性图执行控制面

> 状态（2026-08-04）：批准的重写主线。取代"grep 删死代码"式瘦身（只到 ~8%，因为
> 大头是**结构性重复**不是孤立死代码）。本文是唯一权威设计，落地即以本文为准。
> 输入依据：`refactor-plan.md`(北极星+分阶段)、`refactor-plan-calibration.md`(证据纪律)、
> 记忆里的 4 类 bad-case 归类、两份现状调研（contracts/persistence + WorkGraph 执行模型）。

## 0. 北极星（不可违背）

生成物是给 RL 训练用的**确定性、不说谎的可执行环境**。状态转移由**生成的代码**拥有；
LLM 只做研究、语义提案、代码生成、语义质疑。禁止 mock/template/固定 replay/固定 id/
LLM 文本模拟作为成功路径。"放松校验以通过"=跑偏。**框架代码**（不是任何 Agent、不是任何
第三方库）拥有 Artifact 身份、Gate 判定、预算租约、rework-DAG、release authority。

核心成功路径（必保）：需求 → Controller → Designer(证据+WorldSpec) → Builder(真实代码) →
Challenger(Verifier IR) → Integration(干净安装+协议/冒烟) → Release readiness →
Judge(真 rollout + property/sealed Gate) → Release Kernel → Registry → SuiteSnapshot → RPC/veRL。

3 个隔离 Agent 角色：Researcher、Environment Engineer、Challenger。

必保 CLI：doctor / generate / run(resume,inspect) / registry /
expand(start,resume,inspect —— Evolve 通道，E2E 必含) / suite / feedback / observe / metrics。

## 1. 为什么重写：现状控制面的结构病

现状控制面把"一个图执行器"摊成了 8+ 个互相重复的子系统，累计 ~29k 行（control/ 包）：
- `work_graph.py`(4220) 编译 4 个 epoch 的 `WorkDefinition` 图，3 个 compile 入口；
- `work_scheduler.py`(1025) `snapshot()`→`run_until_stalled()` 是真正的 step loop；
- `direct_runner.py`(2818) 又内联了一遍 readiness 过滤（与 scheduler 重复）；
- `work_runtime.py`(5175) `_authorize_next_or_fail` 用 5 个 `no_*_authority` 布尔做修复授权；
- `leaf_executor.py`(2059) `execute` 有 7+ 个 except 分支各产不同形状的终态；
- `work_store.py`(WorkControlHead,按 WorkCoordinate) vs `direct_store.py`(DirectJobHead,按
  request_id) 两套独立 CAS head；`repair.py`(RepairLedger) vs `work_repair.py`(WorkRepairLedger)
  两套修复账本；`campaign.py`/`campaign_store.py` 又把 job/attempt/head 概念重造一遍(Expand 专用)。

**A 类 bad-case（控制面/resume 膨胀，图重写直接消除）**：verifier-intent-release-gate 死锁、
kill-generate-orphan-head 中毒、resume-id-topology 缺反向索引、workcontrolruntime-ctor-drift、
descendant-topology-parent-commit-inactive。全部源于"同一角色多套实现 + resume 靠撬 head 反查"。

结论：不是删代码能解决的，是**把 N 套控制原语坍缩成一套 StateGraph**。删除随之而来（预计
control/ 从 ~29k 降到 <6k），但删除是坍缩的副产品，不是目标。

## 2. 目标：自建薄图执行器（不用 langgraph 库）

采用 LangGraph 的**心智模型**，但**自建**——不引入 langgraph 库。原因：其 checkpointer/
TypedDict state 是弱合同（松散 merge），会稀释框架对 release/budget/CAS 的自持有权威。
我们要确定性、内容寻址、fail-closed 的图执行器。

四个一等概念：

- **State**：一个持久、内容寻址的对象，携带一次 run 的全部产物（need/design/candidate/
  verifier/findings/budget/per-node 状态切片）。每个字段是 `ArtifactRef` 或 typed 值。
  State 变更 = 追加一个新的内容寻址版本（不可变，可 resume）。
- **Node**：`async (State, NodeContext) -> NodeResult` 的纯函数式阶段。一个 Node 对应流水线
  一个阶段（research/architecture/build/verifier_intent/integration/judge/release/...）。
  Node 只读它声明的输入切片、只写它声明的输出切片。**执行体就是把 designer/judge/builder
  现有的 `_compile_*`/`_validate_*` 私有 helper 直接抬进来**（它们已是纯函数形状）。
- **Edge（前向）**：拓扑推进边。声明式 DAG：`node -> [下游 node]`。ready = 所有上游输出切片
  已 commit。取代 `work_graph.py` 的 4-epoch 编译 + 3 compile 入口。
- **Router（反馈边）**：`(State, Finding) -> RerunTarget | HonestStop`。judge/challenger 的
  actionable finding 经 router 决定回跑哪个 node（跳距 0/1/≥2=人工），取代
  `_route_parent_repair_if_requested` + `_authorize_next_or_fail` 的 5-布尔授权。

### 2.1 State schema（内容寻址、可 resume）

```python
class RunState(V2Contract):
    request_id: Identifier              # 从 need fingerprint 确定性派生
    scope_id: Identifier                # generate=self / expand=candidate；同一 schema
    need: EnvironmentRequest
    budget: BudgetLease                 # 全局唯一预算租约（复用现有 contracts/jobs Budget）
    slices: dict[Identifier, NodeSlice] # 每 node 一个切片：输出 ArtifactRef + 状态
    findings: tuple[Finding, ...]       # 累积的 actionable finding（router 输入）
    # 无 telemetry：观测是 bolt-on 侧写，不进 State 控制决策
```

`NodeSlice` 携带该节点的 status(pending/running/committed/failed/honest_stop)、
输出 `ArtifactRef`、`input_fingerprint`、`definition_digest`(折入 leaf 源码摘要+模型版本→
改代码自动失效缓存)、以及**活会话状态**（continuation seed，无法从 commit 图重建，作为切片
字段而非独立 store）。resume 语义坍缩为一句话：**切片非 committed → 跑它**。

### 2.2 Node 契约

```python
class NodeResult(V2Contract):
    status: Literal["committed", "failed", "honest_stop"]
    outputs: dict[Identifier, ArtifactRef]       # 写入 State 切片
    report: ValidationReport | None              # C 类保真：typed diagnostic
    usage: BudgetUsage                            # 记账（B 类物理信号）
    rerun_request: RerunRequest | None            # 请求 router 回跳（附因果证据）
```

取代 leaf_executor 的 7+ except 分支——**每个 Node 返回唯一 typed `NodeResult`**，异常
在执行器边界统一分类成 3 条 lane（见 §2.4）。

### 2.3 前向拓扑（generate 与 expand 同一图）

```
research → architecture → behavior → rules → curriculum → modeling_boundary
        → build ‖ verifier_intent → integration → release_assurance
        → judge → release → registry_publish
```

expand 只是换 scope_id + 一个 seed 节点（改 tool surface/语义/状态约束/task scope）后**接同一
图**回到 research/design 全生成。删除 `expansion_runner.py`(2852) + `campaign*.py` 的第二控制面。

### 2.4 三条 lane 分类（B/C 类保真，唯一权威=ValidationReport.status）

执行器在 Node 边界把结果分成且仅分成三类：
- **infra/transport retryable**（B 类物理失败）：provider 502/隧道、idle-timeout、token/wall
  lease 欠配 → 有界重试 + 预算 resize，**不改设计**。收敛到 3-4 种 recovery，不是 1 种。
- **design defect actionable**（C 类，灵魂，只精修不砍）：typed validator 抛 PydanticCustomError
  → ValidationReport.status=failed → router 回跳。Agent 输入值绝不进 code/message。
- **framework diagnosis**（无 owner）：终止为 honest framework_diagnostic，不烧 retry/不放松 Gate。

### 2.5 保留、坍缩、删除清单

**保留（直接复用，不重写）**：`contracts/base.py`(V2Contract/ArtifactRef/ContentHash)、
`contracts/jobs.py`(Budget 12 维向量)、`artifact_store.py`(内容寻址 CAS + SQLite 投影)、
designer/judge/builder 的 `_compile_*`/`_validate_*`/`_research_*` 纯 helper、typed validator
协议(diagnostic-fidelity)、rule_context catalog(脚手架填洞样板)。

**坍缩成 StateGraph 单套**：work_graph + work_scheduler + direct_runner + work_runtime +
leaf_executor → `graph/`(executor + state + node + router)；WorkControlHead + DirectJobHead →
单一按 (scope_id, node) 键的 head；RepairLedger + WorkRepairLedger → State.findings + router；
NodeContinuationStore/SemanticRepairSeedStore → NodeSlice 字段；campaign*/expansion_runner →
同图 + seed 节点。acceptance_digest/definition_digest → 从**一份字段分类**派生，不再两套手维护列表。

**删除**：test_*/observe_* 冗余 runner、back-compat 序列化器(RepairPolicy model_serializer)、
`_execute_direct_locked` 纯 pass-through、direct-design 死 recovery 代码。

## 3. 分阶段落地（每阶段独立可验证、可回滚）

- **P0 图执行器骨架**：新 `agent_world/graph/`：`state.py`(RunState/NodeSlice/NodeResult)、
  `node.py`(Node 协议+registry)、`edge.py`(前向 DAG+ready 判定)、`router.py`(反馈跳跃)、
  `executor.py`(step loop：坍缩 run_until_stalled)、`head.py`(单一 CAS head)。纯单测覆盖
  ready/commit/resume/router 跳距，不烧 LLM。
- **P1 迁一个真节点端到端**：把 research→architecture 两个 Node 接上真 backend + artifact_store，
  证明 State 追加、resume 短路、finding 回跳可用。
- **P2 迁全部 design 语义节点**：behavior/rules/curriculum/modeling_boundary/verifier_intent，
  抬 designer 现有 helper 进 Node 体；typed diagnostic 保真。
- **P3 迁 build/integration/judge/release/registry**：judge `evaluate()` 850 行内联 gate loop
  拆成 Node（内部 `_` helper 已现成）；BC-08 重复真执行去重（Integration 一次，Release 增量）。
- **P4 expand 接同图**：seed 节点 + 同图；删 expansion_runner/campaign 第二控制面。
- **P5 老 control/ 退役**：rg + call graph 证明无引用后删除 8 子系统；delta 应 -20k 行量级。
- **P6 E2E 全路径真跑**：generate + expand 两条都到 release，`refactor-plan-calibration.md`
  的完成定义为准（真 Search/Fetch、真 backend、真子进程、原子 Registry released）。

## 4. 验收红线（防跑偏，每阶段查）
- 出现 mock/template/固定 replay/固定 id/放松校验以过关 → 立即回滚，不计进度。
- 每阶段跑该阶段单测 + 一次相关真跑（真 InvocationBackend）。
- 凭证/base URL/拒绝值/sealed case/provider 转录绝不进 git/Artifact/日志/包。
- 每个 Node/Edge/Router 决策必须对得上 §0 北极星与必保 CLI / 组件语义（observe 分层、expand E2E）。
- 不 commit git 直到用户明确同意（Task #5 未授权）。
