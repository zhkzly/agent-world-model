# Implement — DiagnosticClonePipeline 收敛 + 反馈保真度

顺序:D2(反馈保真度,小独立)先做 → D4(failed-head 报告) → D1(pipeline 收敛,大) → D3(scope 过滤)。

---

## Part 1:反馈保真度(先做,独立、小)

### P1.1 leaf_executor agent 未执行 → preflight_ 语义
- [ ] leaf_executor.py:718 ValidationError 分支:`_ACTIVE_AGENT_PROPOSAL_OUTCOME.get()` 为 None 时,分类为 `preflight_*` code(如 `preflight_agent_input_schema`),而非 `agent_leaf_untranslated_schema_error`;经 `_finish_exception` 传可操作 category(含 ValidationError 字段路径)。
- [ ] `_finish_validation_failure` 门禁(1128):`_ACTIVE_AGENT_PROPOSAL_OUTCOME.get() is None` 时豁免 provenance 要求(agent 未执行)。
- [ ] 验证 `_finish_exception` 的 `preflight_` 豁免(1544)覆盖此场景。

### P1.2 CLI operation_failed 保留 traceback
- [ ] cli.py:857 except Exception:`traceback.print_exc()` 到 stderr(本地调试),JSON 保持简洁。

### P1.3 验证
- [ ] P1-V1. `pytest tests/agent_world/test_scheduler_leaf_executor.py`(baseline 现有失败是独立)。
- [ ] P1-V2. 构造 agent 未执行的输入 ValidationError,断言直出可操作字段路径,不报 provenance 误导。

---

## Part 2:failed-head 诊断报告

### P2.1
- [ ] TestNodeRunner dispatch 失败时(如 FailedHead 不可 dispatch),直出可操作原因(带 head 状态 + 失败 code),而非笼统 `operation_failed`。
- [ ] `_nonterminal_diagnostic_dispatch_error`(506-543)改进:保留根因 traceback + 分类。

### P2.2 验证
- [ ] P2-V1. 对 failed head 跑 test-node,断言可操作错误信息。

---

## Part 3:提取真共享件 + 收敛(2026-08-02 review 修订,不建 god-class)

### P3.1 module-level 共享件
- [ ] `prepare_diagnostic_clone(source_state_root) -> Path`:封装 `_copy_state_root` + `mark_test_node_diagnostic_clone`。
- [ ] hoist 跨 runner 加载器到 module-level:`_load_plan_derived_join`、`_load_frozen_target`、`_load_frozen_descendant`。
- [ ] 复用已 module-level 的 `_nonterminal_diagnostic_dispatch_error`、`_settle_cancelled_diagnostic_dispatch`。
- [ ] head→report 的 "assert diagnostic-only marking" 检查抽成共享辅助。

### P3.2 迁移 runner(用共享件,保留各自 derive/settle/report)
- [ ] TestNodeRunner:用 `prepare_diagnostic_clone` + 共享加载器,保留 source/result 差异。
- [ ] DiagnosticDescendantNodeRunner:用共享加载器 + dispatch 分类,保留 repair auth + rework matrix。
- [ ] DiagnosticWorldPlanNodeRunner / TaskRequirement / TaskCurriculumJoin / PlanDerivedDesign:用共享加载器,保留各自 derive。
- [ ] DiagnosticFinalNodeRunner:用共享加载器,保留 readiness gate + final graph derive。
- [ ] DiagnosticSuccessorNodeRunner:用共享加载器,保留 successor derive + result 契约。

### P3.3 验证
- [ ] P3-V1. `pytest tests/agent_world/test_test_node.py`(baseline 2 fail/61 pass,无回归)。
- [ ] P3-V2. ruff + mypy 净。

---

## Part 4:scope 污染过滤

### P4.1
- [ ] `_copy_state_root` 加 `scope_id` 参数,只拷贝目标 scope 的 heads(而非 whole-archive)。
- [ ] 各 runner copy 时传 target scope_id;保留 read-time 过滤作防御。

### P4.2 验证
- [ ] P4-V1. copy 后 heads 只含 target scope(测试断言)。
- [ ] P4-V2. test_node.py suite 无回归。

---

## 门禁
- [ ] G1. `pytest tests/agent_world/test_test_node.py` = 2 fail/61 pass(无回归)。
- [ ] G2. `pytest tests/agent_world/test_scheduler_leaf_executor.py`(Part 1 相关,无新回归)。
- [ ] G3. ruff + mypy 净(改动文件)。
- [ ] G4. 若可行,用新 E2E scope 跑 test-node 验证 verifier_intent_batch + integration 能过。

## 约束
- 不 commit(除非用户 go)。
- 只有"agent 未执行"(ACTIVE None)豁免 provenance;agent 真执行后必须绑定证据。
- archive-then-rerun 机制保留(合法)。
- 不造假;每个诊断节点真实执行。
- 凭证不进 tracked。
