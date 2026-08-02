# R4 重构 test_node.py:8 runner 收敛 + 反馈保真度 + 终局节点可达

## 背景

test_node.py ~7500 行,8 个 diagnostic runner 各抄一遍"copy/mark → build/derive → resolve → dispatch → settle → report"骨架。memory `[[test-node-cli-refactor-debt]]` 记录需抽共享 pipeline。2026-08-02 方向 A/B 验证 + 尝试续接 release_assurance 时,又暴露一批问题,全部纳入。

## 需求(直接重构,不保持兼容性)

### R4.1 收敛 8 runner 复制骨架(修订:提取真共享件,不建 god-class)
- [ ] 提取 module-level 共享件:copy+mark、dispatch 异常分类器、head→report 的 diagnostic-only 断言。
- [ ] hoist 跨 runner 加载器到 module-level:`_load_plan_derived_join`、`_load_frozen_target`、`_load_frozen_descendant`。
- [ ] 保留每 runner 差异(derive/compile/freeze、settle-archive、result 契约、descendant rework matrix)。
- [ ] 8 runner 迁移到共享件,消除复制骨架。

### R4.2 反馈保真度(2026-08-02 发现,已修 P1)
- [ ] agent 未执行就 ValidationError → 分类 `preflight_agent_input_schema`(已修),直出可操作字段路径。
- [ ] `_finish_validation_failure` 门禁豁免 agent 未执行(已修)。
- [ ] CLI operation_failed 保留 traceback 到 stderr(已修)。
- [ ] 补测试:agent 真执行后失败但没到 record 时机,不被误判为 preflight。

### R4.3 scope 污染
- [ ] copy 后 heads 混多 scope;runner 必须按 target scope_id 精确过滤(读时),不误报隔壁 scope。

### R4.4 failed-head 诊断
- [ ] dispatch_one 要求 ready,无法诊断 failed head;test-node 应给出可操作失败原因而非笼统 operation_failed。

### R4.5 manifest 歧义(2026-08-02 续接 release_assurance 发现)
- [ ] release_assurance 等终局坐标在多个 retained manifest 里,需 `--manifest-revision` 二选一,笨拙易错。应自动选"含最新 committed 前置"的 manifest。

### R4.6 终局节点可达(2026-08-02 发现,关键)
- [ ] 从已 committed 的 integration 续接 release_assurance(历史从未 dispatch 的节点),test-descendant-node 应能无缝派生并 dispatch,不用重跑上游。这是完整 E2E 的补充诊断路径。

### R4.7 跨 runner 加载器耦合
- [ ] `_load_plan_derived_join`(4 runner)、`_load_frozen_target`(2 runner)、`_load_frozen_descendant`(2 runner)是真耦合,hoist 到 module-level。

## 约束

- 不考虑兼容性,直接重构。
- 不造假;每个诊断节点真实执行。
- R4.2 不破坏"agent 真实执行后必须绑定 provenance"不变量。
- 凭证不进 tracked。
- baseline: `pytest tests/agent_world/test_test_node.py` = 2 fail/61 pass(2 个 fail 是独立 work_runtime.py:713)。

## 验收

- AC1:8 runner 无复制骨架;共享件 + 加载器 hoist 到 module-level;单测覆盖。
- AC2:agent 未执行 ValidationError 直出可操作字段路径(无 provenance 误导)。
- AC3:CLI operation_failed 有 traceback。
- AC4:failed head 给出可操作失败原因。
- AC5:manifest 二选一自动化为"选含最新 committed 前置的";不要求手工 --manifest-revision。
- AC6:从 committed integration 续接 release_assurance 的 test-descendant-node 路径可用(诊断验证)。
- AC7:test_node.py suite 无回归(2 fail/61 pass baseline)。
