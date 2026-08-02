# R4 DiagnosticClonePipeline convergence(收敛 test_node 8 个 runner + 修复反馈保真度)

## 背景

test_node.py 7350 行,8 个 runner 各抄一遍"复制/标记状态 → 构建图 → 解析输入 → dispatch 单节点 → settle → 报告"骨架。memory `[[test-node-cli-refactor-debt]]` 记录需抽共享 `DiagnosticClonePipeline`。2026-08-02 验证方向 A/B 时又暴露 test-node 三个反馈保真度缺陷,一并纳入。

## 需求(直接重构,不保持兼容性)

### R4.1 DiagnosticClonePipeline 收敛
- [ ] 抽共享 `DiagnosticClonePipeline`(copy/mark/build/resolve/dispatch/settle/report),8 runner 迁移上去。
- [ ] 保留每个 runner 的差异点(目标坐标类型、batch 选择、descendant rework matrix)作为 pipeline 的策略参数,而非复制骨架。
- [ ] Descendant rework matrix 保持独立作被委托引擎。

### R4.2 反馈保真度(2026-08-02 发现)
- [ ] agent 未执行就因**框架输入 ValidationError**(如旧 EnvironmentDesign 被新 curriculum cap 拒)失败时,test-node 应直出可操作 ValidationError(字段路径),而非被 provenance 门禁包装成误导性 "Agent leaf failures must bind real invocation/profile provenance"。
- [ ] 利用 `ProposalExecution.agent_preflight_failure`(work.py:749-753)作为"agent 未执行就失败"的正确语义(executor=agent + status!=completed + error_code preflight_)。
- [ ] CLI `operation_failed` 保留完整 traceback 到 stderr(本地调试),JSON 保持简洁(不暴露 backend/auth 文本)。

### R4.3 scope 污染(head 混入多 scope)
- [ ] test-node 复制 source state root 时,work-control/heads 混入多个历史 scope 的 head;runner 必须按 target scope_id 精确过滤,不误报隔壁 scope 结果。

### R4.4 failed-head 诊断
- [ ] dispatch_one 要求 ready/repair_ready/stale(work_scheduler.py:464),无法诊断已 failed 的 head。test-node 应能对 failed head 给出可操作失败原因(而非笼统 operation_failed)。

## 约束

- 不考虑兼容性,直接重构。
- 不造假成功;重构后用真实 test-node 或 E2E 验证。
- R4.2 不能破坏"agent 真实执行后必须绑定 provenance"的安全不变量——只豁免"agent 未执行"场景。
- 凭证/敏感值不进 tracked。
- baseline: `pytest tests/agent_world/test_test_node.py` 当前 2 fail/61 pass(2 个 fail 是独立 work_runtime.py:713 workspace-authority,不在本 task)。

## 验收

- AC1:8 runner 收敛到 DiagnosticClonePipeline,无复制骨架;单测覆盖 pipeline 各步骤。
- AC2:test-node 对 agent 未执行的输入 ValidationError 直出可操作字段路径,不报 provenance 误导错误。
- AC3:CLI operation_failed 有 traceback 到 stderr。
- AC4:test-node 对 failed head 给出可操作失败原因(或明确诊断语义)。
- AC5:test_node.py 测试 suite 无回归(保持 2 fail/61 pass baseline)。
