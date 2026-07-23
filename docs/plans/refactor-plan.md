# Agent World Foundry —— 端到端跑通 + 环路稳定 重构实现计划

> 状态（2026-07-23）：待验证的重构假设输入，不是可直接执行的顺序。
> 本文保留北极星、坏例线索和候选方案；执行次序、证据等级、版本控制及完成定义以
> [refactor-plan-calibration.md](refactor-plan-calibration.md) 为准。尤其不得把本文对
> typed hole、跨 scope 复用或只执行一次的叙述当作已证明的架构事实。

## 0. 北极星（不可违背，任何阶段偏离即视为跑偏）

生成物是**给 RL 训练用的确定性、不说谎的可执行环境**。状态转移由**生成的代码**拥有；
LLM 永远只做研究、语义提案、代码生成、语义质疑。禁止 mock / template / 固定 replay /
固定环境 id / LLM 文本模拟 作为成功路径。**"放松校验以通过" = 跑偏。** 交付物是
方法论论文 + 一批真实可用环境。

本计划的目标不是"让它勉强跑到 Registry"，而是让**反馈环收敛**：每一轮迭代要么向前，
要么以有信息的方式停止，绝不无界回退、绝不震荡。

---

## 1. 设计思想（先想清楚"为什么这样设计"）

### 1.1 根因回顾（三 Agent 并行取证已确认）
1. **收敛经济学 × 语义层"一次成型的形式化 IR"**：每次真跑都重烧 ~138s Research，然后死在
   语义设计层某个*新*边界（BC-29→BC-40 全部聚集在此）。该层要求 LLM 一次性产出全类型、
   交叉引用一致、RFC-6901 正确的形式化 IR，并在**提案时**刚性校验。
2. **BC-08 最贵边界的重复真执行**：Integration 与 ReleaseAssurance 对同一字节重复跑
   install/supply_chain/static/public/protocol/materialization。
3. **双控制面债务（局部化于 Evolve/Expansion）**：Direct 已切到 WorkScheduler；遗留
   direct-design 死代码 + expansion 单体编排 (~2860 行) 仍在，且 Expansion 绕过共享
   WorkGraph 与全局修复账本（违反 FR-1）。

同时确认**保留**：新控制面反馈环设计是健全的（端点由图边派生、跳距有界、兄弟保留、无无界 re-ask）。

### 1.2 环路稳定性 —— 这是控制论问题，不是工程问题
LLM 每次看到完整约束表却无法同时满足全部，于是"修 A 破 B"，在节点内/节点间来回震荡。
真正的解决办法不是"多校验/多回退"，而是把每一轮迭代变成**收缩映射（contraction）**：

**稳定性四条硬不变量（贯穿全设计）：**
- **S1 单洞独立性**：每个语义提案被拆成一组*互相独立、各自可校验*的"洞"（typed hole）。
  修一个洞不可能破坏另一个洞 → 消除节点内震荡的结构根源。
- **S2 严格单调**：节点内每次重试后，"未闭合问题集合"必须严格变小（monotone decrease），
  否则不是重试而是失败。代码强制此不变量。
- **S3 有界回跳**：跳距 0=本地纠正、1=一跳父级（需因果证据）、≥2=人工。已在新面存在，保留并全局唯一化。
- **S4 无进展终止**：同一 (Artifact 坐标 + input_fingerprint) 的重复失败即刻收敛为
  honest 失败（`_fail_head`），绝不回到起点重烧 Research。

### 1.3 核心手法：把"自由提案+刚性校验"翻转为"脚手架+受限填洞"
现状：LLM 自由产出形式化 IR，代码事后刚性校验（失败面巨大、且每次重跑烧 Research）。
目标：**代码先编译一个带 typed hole 的脚手架，LLM 只填洞（从冻结目录里选，或写有界业务散文），
代码确定性地组装 IR。**

这不是新发明——`rule_context.materialize_tool_semantics_bindings` 已经在 **1 个节点**
（ToolSemantics）上这么做了：Agent 只选 binding_id，代码 `RuleContextCatalog.for_tool`
派生具体指针/集合/主键/value_type，拒绝一切未绑定逃逸。docstring 明说这是"唯一 rule context
完全冻结的边界"。**本计划把它从 1 个节点推广到全部语义节点。**

关键：机械性事实（schema 节点 id、RFC-6901 指针、rule 命名空间、evidence/claim 交叉引用键、
tool-id 集合划分、clause_id）——这些**不是业务决策**，是从上游产物**可确定性派生**的，
必须由代码拥有。LLM 只保留*真正的业务语义选择*（选哪个前置条件、后置写哪个字段、
课程难度梯度、奖励语义）。

**这不违背北极星**：脚手架是从 LLM 的上游业务选择（研究得到的实体/工具）派生的，
不是固定模板。同一世界的实体/工具不同，脚手架就不同（与现有 tool-batch rule_id
`rule:{tool_id}:{section}:{index}` 同理）。它消除的是"机械格式对不对"这类无训练价值的失败，
保留的是"业务语义对不对"这类真正需要 LLM 的判断。

### 1.4 验证左移 + 三种物理信号分离
你反复强调：验证要减轻人力、给 agent 有价值信号、且不能让流水线过长。方案：
- **提案时**只做*结构性*校验（脚手架保证的东西：类型、指针存在性、引用闭合）——这类校验
  因为脚手架保证，几乎必过，不再是失败源。
- **"到底能不能跑"**这类唯一真正保护训练环境的信号，**下沉到真执行边界**（Integration），
  在那里给出最可行动的反馈，并**尽早**（左移到 Integration 而非 Release）。
- **三种物理信号成为一等类型**，不再用 `hybrid` 混淆：
  - `StaticCheck`（L0/L1，代码，确定性，无权威）
  - `ExecutionCheck`（L1/L3，真执行，是唯一能判"能跑"的）
  - `AdvisoryCheck`（L2，LLM 质疑，只产证据，永不授权 readiness/repair）
  删除 `feedback.py:26` 的 `hybrid`；把"LLM 提案成本"与"确定性评估成本"拆成两个独立字段
  （`ProposalOp` vs `ValidationOp`），这样调度器能分别核算预算、分别限流。

### 1.5 划线立场（回答之前悬而未决的问题）
**必须保留的刚性提案时校验**（因为它们保护训练环境不说谎）：仅限脚手架*无法*保证、
且一旦错误会让生成环境"假成功"的语义不变量——例如后置条件是否真的写了它声称写的状态字段、
奖励是否绑定到可观测状态而非 LLM 判断。
**必须下沉/删除的过度校验**：一切机械格式正确性（指针语法、id 命名、集合划分、交叉引用键）——
这些改由脚手架保证或代码派生，不再在提案时刚性拒绝。

---

## 2. 目标架构（组件可全变，以下是变更后形态）

```
生成/扩展 共用同一 GenerationWorkGraph：
Research → Architecture → Behavior → Rules → Curriculum → ModelingBoundary
        → Build ‖ VerifierIntent → Integration → ReleaseAssurance → Package → Registry

每个语义节点 = Scaffold(code) → HoleSet(schema) → Fill(LLM, 选目录/写有界散文)
             → Assemble(code, 确定性组装 IR) → StaticCheck(几乎必过)
真执行只在 Integration 发生一次；ReleaseAssurance 只做 Integration 未覆盖的增量检查。
所有修复经由单一 WorkRepairLedger + 单一全局 BudgetLedger。
```

---

## 3. 分阶段实现（可分阶段验证，非大爆炸重写）

> 审计教训：先跑垂直切片，再收紧。最高杠杆是先解决收敛经济学，否则每轮调试都烧 Research。

### Phase 0 —— 分段·并行·可观测 测试/调试底座（最高优先，先做）
**问题**：现状是"整条流水线测试，断了从头来"。已确认根：`resume_generation`
(controller.py:713) 只从显式终止失败恢复；`_recover_direct_design_checkpoint` (4018)
只在**整个 design 层完整通过**时才复用——语义层中途死（BC-29→BC-40 聚集处）就没有完整
checkpoint，于是重跑整个 design 层含 ~138s Research。缺的是**节点(WorkGraph 坐标)级、
按 fingerprint 的 commit 复用**（新面已有键控：head 按 `(definition_digest,
input_fingerprint)`，work_runtime.py:1156 `supersede_stale` 连未变更终态都拒绝重跑）。

**红线（北极星）**：分段测试里，捕获的上游 commit 只能当**输入**；被测节点自己仍真跑。
绝不能把捕获产物当作被测节点的**输出**塞回——那是 fake replay，直接违背"不说谎环境"。

**0a 跨进程节点级复用**：新 `generate`/诊断入口对已成功坐标按 fingerprint 命中缓存跳过
（不只"整个 design 全过"才复用）。提供 `--from <coordinate>` 只重跑该坐标及下游。
**0b 分段测试** `test-node <coordinate>`：加载真实上游 commit 当输入，只跑这一节点
（真 backend/真执行），观测 HoleSet / 组装 IR / ValidationReport / 预算。
**0c 接缝契约测试**：纯结构断言"上游产物是下游 scaffold 合法输入"，确定性、便宜、不烧 LLM，
先跑几秒即能定位 handoff 断裂。
**0d 分段并行**：DAG 无依赖坐标并行；同一坐标多变体(不同 prompt/policy)对同一真实输入
并行对比——调收敛的利器。
**0e 可观测一等公民（AI 自我提升基石）**：每 attempt 产出结构化、因果链接
(attempt→report→eval→repair)、带成本标注(按角色/模型分的 token + wall 秒)的**可查**记录；
严守安全线（密钥/拒绝值/provider 转录绝不入库）。
**0f 成本核算**：全局 BudgetLedger 分解到 坐标/角色/attempt，让"Research 138s、语义层
N token M 次重试"可见可优化。
**0g Evolve 维度（关键——批量交付物的生产线，收敛经济学最要命处）**：Evolve 演化出"一批
多样化环境"，是目的的核心交付物；一个 campaign 跑几十上百候选，重烧 Research/候选炸掉整场重来
在批量尺度是灾难。因此本底座必须服务 Evolve：
- **scope-generic**：0a-0f 全建在 WorkGraph/WorkScheduler/telemetry/budget 原语上（Direct 已
  在其上），**不写 Direct 专用逻辑**；Phase 4 把 Expansion 并入同一 WorkGraph 后每个候选自动继承。
- **跨 scope 复用（修 RISK-1）**：今天 `find_historical_commit` scope 绑定→兄弟候选零复用。
  复用键改为 `(input_fingerprint + definition_digest + 代码/模型版本)`，匹配即跨 scope 命中，
  候选间共享的上游阶段(Research/Architecture)自动复用。
- **per-candidate 可观测/成本**：哪个候选/坐标烧多少 token·秒、第几次重试收敛/放弃，一眼可查。

**已定决策（用户 2026-07-22 拍板，不管旧行为兼容）**：
- request_id 从 need fingerprint 确定性派生，默认自动复用已成功节点（Q1=A）。
- `definition_digest` 折入 **leaf 源码摘要 + 模型版本**，改了某节点代码其缓存自动失效
  （Q2=A，完全重构无妨）——修 agent 标的 RISK-2。

- **验证**：连续两次 generate 第二次 Research 秒级跳过；`test-node` 能对单坐标真跑并输出
  结构化观测；接缝契约测试能独立定位 handoff 断裂；每 attempt 有带成本的结构化记录；
  改一个 leaf 源码后该坐标缓存自动失效、上游不受影响。
- **产出**：迭代成本从小时级降到分钟级，且可对单节点反复重放肉眼验 S2 收缩。这是后续一切前提。

### Phase 1 —— 脚手架化*一个*语义节点（垂直切片，端到端打通）
选 **WorldRules**（rule_id 尚未 code-canonicalize，是当前 fragile surface 之一）。
- 新增 `RuleScaffold`（仿 `RuleContextCatalog.for_tool`）：从上游 Architecture/Behavior
  派生冻结目录（可用集合指针、主键、字段、evidence/claim 引用键、rule 命名空间）。
- 新 HoleSet schema：字段只剩真业务选择（选哪些 precondition/postcondition 语义、绑定哪个
  binding_id），机械字段全删。
- `assemble_world_rules(scaffold, holeset)`：代码派生 rule_id、指针、交叉引用，产出闭合 IR。
- StaticCheck 只校验"洞填全了且各洞独立合法"。
- 删除该节点提案时对机械格式的刚性拒绝路径。
- **验证**：该节点单测 + 真跑穿过 WorldRules 到下一节点，且人为制造一个业务错误时，
  反馈定位到*单个洞*、重试严格单调（S1/S2）。

### Phase 2 —— 推广到其余语义节点
按同样模式改造 Architecture / Behavior / Curriculum / ModelingBoundary / VerifierIntent /
SharedToolSemantics（ToolSemantics 已是样板，作为参照对齐）。
- 移除 `models.py:573-580` 仍 schema-legal 的 raw pointer 变体（`RuleReferenceDraft`/
  `RuleLookupByKeyDraft`），只保留 binding 变体——闭掉逃逸。
- 每个节点都产出独立 typed hole → 全局满足 S1。
- **验证**：全语义层真跑穿过，不再死在 BC-29→BC-40 那类机械边界。

### Phase 3 —— 消除 BC-08 重复真执行
- Integration 产出 **digest/toolchain/profile 绑定**的 `ExecutionCheck` 证据。
- ReleaseAssurance 改为：验证 Integration 证据的 digest 绑定仍成立 → **只跑增量检查**
  （reachability/behavior/sealed/deployment），不再重跑 install/supply_chain/static/
  public/protocol/materialization（judge/service.py:642-1016 与 1018-1532 去重）。
- `_record_gate` 按信号种类分桶，不再拍平成单一 GateResult 列表。
- **验证**：最贵边界真执行只发生一次；Release 时长显著下降。

### Phase 4 —— 统一控制面（Expansion 并入共享 WorkGraph）
- Expansion 改为实例化**同一** `GenerationWorkGraph`（FR-1：Generate 与 Expand 同一逻辑图）。
- 删除 controller.py 里手写 `while True` (1505-1567)、`_compile_and_build`/`_judge_and_repair`/
  `_DesignReworkRequired`，改用共享 WorkScheduler + 全局 WorkRepairLedger。
- 删除死代码：`_run_design` (4170)、`_run_direct_design_revision` (4477)、
  `_prepare_direct_release_plan` (7177)，以及遗留 `repair.py` 的 RepairRouter/RepairLedger、
  `decision.py` 的 CodeRouter（新面已取代）。约 -2860 行。
- **Evolve 继承 Phase 0 底座**：一旦每个候选成为同一 WorkGraph 的一个 scope，0a-0g 的
  fingerprint 复用/test-node/可观测/per-coordinate 成本/跨 scope 兄弟复用 全部自动生效。
- **验证**：Expansion 与 Direct 走同一调度器；全局预算/修复账本唯一；无第二条修复路径；
  campaign 内兄弟候选共享上游 commit（跨 scope 复用命中）。

### Phase 5 —— 反馈契约收紧（落实 1.4 的类型）
- `feedback.py`：删 `hybrid`；executor 三分为 `code`/`real_execution`/`llm_advisory`；
  拆分 `proposal_cost` 与 `evaluation_cost` 两字段；重登记所有语义边界。
- 确认 AdvisoryCheck（LLM 质疑）`effect` 只能是 `evidence_only`，永不授 readiness/repair。
- **验证**：所有 FeedbackContract 通过新 `validate_authority`；无任何边界能既提案又授权自己通过。

### Phase 6 —— 环路稳定性硬化 + 全链路真跑
- 在 WorkScheduler 落实 S2（重试后未闭合问题集合严格变小才允许再试，否则 `_fail_head`）、
  S4（同坐标+fingerprint 重复失败即收敛）。
- 全链路真跑 "用户预订宾馆"，要求：要么到 Registry 释放（exit 0），要么在某边界 honest 停止
  （exit 2）且反馈定位到单个可修 Artifact，**绝不回到 Research 重烧**。
- **验证**：连续 N 次真跑，观测无震荡、无无界回退；失败都是"业务语义待人工"而非"机械格式"。

---

## 4. 每阶段验收门槛（防跑偏）
- 任何阶段若出现 mock/template/固定 replay/固定 id/放松校验以过关 → **立即回滚，不计进度**。
- 每阶段结束跑该阶段单测 + 一次相关真跑（用真 InvocationBackend，非 fake codegen）。
- 保持 `.agent-world-live/`、`auth.json`、codex-home 绝不进 git/envpkg/Registry。
- 拒绝值、密钥、私有 verifier case、provider 转录绝不进诊断/Artifact。

## 5. 风险与权衡
- **脚手架派生错误风险**：若代码派生的机械事实本身错了，会静默注入错误 IR。缓解：脚手架派生
  逻辑必须有确定性单测覆盖（它是代码，可测），且 Integration 真执行是最终裁判。
- **业务语义仍可能一次填不对**：这是保留的、有价值的失败——由 S1/S2/S3 有界重试处理，
  实在不行 honest 停止交人工。这正是"减轻人力但不假装成功"。
- **删除 2860 行遗留**：无兼容包袱（用户已批准 clean-break），但需确保新面已覆盖其全部活路径
  （Agent 3 已确认 Direct 已切换、遗留 direct-design 为死代码）。

## 6. 建议执行顺序
Phase 0 → 1（垂直切片，先证明模式可行）→ 2 → 3 → 4 → 5 → 6。
每个 Phase 独立可验证、可回滚。0 和 1 是关键：0 让调试可负担，1 证明"脚手架+填洞"能端到端穿过。
