# Design — test_node.py 完整重构(基于两个精确研究 agent)

> 基于 test_node 差异矩阵 + 组件关系两个研究,2026-08-02 修订为最终版。

## 边界不变量(重构必须保持)

1. test_node **从不直接调** `checkpoint_proposal`/`schedule_operation`/`resume_uncommenced_running`——靠 `WorkScheduler.dispatch_one` + 真实 leaf。
2. 诊断 copy 只做 2 个 store 变更:`mark_test_node_diagnostic_clone` + `archive_terminal_head_for_diagnostic`(都需 marker)。
3. `preflight_` code 前缀是"agent 未执行"的承重逃生口(leaf gate leaf_executor.py:1570 + work.py:742-747)。
4. final-node 天然多 manifest;`required_manifest_ref`/`--manifest-revision` 是消歧机制。
5. 组件关系:test_node 复用生产对象(build_application/scheduler/runtime/leaf_executor),只在 copy 里跑一次真实 leaf。

---

## D1. 提取真共享件(基于差异矩阵,不建 god-class)

### D1.1 `prepare_diagnostic_clone`(copy+mark,对抗 review 修订:非"全部相同")
TestNodeRunner 722-730 / Descendant 2081-2091 / WorldPlan 4935-4945 / TaskRequirement 5147-5157 / Final 6191-6201 / Successor 6919-6929。**对抗 review 指出:非 byte-identical**——error_code 不同(test_node.py:728/2089/4943/5155/6199/6927)、message 不同、TestNodeRunner 无 `except TestNodeError: raise` guard(其他有)、naming 是 prepared_root vs diagnostic_root。
提取 `prepare_diagnostic_clone(source_root, *, diagnostic_parent, marker_error_code, marker_message)`:
- 参数化 marker_error_code + message(保留每 runner CLI 粒度)。
- 参数化 `has_guard`(TestNodeRunner 无 guard,其他有)。
- `diagnostic_parent` 必须保留(design 初版签名 vs implement P3.1 的 source_state_root 不一致,对抗 review 指出)。
- 封装 `_assert_no_symlinks` → copytree → mark_test_node_diagnostic_clone。

### D1.2 `resolve_diagnostic_root`(7 次近似重复)
Descendant 2853 / WorldPlan 5059 / TaskRequirement 5272 / TaskCurriculumJoin 5717 / PlanDerivedDesign 6081 / Final 6765 / Successor 7232——只差 error-code 字符串。提取 module-level,error_code 参数化。

### D1.3 dispatch 异常处理(3 个 dispatching runner 共享)
TestNode 946-1009 / Descendant 2556-2612 / Successor 7105-7161 byte-identical。`_settle_cancelled_diagnostic_dispatch`(395)+ `_nonterminal_diagnostic_dispatch_error`(506)已 module-level;提取成一个 `dispatch_diagnostic_target(scheduler, coordinate, executor, ..., error_code)` helper 封装 dispatch + 异常分类。

### D1.4 跨 runner 加载器 hoist(真耦合)
- `_load_plan_derived_join`(4 runner:5698/5165/6055/6206)→ module-level
- `_load_frozen_target`(2 runner:744/6938)→ module-level
- `_load_frozen_descendant`(3 runner:2105/2150/2186/4964)→ module-level
- `_load_committed_world_plan`(1 runner)→ module-level

## D2. 反馈保真度(已修 P1,确认边界)

- `preflight_agent_input_schema`(leaf_executor.py:764)是"agent 未执行就输入 ValidationError"的正确分类,preflight_ 逃生口有效(leaf 1570 + work 742-747)。
- `_finish_validation_failure` 门禁(1150-1157)豁免 agent 未执行(ACTIVE None)。
- CLI operation_failed 保留 traceback(cli.py,已修)。
- 补测试:agent 真执行后失败但没到 record 时机,不被误判 preflight(one_shot.py:497 唯一 happy-path 调用点)。

## D3. manifest 消歧(对抗 review 修订:保持 fail-closed,不自动选"newest")

两个 review 冲突:架构说"newest committed-predecessor"合理,对抗指出**无时间轴**(manifest 无 timestamp,revision_id 是 content hash),mid-run freeze 可产生最深链但不完整拓扑,自动选会静默选错。**采纳对抗 review(fail-closed 更安全)**:
- **保持 `_load_frozen_descendant` 的硬失败**(3290-3302),不自动选。
- 只当**严格决定性**才自动选:一个候选的 committed-predecessor 集是其他候选的**严格超集** 且 target 的 required_terminal_coordinates 全部 reachable。
- 平局保留硬失败 + `--manifest-revision` 显式覆盖。
- **不 fall back 最小图**(最小图最不完整,对抗 review 正确)。

## D4. 终局节点可达(R4.6)

从已 committed integration 续接 release_assurance:test-descendant-node 已能 dispatch(manifest 选择后)。D3 自动选择让它无需手工 --manifest-revision。确认完整链:integration committed → test-descendant-node release_assurance → release/registry。

## D5. 反向索引(R4.7,对抗 review 修订:处理 legacy + 明确扫描)

heads 是 `sha256(request_id).json`(direct_store.py:285-290),扫描可行(N≈scope 数小)。**索引文件是错误选项**(第二真相源,需在单写者 CAS 路径维护,direct_store.py:147-176,漂移风险)。
- `DirectJobStore.list_request_ids_for_scope(scope_id)` :扫描 heads 按 scope_id 过滤。
- **legacy head 处理**:scope_id None 的 head 必须显式处理——要么 deref job_ref 取 job_id,要么显式排除 + fail-closed。不能静默漏(对抗 review 正确)。
- 仅 DirectJobStore(direct 层);work-control 已 scope-partitioned(work_store.py:1347),不做冗余扫描。

## D6. observability_hint 常驻(解耦 + 状态门,对抗 review 修订)

对抗 review:always-inject 违反 hook 的 silent-no-op 契约(observability_hint.py:30-43),扩大读面(需 projector = import 组合根,违反 bounded no-import 设计),每 prompt 噪音。**采纳**:
- **D6 从 test_node 重构解耦**——它是 hook 域独立改造,且 .claude/.codex 双副本已漂移(需同步)。
- 保持 bounded no-import(只读 head 记录 + scene.md,不 import projector)。
- **状态门**:只在非 idle 状态存在时 emit(head mtime 变化 / 有 running/failed/stuck);cap 大小(N 个 scope,每个一行)。
- 保留 failed 优先,running 次之。
- 双副本(.claude + .codex)同步修改。

## D7. 重试退避确认(遗留项,已解决,文档确认)

config.py:102 `infrastructure_retry_backoff_seconds` 默认 5.0;work_scheduler.py:655-664 `_await_retry_backoff` 真 asyncio.sleep。**已实现**。可选:5s 对 grok 5.7min 窗口仍短,可调 config,但非代码缺陷。D7 = 文档确认,无代码。

## D8. 被吞的 WorkRuntimeError(遗留项,memory 不准确,已正确)

研究确认:`_nonterminal_diagnostic_dispatch_error` 在 head terminal 时返回 None → 原始 WorkRuntimeError re-raise(不吞);非 terminal 时转 TestNodeError 且链 __cause__。**行为已正确**。补一个 descendant 测试断言(非吞)。D8 = 补测试,无行为改动。

## D0. copy-time vs read-time scope 过滤(对抗 review 指出矛盾)

design D1.1(copy 全量)+ prd R4.3(读时过滤)vs implement P4.1(copy 时过滤)矛盾。**裁定:read-time 过滤**(对抗 review + 架构 review 一致):
- copy 保持全量(byte-for-byte,ancestor-closure 依赖)。
- scope 过滤在 read-time(`read_scope_heads` 已做)。
- copy 时过滤会破坏 byte-for-byte 完整性 + 一个无关 scope 的 corrupt head 中止整个 copy。
- implement.md P4.1 的 copy 过滤项**删除**。

---

## 测试策略

- T1:`prepare_diagnostic_clone`/`resolve_diagnostic_root` 单测(copy 排除正确、mark 生效)。
- T2:dispatch helper 单测(异常分类,terminal 不吞)。
- T3:manifest 自动选择单测(newest committed-predecessor 排序)。
- T4:反向索引单测(scope→request 查询)。
- T5:observability_hint 常驻单测(running 也返回摘要)。
- T6:agent 真执行后失败不被误判 preflight。
- T7:descendant 非吞 WorkRuntimeError 测试。
- T8:8 runner 迁移后 `pytest tests/agent_world/test_test_node.py` 无回归(2 fail/61 pass baseline)。

## 约束

- 不考虑兼容性,直接重构。
- 边界不变量(§顶部 5 条)必须保持。
- 不造假;每个诊断节点真实执行。
- 凭证不进 tracked。
