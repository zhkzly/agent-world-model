# 交接文档：world_rules 诊断保真迁移（codex 接手）

> 生成日期：2026-07-25。分支：`codex-agent-world-runtime-redesign`。
> 本文是把"永远打转"的根因、已修部分、以及**确切的下一步**交接给 codex。
> 服从 `staged-test-and-debug-plan.md` 的北极星与纪律；本文只加"这一段"的执行细节，不改产品合同。

## 0. 一句话现状

e2e 生成"永远在打转"的**一类直接根因已被确定性定位**：语义层 validator 抛**裸 `ValueError`** → 撞进单发结构化执行的 catch-all → 塌成 non-actionable `framework_diagnostic_incomplete` → Agent 拿不到可修 identity → 盲重采样 → 打转。上一批已修 7 个 evidence-claim 闭包 validator（已 commit）。**下一步：把 world_rules 编译链里剩余 26 处裸 ValueError 全部 typed 化**（用户已拍板"全迁"）。

## 1. 北极星红线（任何一步不得违反）

1. 生成的环境是确定性、不撒谎、可执行的 RL 训练环境；状态转移/reward/verifier 由生成的**代码**拥有，绝不由 LLM 文本/mock/模板/固定回放充当成功路径。
2. **不靠加 retry、扩 prompt、放松 Gate、人工补 Artifact 来"推进"。放松验证让它过 = DRIFT。** 确定性可判的约束就该留在代码里，不得为了让它通过而放松。
3. **Agent 提供的值（claim id、tool id、rule id、字段名等）绝不进诊断的 code 或 message。** 只有稳定 code + 字段 path 可跨安全边界。
4. 密钥/base URL/auth/sealed verifier/带凭证 transcript 绝不进任何 artifact/日志/trace/tracked 文件。模型凭证从 env 变量名 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 读（值在 bashrc）。
5. **push / git commit 仅在用户明确同意后。** 首选模型 grok-4.5，不可用才人工切 gpt-5.4-mini，绝不造假成功。

## 2. 反打转硬规则（元层，最重要）

- **禁止整条 e2e 盲跳调试。** 一次只在一个节点 + 其冻结契约 + 单点复现内工作。
- **每次修改前先分类**（code bug / 契约输入不全 / hole 欠定义 / 预算·基础设施 / 提示词欠定义），写进日志。分类错则后续全错。
- **修 bug 前先分清 owner**：确定性可判的约束留代码、只补 SKILL.md 告知；分类/路由/诊断错才改代码。
- **反复重跑 = 采样，采样不保证通过，也不是修复。** 必须构造/提取输入、单测那一个函数直到真的通过，再跑整段。
- 进展用 4 态 lattice 判（收缩/推进/回退/震荡）；连续两次 frontier 不缩或 A→B→A → 停手写根因、换打法，不得再补增量补丁。

## 2.5 调试宪法（DEBUGGING CONSTITUTION — 违反即停手）

> 这一节是针对**实际发生过的失败模式**写的硬约束。前任 agent 的通病：**好几个节点一起调、某个 bug 没修完就一味重跑采样、信息不够也不补反馈只顾再跑。** 以下每条都不得违反。

### C1. 一次只调一个 bug，修完再动下一个
- **禁止多节点/多 bug 并行调试。** scope 收窄到「一个坐标 / 一个 validator / 一处 raise」+ 其冻结契约 + 单点复现。
- 一个 bug **没有确定性验证通过（failing→passing 单测）之前**，不得开始下一个，更不得跑整段/整条 e2e。
- "看起来都相关所以一起改" = 反模式。相关也要一个一个来，每个都留下独立的 failing→passing 证据。

### C2. 重跑不是修复；重跑前必须先有"这次会不一样"的确定性理由
- **反复 `generate`/`test-node`/重采样 = 采样，采样不保证通过，也不修任何东西。**
- 每次真实 run **之前**必须能回答:"我改了什么代码、为什么这次结果会不同?" 答不上来 = 不许跑。
- 真实 run 只用于**两件事**:①最后确认已确定性修好的东西在真环收敛;②首次探明未知节点的真实失败形态。**不用于"再赌一次看看能不能过"。**
- 判据:若连续两次 run 的 frontier 没严格缩小,或出现 A→B→A 震荡 → **立即停手**,写根因诊断,换打法,不得再补增量补丁或再重跑。

### C3. 信息不够 = 反馈不足 = 去把反馈加上(而不是继续赌)
- **调试信息不足时,大概率是系统反馈的信息本身不足。正确动作是"把缺的诊断/telemetry/日志补进代码",不是硬猜或反复重跑碰运气。**
- 具体:如果一个失败只给你 generic code（如 `framework_diagnostic_incomplete`、`validation_failed`）、没有 path/stable-code/violated_condition —— 这**本身就是要修的 bug**（诊断保真缺陷,正是本文档整段在做的事）。先让失败"说清楚它是什么",再谈修它。
- 补反馈的合法手段:typed diagnostic（StructuredValidationError + 稳定 code + 精确 path）、frontier.jsonl 的 issue_samples、telemetry span 的 error_code/attributes、observability scene 的 lane/next_action。**加诊断永远优先于加重试。**
- **红线**:补反馈不得回显 Agent 值(见北极星红线 3);不得用加日志掩盖"没有稳定 code"的结构缺陷。

### C4. 先构造/提取输入,单测那一个函数——不要为了拿 input 跑整条管线
- 某个函数有 bug,就**直接构造它的输入单测它**(用 fixture 如 `portable_counter_contracts`,只毒化目标字段),直到真的通过,再往上跑。
- **不要**"为了拿到某节点的输入,把前面整条 Research→Design 都真跑一遍"——那是盲跳,慢且不可控。没有 input 就构造一个。
- 被拒提案通常不持久化;**不要过度猎取那份 provider payload**,构造等价输入即可。

### C5. 先分类,再定 owner,才动手
- 每次失败先查分类路由表(code bug / 契约输入不全 / hole 欠定义 / 预算·基础设施 / 提示词欠定义),写进日志。**分类错则后续全错。**
- 分清 owner:**确定性可判的约束就该留在代码里(北极星),只补 SKILL.md 告知模型;只有分类/路由/诊断本身错了才改代码。** 判定手段:`grep` SKILL.md 命中数——命中 0 说明模型从没被告知,owner 在提示词层,不是代码层。
- 绝不"为了让它过"放松/删除 validator 检查。

### C6. 用权威信号,不靠外观推断
- 判 lane 用 `ValidationReport.status`（`error` vs `failed`）和 evidence type（§3.3 三条 lane），**不靠 telemetry 外观或 pipeline_stage 粗猜**。
- 判失败真因读 telemetry.sqlite（spans.error_code/status/duration、events.payload、frontier/*.jsonl 的 issue_samples），**不靠"我记得""大概是"**。
- 说"修好了"之前必须有:①failing→passing 单测,或 ②真实 run 的 ValidationReport 证据。**不得把失败重命名为完成。**

### C7. 本 session 实际有效的调试流程（照此复刻，勿再走弯路）
1. 从 telemetry.sqlite 查目标节点 span：确认 `status/error_code/duration`——先分清是**真跑出来失败**还是**根本没跑到模型（挂起/transport）**。（本次:world_rules `failed/validation_failed/176.7s` = 真跑出来的语义崩塌,不是挂起。）
2. 读 `observability/.../frontier/<coord>.jsonl` 的 `issue_samples` 拿**真实 issue code + path + violated_condition**。（本次:`framework_diagnostic_incomplete @ ["semantic_output"]` → 指向 one_shot 兜底。）
3. 从兜底位置**逆推抛出点**:读绑定的 semantic_validator（`validate_world_rules` → `_compile_world_semantic_source`),`grep -n "raise ValueError"` 数清链里所有裸 raise 地雷。
4. **逐条分类**每个裸 raise(Agent 可控 vs 框架不变量),定 owner。
5. 构造毒化 draft **单测**目标 validator,确定性复现→修→复测通过。
6. 全部修完 + 元测试(无裸 raise 能撞兜底)通过,**最后**才 test-node 真跑确认收敛。
7. 每步写进最小报告;不跳步,不并行,不重跑赌运气。

## 3. 本 session 的核心发现（根因链，逐层核实）

### 3.1 崩塌机制

`agent_world/designer/one_shot.py` 的 `run_structured_agent` 单发路径异常处理顺序（300–395）：
- `StructuredValidationError`（321）→ `structured_output_semantic`，**保真**（issue 的 code/path/retryable/violated_condition/expected_category 全传上来）。
- `StructuredSemanticError`（331）→ 同上。
- `ValidationError`（353，pydantic）→ `structured_output_shape`。
- **`except ValueError:`（368，无 `as exc`）→ catch-all**：构造一个**纯静态**的 `SafeValidationIssue("framework_diagnostic_incomplete", ("semantic_output",), ..., retryable=False, violated_condition="the validator emitted no typed semantic issue", expected_category="a StructuredValidationError with a stable safe issue")`。

**关键点**：这个兜底**根本没用 `str(exc)`**——所以裸 ValueError 的 message（即使含 Agent 值）**不会跨界泄漏**；但它把一切裸 ValueError 一律塌成 non-actionable 的通用文案，Agent 无从修复。

### 3.2 actionable 判据（control/validation.py）

`actionable_for_agent = retryable and code not in _GENERIC_NON_ACTIONABLE_CODES`
其中 `_GENERIC_NON_ACTIONABLE_CODES` = {`semantic_contract_violation`, `schema_validation_error`, `schema_value_error`, `schema_value_error_root`, `validation_error`, `framework_diagnostic_incomplete`}。
→ 塌成 `framework_diagnostic_incomplete` 即 `actionable_for_agent=False, retryable=False`，反馈环断裂。

### 3.3 判别信号：三条 lane（观测层已贯通，见 staged plan T1.0-A/E）

| evidence type | report.status | 含义 | lane |
|---|---|---|---|
| `control.leaf_failure_evidence` | `error` | leaf 未产出提案（infra/transport） | `infrastructure_transport` |
| `control.leaf_validation_evidence` | `failed` | 提案跑出来了、**自身**语义被拒 | `proposal_semantics` |
| `control.parent_repair_route` 存在 | `failed` | leaf 明确把修复交上游 | `design_worldspec` |

**本段处理的是第二条 lane（proposal_semantics）**：提案真跑出来但语义被裸 ValueError 拒，诊断塌了。

## 4. 已交付（commit `3e9e424`，本 session）

`fix(designer): typed diagnostics for evidence-claim closure validators`

- 新增共享 helper `EnvironmentDesigner._evidence_claim_closure_issues(claim_ids, *, path, known_claims)`（service.py ~11006）：逐个未知 claim 产出 `SafeValidationIssue("world_model_evidence_claim_unknown", (*path, claim_index), "Use only an exact evidence claim id ...")`，**不回显 claim id**。
- 迁移 7 个 evidence-claim 闭包 validator（原本裸 `ValueError(f"... references unknown evidence claims: {sorted(unknown)}")`），改为收集 issues 后 `raise StructuredValidationError(ValidationDiagnostic(owner_component="design", validation_phase=<phase>, frontier_ordinal=40, issues=tuple(issues)))`。
- `control/validation.py` 的 `_DESIGNER_SEMANTIC_CONTRACTS` 新增 `"world_model_evidence_claim_unknown": (<violated_condition>, <expected_category>)`，自动派生进 `_SAFE_VIOLATED_CONDITIONS`/`_SAFE_EXPECTED_CATEGORIES`；已验证不在 `_GENERIC_NON_ACTIONABLE_CODES` → actionable。
- 回归测试 `test_world_model_reports_unknown_evidence_claim_as_actionable_field`（test_designer_world_composition.py）。
- 相关测试全绿（designer_world_composition 37 passed；feedback/rework/one_shot/control 89 passed）。

**这 7 个只是同类崩塌的第一批。**

## 5. 进行中（未提交）：world_rules 编译链剩余 26 处裸 ValueError

### 5.1 目标 validator（`_compile_world_semantic_source`，service.py:10877 调用链）

world_rules 节点绑定 `validate_world_rules`（service.py:1164）→ `_compile_world_semantic_source(compose_world_source(value), ...)`（:10877）。该链依次调 13 个 validator，其中 **7 个仍有裸 ValueError，合计 26 处**（其余已 typed）：

| validator | 行区间 | 裸VE | 类 |
|---|---|---|---|
| `_validate_world_state_shape_draft` | 7318-7364 | 3 | A |
| `_validate_initial_state_rules_draft` | 8011-8060 | 3 | A |
| `_validate_world_tool_plan_inventory_draft` | 8111-8151 | 5 | A |
| `_validate_tool_schema_draft` | 8173-8188 | 2 | B |
| `_validate_tool_surface_schemas_draft` | 8152-8172 | 1 | C |
| `_validate_world_tool_inventory_draft` | 8075-8110 | 3 | C |
| `_validate_world_skeleton` | 8957-9040 | 9 | B+C 混 |

> 行号以本文生成时为准；迁移前用 `grep -n "raise ValueError"` 重新核对（编辑会移动行号）。

### 5.2 分类（用户已拍板"A+B+C 全迁"，但分两种 typed）

- **A 类 = Agent 直接写的语义字段**（可修）→ **actionable typed**：
  - state_shape：`root_state_schema must be an object`（root schema 形）、actor reset visibility 唯一/引用未知字段。
  - initial_state_rules：family 必须 `initial_state`、id 必须 `rule:state:` 前缀、id 唯一。
  - tool_plan_inventory：超 `MAX_WORLD_TOOL_SURFACES`、tool_id 唯一、`tool_id == "<namespace>.<name>"`、namespace 在 WorldBoundary 内、claim 唯一。
- **B 类 = Agent IR 编译后仍反映其选择**（可修）→ **actionable typed**：
  - tool_schema：`draft.tool_id == plan.tool_id`、`schema_kind` 匹配。
  - skeleton：fidelity `bounded_approximation` 需 `known_divergence` / `faithful` 不得有 `known_divergence`；task_dimensions 必须稳定 Identifier。
- **C 类 = 框架 compose 后对已校验数据的防御性重查**（Agent 改不了，触发=框架 bug）→ **non-actionable typed**（`retryable=False`）：
  - tool_surface_schemas target（框架刚把 tool_id 设成 plan.tool_id，理论上不该触发）。
  - world_tool_inventory 的超界/唯一/namespace（源数据已在 plan_inventory 校验过）。
  - skeleton 里对 tool 超界/唯一/namespace/root schema/visibility 的重查（都是对上游已校验数据的复查）。

### 5.3 为什么 C 类也 typed（精炼，务必理解）

`one_shot.py:368` 兜底是纯静态文案、丢弃 `str(exc)`，所以 C 类保持裸 ValueError **语义上也"对"**（天然塌成 non-actionable，且不泄漏值）。但全 typed 化仍有净收益：**目前"validator 故意的框架不变量" vs "validator 忘了 typed 的疏漏"都塌成同一个 `framework_diagnostic_incomplete`，运维无法区分。** 给 C 类一个专门的 `retryable=False` 框架不变量 code（如 `world_compile_invariant_violated` 或按点更细），既保持 non-actionable（框架 bug 不该让 Agent 瞎修），又消除"疏漏/故意"歧义、消除 value 回显。

### 5.4 迁移模式（照抄已交付的 evidence-claim 写法）

每个 validator：收集 `list[SafeValidationIssue]`，循环末尾一次性
```python
raise StructuredValidationError(
    ValidationDiagnostic(
        owner_component="design",
        validation_phase="<per-validator-phase>",   # 如 world_state_shape_semantics
        frontier_ordinal=40,                          # A/B；C 可用同值但 code 标 non-actionable
        issues=tuple(issues),
    )
)
```
- **A/B 用 actionable code**（不进 `_GENERIC_NON_ACTIONABLE_CODES`，SafeValidationIssue 默认 retryable=True）。
- **C 用 `SafeValidationIssue(<code>, <path>, <static msg>, retryable=False, violated_condition=..., expected_category=...)`**。
- **路径要精确到字段**（如 `("initial_state_constraints", rule_index, "rule_id")`、`("tools", i, "namespace")`），不要聚合。
- **绝不回显 Agent 值**：现有 `f"...{sorted(invalid_ids)}"`、`f"actor {actor.actor}..."`、`f"...{tool_id}..."` 全部去掉，改为 code+path 定位 + 静态可修指引。
- 对已有 evidence-claim 迁移的 3 个 validator（state_shape/initial_state_rules/tool_plan_inventory），把新 issues **并入现有 issue 列表**再一起 raise，别开第二个 raise。

### 5.5 validation.py 注册（每个新 code 一条）

在 `control/validation.py` 的 `_DESIGNER_SEMANTIC_CONTRACTS` 加 `"<code>": (<violated_condition>, <expected_category>)`（会自动派生 `_SAFE_VIOLATED_CONDITIONS`/`_SAFE_EXPECTED_CATEGORIES`）。
- A/B 的 code **不要**放进 `_GENERIC_NON_ACTIONABLE_CODES`。
- C 的 code 靠 `retryable=False` 本身保证 non-actionable；是否也列入 generic 集由你按语义定（列入=永远 non-actionable，更保险）。

### 5.6 验收（确定性优先，最后才真实 run）

1. **确定性单测**（每个 code 一条 failing→passing）：用 `portable_counter_contracts` 类 fixture 构造合法 draft，**只毒化一个字段**，直接调对应 `_validate_*` 或 `_compile_world_semantic_source`，断言：
   - `diagnostic.validation_phase == <期望>`；
   - `issue.code == <期望稳定 code>` 且 path 精确；
   - A/B：`actionable_for_agent is True`；C：`actionable_for_agent is False`；
   - message/code **不含**被毒化的 Agent 值。
   - 保留"裸 ValueError 仍 non-actionable"的守护测试语义（别放松）。
2. **构造输入单测 `compile_world_rules` 整链**：确认迁移后**没有任何裸 ValueError 能撞到 one_shot 兜底**（可加一条元测试：反射扫描这 7 个 validator body 无 `raise ValueError`，或全链跑一个多字段毒化 draft 断言得到 typed 诊断而非 framework_diagnostic_incomplete）。
3. **最后**再用 test-node 对 world_rules 真跑一次确认收敛（见 §6）。**先修地雷再 test-node，否则只会复现崩塌。**

## 6. test-node 真跑（真实验收，最后一步）

**config 不跨 session，每条后台命令必须显式 export：**
```bash
cd /home/kelong/pycodes/agent-world-model
export AGENT_WORLD_CONFIG=.agent-world-live/doctor-grok45/config.toml   # gitignored，凭证仅 env 变量名
.venv/bin/python -m agent_world.cli test-node \
  generate-job:ba03ff3dce4e303593c64e2d \
  '{"artifact_slot":"world_rules","component":"design","stage":"world_rules","scope_id":"generate-job:ba03ff3dce4e303593c64e2d","schema_version":"v2","group_id":null,"shard_id":null}' \
  --source-state-root .agent-world-staged/t2-probe-2/state
```
- 行为：复制 scope 的 state_root 到 gitignored `.agent-world-live/test-node-<ts>/`，只 supersede world_rules 目标 head，`dispatch_one` 真跑模型；祖先 commit 原样当输入。
- 产物标 `diagnostic_only=true, releasable=false`，**绝不进 Registry**（守跨-scope-复用红线）。
- 隔离前提（重启失效）：`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` + `unshare --user --map-root-user echo userns-ok`。撞 `IsolationUnavailable` = 开关复位，不是 code bug。**绝不因隔离不可用就放松/跳过 Judge。**
- 收敛判据：world_rules 真跑出 `ValidationReport.status`，若仍 `failed`，看 issue code——应是 **typed actionable**（Agent 可修）而非 `framework_diagnostic_incomplete`。若 provider 挂起（见 §7 缺口 A）则是另一条 lane 的问题。

## 7. 关键事实修正 + 已知缺口（交接必读）

### 7.1 修正 memory 里的 T2 结论

`staged-test-and-debug-plan.md` §327「硬结论 1」称 world_rules "provider 挂起 27 分钟"。**本 session 从 telemetry 实测：t2-probe-2 的 world_rules span 是 `att=1 status=failed err=validation_failed dur=176.7s`——它真跑出来了、是语义崩塌（framework_diagnostic_incomplete @ semantic_output），不是挂起。** 挂起是**另一次**运行的现象。两者都真实存在，但**当前捕获的 t2-probe-2 失败是语义诊断崩塌**，正是本段要修的。

### 7.2 缺口 A（provider 挂起，未做）

单次 LLM 调用**无 per-turn 软超时**，provider 挂起会让反馈环干等到 45min 全局 timeout 才触发唯一 1 次 infra 重试。**修法**：给单次调用加远小于 45min 的 per-turn 软超时 + 指数退避；保留"单 backend、无自动模型 fallback"不变量。与本段（诊断保真）解耦，可后做。

### 7.3 缺口：孤儿 running-head 竞态（未做，记 owner）

硬 kill 正在跑的 generate 会留 `status=running + active_operation_ref=None` 的孤儿 head，`work_runtime.py:379-380` 的 `reconcile_abandoned_operation` 对 `active_operation_ref is None` 直接 return 不终态化 → 永久卡 running，同键 resume 报 `TelemetryError`。**规避**：污染的 scope 弃用，用新 request-id + 新 state_root 干净重跑。owner=代码（恢复逻辑边界遗漏），非打转核心，独立修。

### 7.4 一起看过、判定"不改"的 5 处兜底（别误迁）

`judge/compiler.py:1387`、`builder/service.py:1087`、`designer/service.py:2825/5791/6383` 都是 `_validation_diagnostic`/`except` 的**兜底捕获点**，不是抛出点。它们在上游抛裸 error 时塌成 `framework_diagnostic_incomplete`——**这是对的**（untyped error = 框架契约缺陷，绝不能烧 Agent 重试）。judge 复核结论：`VerifierIntent/VerifierDraft`（Agent 输出模型）无裸抛 field_validator，compiler 层裸 ValueError 走 message 映射表末尾 actionable catch-all（`intent_rule_binding_invalid`），**不塌**；judge/models.py 仅 2 个 validator 在框架编排 artifact 上。**judge/builder 这条线当前干净，不用动。** 真正的抛出点集中在 designer 的 world_rules 编译链（本段）。

## 8. 交接给 codex 的执行顺序

1. **重新核行号**：`grep -n "raise ValueError" agent_world/designer/service.py`，比对 §5.1 的 7 个 validator。
2. **A+B（14 处）迁 actionable typed**：state_shape/initial_state_rules/tool_plan_inventory/tool_schema/skeleton(fidelity+task_dimensions)。每处收集 issues、精确 path、去 value 回显、并入已有 raise。
3. **C（12 处）迁 non-actionable typed**：`retryable=False` 框架不变量 code；tool_surface_schemas/world_tool_inventory/skeleton 重查。
4. **validation.py 注册**所有新 code（A/B 不入 generic 集；C 靠 retryable=False）。
5. **确定性回归**：每 code 一条 failing→passing；加"这 7 个 validator body 无裸 raise"元测试；保留"裸 ValueError 仍 non-actionable"守护。
6. **跑测试全绿**（`.venv/bin/python -m pytest tests/agent_world/test_designer_world_composition.py tests/agent_world/test_feedback_contracts.py tests/agent_world/test_designer_structured_rework.py -q`）。
7. **test-node 真跑 world_rules**（§6 命令）确认收敛：typed actionable 而非 framework_diagnostic_incomplete。
8. **更新 memory**：修正"provider 挂起"为"t2-probe-2 是语义崩塌"；记录 world_rules 26 处迁移完成。
9. **commit**（用户已授权本方向；push 另需明确 go）。commit message co-author 尾注按仓库约定。

## 9. 环境与命令速查

- Python：`/home/kelong/pycodes/agent-world-model/.venv/bin/python`（无 `python`，用 `.venv/bin/python`）。
- doctor config（gitignored，凭证仅 env 变量名）：`.agent-world-live/doctor-grok45/config.toml`。
- 捕获 scope：`.agent-world-staged/t2-probe-2/state`（scope_id `generate-job:ba03ff3dce4e303593c64e2d`，7 committed + world_rules failed，祖先闭包完整可 test-node）。
- telemetry：`.agent-world-staged/t2-probe-2/state/telemetry/telemetry.sqlite`（spans/events/metrics）。
- 失败 frontier 证据：`.../observability/generate-job:.../frontier/ce5ce368....jsonl`（issue_samples 里 `framework_diagnostic_incomplete @ semantic_output`）。
- 模型：grok-4.5 首选（env `OPENAI_API_KEY`/`OPENAI_BASE_URL`，值在 bashrc）；不可用人工切 gpt-5.4-mini，不造假。

## 10. 绝对不要做

- 不要为了让 world_rules 过而放松/删掉任何 validator 检查（那些约束确定性可判、就该在代码里）。
- 不要把 Agent 值写进 code/message。
- 不要改那 5 处兜底捕获点（§7.4）。
- 不要动 judge/builder 线（当前干净）。
- 不要整条 e2e 盲跳；先修地雷、确定性验、最后才 test-node。
- 不要 git commit/push 未经明确同意（本方向已授权 commit；push 需再确认）。
- 不要因隔离开关复位就跳过 Judge。
