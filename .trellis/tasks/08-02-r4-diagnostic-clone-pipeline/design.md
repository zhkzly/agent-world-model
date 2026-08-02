# Design — DiagnosticClonePipeline 收敛 + 反馈保真度

## 总则

test_node.py 7350 行,8 个 runner 抄同一骨架。**直接重构,不保持兼容性。** 收敛成共享 `DiagnosticClonePipeline`,同时修复反馈保真度(agent 未执行就失败的 preflight 语义)。

## 现状(全部代码验证)

### 8 runner 结构(test_node.py)

| Runner | 位置 | 参数 | 特点 |
|---|---|---|---|
| TestNodeRunner | 666 | config, source_state_root | 唯一带 source;copy+mark;dispatch |
| DiagnosticDescendantNodeRunner | 1925 | config, diagnostic_state_root | 主 dispatch 引擎(6 个 delegate 给它) |
| DiagnosticWorldPlanNodeRunner | 4890 | config, diagnostic_state_root | 派生 world 拓扑 → delegate |
| DiagnosticTaskRequirementNodeRunner | 5109 | config, diagnostic_state_root | 派生 plan design → delegate |
| DiagnosticTaskCurriculumJoinRunner | 5658 | config, diagnostic_state_root | 无 fresh copy,直接 delegate |
| DiagnosticPlanDerivedDesignNodeRunner | 6011 | config, diagnostic_state_root | 无 copy,直接 delegate |
| DiagnosticFinalNodeRunner | 6138 | config, diagnostic_state_root | 派生 final graph → delegate |
| DiagnosticSuccessorNodeRunner | 6875 | config, diagnostic_state_root | 从 committed Architecture 扩展(无 diagnostic_parent) |

共享骨架 6 步:copy+mark → build/derive graph → resolve_inputs → dispatch_one → settle terminal → report。

### 反馈保真度根因(已确认)

leaf_executor.py:718 的 ValidationError 分支对 agent 定义:
- `_ACTIVE_AGENT_PROPOSAL_OUTCOME` 为 None(agent 未执行)→ `_finish_exception(code="agent_leaf_untranslated_schema_error", agent=None)`(742-748)
- `_finish_exception` 门禁(1541-1548):`executor=="agent" and agent is None and not preflight_` → raise "Agent leaf failures must bind real invocation/profile provenance"
- `agent_leaf_untranslated_schema_error` 不满足 `preflight_` 前缀 → 门禁触发,原始 ValidationError 丢失

**Escape hatch 已存在**:`ProposalExecution.agent_preflight_failure`(work.py:742-747)允许 agent 全 None 字段当 `status != completed and error_code.startswith("preflight_")`。`_finish_exception` 也已有 `preflight_` 豁免(1544)。**缺陷 = agent 未执行的 schema 错误被分类成 `agent_leaf_untranslated_schema_error` 而非 `preflight_*`。**

### scope 污染

copy 是 whole-archive(`_copy_state_root` 1131-1162),heads 全部混入。scope 过滤在 read-time 各 runner 做(`read_scope_heads` 等)。

### failed-head 诊断

TestNodeRunner 通过 `archive_terminal_head_for_diagnostic`(885-889, clone marker 允许)先归档 failed head → 坐标 unheaded → scheduler 见 ready → 重跑。这是合法机制。

## 设计(2026-08-02 经对抗性 review 修订)

> review 否决了初版"6 步 god-class pipeline":TaskCurriculumJoin/PlanDerivedDesign 跳过 4 步(无 copy/dispatch/settle),derive_graph 把 4 种不同编译流程塌成一个带 6 深参的 hook,共享 report 因 8 个 runner 返回不同契约而错误。**修订:只提取真共享件,保留 runner 差异。**

### D1. 提取真共享件(module-level),不建 god-class

**共享(module-level 函数/辅助)**:
- `prepare_diagnostic_clone(source_state_root) -> Path`:封装 `_copy_state_root` + `mark_test_node_diagnostic_clone`(TestNode 等 6 runner 用)。
- dispatch 异常分类器:`_nonterminal_diagnostic_dispatch_error`(506)、`_settle_cancelled_diagnostic_dispatch`(395)——已 module-level,保留并复用。
- 跨 runner 加载器 hoist 到 module-level(真耦合):
  - `_load_plan_derived_join`(4 runner:5165/5698/6055/6206)
  - `_load_frozen_target`(TestNode+Successor:744/6938)
  - `_load_frozen_descendant`(Descendant+WorldPlan:3003/4964)
- head→report 的 "assert diagnostic-only marking" 检查(1038-1050)——唯一可共享的 report 部分。

**保留 per-runner(不强制统一)**:
- derive/compile/freeze(4 种不同流程:world/design/final/successor)——各自专属,不做策略 hook。
- settle-archive(reconcile)逻辑——Descendant 有 repair auth,Successor 无 archive,各异。
- result 契约——TestNodeResult/SuccessorResult/DescendantResult/包装类各不相同。

### D2. 反馈保真度(已验证 OK + 补强)

- `_finish_exception` 的 `preflight_` 豁免(1567-74)覆盖 `preflight_agent_input_schema` ✓。
- `ProposalExecution.agent_preflight_failure`(work.py:742-47,762)接受 status!=completed + preflight_ + 全 None ✓。
- **补强**:`_finish_validation_failure` 门禁(1150-55)依赖 `_ACTIVE_AGENT_PROPOSAL_OUTCOME` 判定"agent 是否真执行"。但 `record_agent_proposal_outcome` 只在 one_shot.py:497 一个 happy-path 调用。**需加测试**:agent 真执行后失败但没到 record 时机(通常走 LeafExecutionFailure→_finish_exception 仍受 guard),确认不会被误判为 preflight。

### D3. scope 过滤:留在 read-time(copy-time 是错误层)

- head 文件名 `sha256(scope_id\0coordinate_key)`(work_store.py:1346-47),`read_scope_heads` 已过滤(228-39)。
- **不改 copy**:copy-time 过滤会破坏 byte-for-byte 完整性(ancestor-closure 依赖 788-92),且一个无关 scope 的 corrupt head 会中止整个 copy。
- **保留 read-time 过滤 + 加 scope guard 测试**(确保 runner 不误读隔壁 scope 的 head)。

### D4. failed-head 诊断

保留 archive-then-rerun(TestNode 885-889,合法),改进 dispatch 失败时的错误报告(直出可操作原因)。

### D2. 反馈保真度修复(agent 未执行 → preflight_ 语义)

**leaf_executor.py:718 ValidationError 分支**:
- `_ACTIVE_AGENT_PROPOSAL_OUTCOME` 为 None(agent 未执行)时,分类为 `preflight_*` code(如 `preflight_agent_input_schema`),而非 `agent_leaf_untranslated_schema_error`
- 这样 `_finish_exception` 门禁的 `preflight_` 豁免生效,原始 ValidationError 保留(通过 category/terminal_details 传递可操作字段路径)

**`_finish_validation_failure` 门禁(1128)**:同类处理——agent 未执行(ACTIVE 为 None)时豁免 provenance 要求。

**`_finish_exception` 门禁(1541)**:确保 `preflight_*` 豁免覆盖"agent 未执行的输入 ValidationError"(已覆盖,验证即可)。

**关键不变量**:只有 `_ACTIVE_AGENT_PROPOSAL_OUTCOME is None`(agent 从未执行)才豁免;agent 真执行后的失败仍强制 provenance。**不破坏审计一致性。**

### D3. scope 污染:copy-time 过滤

`_copy_state_root` 增加可选 `scope_id` 参数,只拷贝目标 scope 的 heads(而非 whole-archive)。各 runner 在 copy 时传 target scope_id,消除 read-time 逐 runner 过滤的必要(保留 read-time 过滤作为防御)。

### D4. failed-head 诊断

保留 TestNodeRunner 的 archive-then-rerun 机制(已合法),但**改进报告**:dispatch 失败时(如 FailedHead 导致 dispatch_one 报错)直出可操作原因,而非笼统 `operation_failed (WorkRuntimeError)`。

## 边界/不变量

- 只有"agent 未执行"(ACTIVE None)豁免 provenance;agent 真执行后必须绑定证据。
- archive-then-rerun 机制保留(合法,clone marker 允许)。
- 不造假结果;每个诊断节点真实执行。
- baseline: `pytest tests/agent_world/test_test_node.py` = 2 fail/61 pass(2 个 fail 是独立 work_runtime.py:713,不在本 task)。

## 测试策略

- T1:DiagnosticClonePipeline 单测——copy/mark 过滤 scope、dispatch 分类、settle、report 各步。
- T2:反馈保真度——构造 agent 未执行的输入 ValidationError(如旧 EnvironmentDesign 超 cap),断言直出可操作字段路径,不报 provenance 误导。
- T3:preflight_ 语义——agent 未执行失败 → ProposalExecution status!=completed + error_code preflight_*,validator 放行。
- T4:scope 污染——copy 后 heads 只含 target scope,不混入。
- T5:8 runner 迁移后,`pytest tests/agent_world/test_test_node.py` 无回归(保持 2 fail/61 pass baseline)。
