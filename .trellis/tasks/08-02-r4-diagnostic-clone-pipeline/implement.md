# Implement — test_node.py 完整重构(两个 review 修订后)

> 顺序:Part 1 共享件(基础)→ Part 2 manifest 消歧 → Part 3 反向索引 → Part 4 observability(解耦)→ Part 5 测试补强。

---

## Part 1:共享件提取(基础)

### P1.1 `prepare_diagnostic_clone`
- [ ] module-level `prepare_diagnostic_clone(source_root, *, diagnostic_parent, marker_error_code, marker_message, has_guard)`。
- [ ] 6 处 copy+mark 迁移;error_code/message/guard 参数化保留差异。
- [ ] TestNodeRunner 的 `_copy_state_root`/`_new_diagnostic_root` 被其替代(或内部调用)。

### P1.2 `resolve_diagnostic_root`
- [ ] module-level,error_code 参数化;7 处(2853/5059/5272/5717/6081/6765/7232)迁移。

### P1.3 dispatch 异常处理 helper
- [ ] 提取 dispatch+classification(不吞 executor 构造/span finish,传 span-finish callable);3 个 dispatching runner 迁移,error_code 前缀参数化。

### P1.4 加载器 hoist
- [ ] `_load_plan_derived_join`、`_load_frozen_target`、`_load_frozen_descendant`、`_load_committed_world_plan` hoist module-level。

### P1-V
- [ ] `pytest tests/agent_world/test_test_node.py`(2 fail/61 pass 无回归)。

---

## Part 2:manifest 消歧(D3,fail-closed 修订)

### P2.1
- [ ] `_load_frozen_descendant` **保持硬失败**(3290-3302)。
- [ ] 仅当**严格决定性**才自动选:一个候选 committed-predecessor 是严格超集 + target terminals reachable。
- [ ] 平局保留硬失败 + `--manifest-revision`;**不 fall back 最小图**。

### P2-V
- [ ] 单测:严格超集才选;平局硬失败。

---

## Part 3:反向索引(D5,legacy 处理)

### P3.1
- [ ] `DirectJobStore.list_request_ids_for_scope(scope_id)`(扫描 `sha256(request_id).json` heads)。
- [ ] legacy head(scope_id None):deref job_ref 取 job_id,或显式排除 + fail-closed。
- [ ] 不建索引文件;仅 DirectJobStore 层。

### P3-V
- [ ] 单测:scope→request 正确;legacy head 显式处理。

---

## Part 4:observability_hint(解耦,独立改造)

### P4.1
- [ ] **从 test_node 重构解耦**,独立小改造。
- [ ] 保持 bounded no-import(读 head 记录 + scene.md,不 import projector)。
- [ ] 状态门:head mtime 变化才 emit;cap 大小(N scope,一行/个)。
- [ ] failed 优先,running 次之。
- [ ] .claude + .codex 双副本同步。

### P4-V
- [ ] 单测:非 idle 才 emit;failed 优先。

---

## Part 5:测试补强(D2/D8)

### P5.1
- [ ] 测试:agent 真执行后失败但没到 record 时机,不被误判 preflight。
- [ ] 测试:descendant 非吞 WorkRuntimeError(terminal 时 re-raise)。

### P5-V
- [ ] `pytest tests/agent_world/test_scheduler_leaf_executor.py`(baseline 7 fail 无新增)。

---

## 门禁
- [ ] G1. `pytest tests/agent_world/test_test_node.py` = 2 fail/61 pass(无回归)。
- [ ] G2. ruff + mypy 净。
- [ ] G3. 真实 test-descendant-node 从 committed integration 续接 release_assurance(不造假)。

## 约束
- 完整重构,不分段。
- 边界不变量(design §顶部 5 条)保持。
- **read-time scope 过滤**(copy 保持全量,不 copy 过滤)。
- schema_missing(properties[22])out of scope,follow-up。
- 凭证不进 tracked。
