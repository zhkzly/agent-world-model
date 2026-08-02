# Design — recipe 指针闭集生成 + curriculum 成本约束(修订版)

> 修订说明:初版经两个 adversarial review(各审一个方向)发现 10 处缺陷,本版全部吸收。
> A 核心修正:枚举器从 **runtime 真实值**枚举而非 schema(否则闭集不成立)。
> B 核心修正:范围扩大,capp 不只要 cap 两个 minimum 字段,还要 cap actors/dims/levels 上界。

## 总则

两个方向独立,同根理念:**可判定的决策交给确定性代码,模型只在闭集内选择。** 不考虑兼容性。

---

## 方向 A:recipe 指针合法候选闭集(verifier challenger)

### 现状
- `_solve_recipe_binding_guide`(compiler.py:3591)只对 required_tool_ids × public_goal_schema 顶层 properties 生成单段浅指针;无深指针、无数组、无 reset_observation/previous_* source。
- prompt(compiler.py:2860)"guide is not exhaustive" 明示模型可自行发明指针 → 踩 `recipe_pointer_traverses_scalar`。
- validator `_schema_at_pointer`(compiler.py:3466-3530)是"合法"权威定义:object→properties 键,array→任意 canonical 索引进 items(**无边界检查**),scalar/union→`recipe_pointer_traverses_scalar`。

### Review 修正的认知(为什么不能 schema 枚举)
1. **schema 闭集 ≠ runtime 闭集**:`previous_tool_result` 的 schema 是 `output_schema`,但运行时值是 `EpisodeStepResult.tool_result`(可漂移:optional keys、additionalProperties、变长数组)。schema 枚举的候选在 runtime 可能 path-absent;schema 没列的关键 runtime 有。
2. **数组 `/0` 哨兵不可强制**:validator 接受任意 canonical 索引,`/0` 不能由 validator 强制 → 闭集外指针(如 `/5`)仍合法,闭集声明是假的。
3. **指南只枚举 required_tool_ids,但 validator 验证所有 step 的工具** → 非 required 工具参数无候选。

**结论:必须从 runtime 真实值枚举。** 各 source 的真实值在 challenger 上下文可见(public_goal / reset_observation / 先前 step 的 tool_result + observation),直接递归遍历真实 JSON,每个可达节点都是合法指针。

### 设计
**1. 新增枚举器 `_enumerate_legal_pointers(value, *, visible_fields=None, location=...)`**(compiler.py,挨着 `_solve_recipe_binding_guide`):
- 从 runtime 真实值递归:
  - object:对每个真实键(segment-0 受 `visible_fields` 过滤),append `/escaped(key)` 递归
  - array:对**每个真实索引**(0..len-1),append `/<i>` 递归 —— 用真实索引,不用哨兵
  - scalar/其他:停(emit 指向该叶的指针,不再下降)
- emit 每个可达节点(含中间 object/array 本身,供"取整个对象"用)
- 上限:段数 ≤32、指针 ≤4096 字符

**2. 每类 source 的真实值来源:**
- `public_goal`:`task.public_goal_schema` 无运行时值 → 用 schema 枚举(public_goal 是 Frozen 契约,无漂移),但数组用**真实值**若有;否则标注"需 model 确认长度"
- `reset_observation`:`world_spec.state.root_state_schema`(schema 枚举 + actor 可见性过滤)
- `previous_tool_result`:**先前 step 的运行时 `tool_result` 真实值**(递归枚举)——schema 仅作类型过滤
- `previous_observation`:**先前 step 的运行时 `observation` 真实值** + visible_fields 过滤

**3. 每个 tool 参数候选过滤**:用 `_schemas_compatible` 对目标 input_properties[name] 过滤;候选含结构化值指针(object/array 停留点)。

**4. 枚举工具集**:不只 required_tool_ids——枚举 **task 可能用到的所有 frozen tools**(validator 验证所有 step 工具)。非 required 工具参数也有候选。

**5. 指南重写**:`required_arguments[]` 每项列出按 source 分组的闭集候选:
```
{"argument": name, "target_type": label,
 "candidates": [{"source": "public_goal", "pointer": "/a/b", "value_type": "string"},
                {"source": "previous_tool_result", "previous_step_index": 0, "pointer": "/r", "value_type": "number"}, ...]}
```

**6. prompt 文案**:compiler.py:2860 → "The guide is a closed enumeration of every legal pointer derived from the actual values in this context; use a pointer only if it appears in the guide, or a schema-valid literal. If no candidate is listed for an argument, it must be a literal." 保留 2865-2868 结构规则。

**7. validator 保留**(compiler.py:3523)不改——纯防御。闭集外的指针仍被拒。

### AC-A 修订
- AC-A1:候选闭集 = 从 runtime 真实值枚举的合法指针集,含真实数组索引(非 `/0` 哨兵)。
- AC-A2:batch-2 失败形状,闭集含合法深指针,不再触发 `recipe_pointer_traverses_scalar`。
- AC-A3:validator 保留;闭集外指针(含越界数组索引、越 scalar 指针)被 validator 拒。
- AC-A4:非 required 工具参数也有候选。

---

## 方向 B:curriculum 成本参数框架约束(范围扩大)

### 现状
- `minimum_distinct_initial_states`/`minimum_distinct_tasks_per_type`:contracts/design.py:388-389,`Field(ge=2)` 无 le。
- `allowed_actor_ids`(design.py:110)、`difficulty_dimensions`(design.py:122)`:min_length=1` **无 max_length**;`DifficultyDimension.levels`(design.py:86):`min_length=2` 无 max。
- 预算公式 `task_materializer_call_counts`(judge_budgeting.py:38-53):`max(2, min_states, min_tasks, samples) × len(actors) + 2×len(dims) + tail`。
- 实测 12025 → 72169 episodes。review 确认:**绕道 actors/dims 同样可爆预算**(20 actors × 20 dims ≈ 6728 episodes/task × 8)。

### Review 修正的认知
1. `le=64` 对测试安全但需与 world-derived 检查一致(否则 world 可达 256 却拒 100)。
2. 可达性检查**按 task 逐个**,不是 Σ(求和过宽:窄 task 仍会在 runtime 失败)。
3. source-draft cap 在 draft 时生效,无 bypass(inner caps 是 defense-in-depth)。
4. 窄世界晚期失败仍存在,需路由到 design repair loop 给可操作消息。

### 设计(最终值:与用户对齐后 4/4/16 + scope 1024)
**1. 主(硬约束,三层 schema):共享常量 + `le`**
```python
MAX_DISTINCT_CURRICULUM_SAMPLES = 16   # 用户定:宽松组合(4/4/16)
MAX_ACTORS_PER_TASK = 4
MAX_DIFFICULTY_DIMENSIONS = 4
MAX_LEVELS_PER_DIM = 16
```
- `CurriculumRequirements`(contracts/design.py)、`CurriculumPlanDraft`(designer/models.py)、`CurriculumPlanSourceDraft`(models.py):两个 minimum 字段 `Field(ge=2, le=MAX_DISTINCT_CURRICULUM_SAMPLES)`。
- **为何 4/4/16**(基于真实评估成本分析):默认设计(2 floor, 1 actor, 1 dim, 8 tasks)只要 **40 episodes**,scope 预算 200 本就够;成本大头是 **actors×dims 乘积**。宽松组合 4×4×16 最坏 ~776 episodes,装进 scope 1024。模型保留多智能体真实空间,又不允许天文数字。

**2. 关闭并行漏洞(新):`max_length` 约束**
- `allowed_actor_ids`(design.py):`Field(min_length=1, max_length=MAX_ACTORS_PER_TASK)`(=4)
- 每 task `difficulty_dimensions`(design.py):`max_length=MAX_DIFFICULTY_DIMENSIONS`(=4)
- `DifficultyDimension.levels`(design.py):`Field(min_length=2, max_length=MAX_LEVELS_PER_DIM)`(=16)
- 同步:designer/models.py 的 `CurriculumTaskPlan` / `CurriculumTaskPlanSourceDraft` 的 allowed_actor_ids / difficulty_dimensions 同加 max_length。
- **硬上限**:`task_materializer_call_counts`(judge_budgeting.py)内部 clamp actors/dims/minimum_distinct——双保险(即使 model 绕过 schema,预算引擎不放大)。
- **scope 预算**:config evaluation_episodes 200 → **1024**(容纳最坏 4×4×16 ≈ 776 + release assurance headroom)。

**3. 次(world-derived 语义检查):`_validate_curriculum_plan`(service.py:10735)**
- 按 task 逐个检查:`minimum_distinct_initial_states > len(actors)·∏len(levels)`(该 task 的可达上界)→ raise StructuredValidationError(字段可寻址)。**逐个,不求和**。
- 让超界值得到可解释修复反馈,而非裸 ValidationError。

**4. 三(prompt 根因):范围指导**
- `_curriculum_plan_prompt`(final_design_leaves.py:1372-1391)+ 静态 prompt(service.py:12841):"keep minimum_distinct_* at default 2 unless a specific task needs more; per-task floors that directly multiply Judge evaluation-episode budget. Keep allowed_actor_ids / difficulty_dimensions / levels small — each actor multiplies per-task episodes, each dimension adds 2."

**5. 四(runtime 晚期失败路由)**:judge/service.py:2445-2449 的 `_CandidateTaskFailure`(materializer 产不出足够 distinct)路由回 design repair loop,带可操作消息("this task type can only produce N distinct initial configs given its actors×levels; lower minimum_distinct_initial_states below N").

### AC-B 修订
- AC-B1:两个 minimum 字段 schema 层 `le=64`(快速失败),world-derived 检查按 task 放行合理大值。
- AC-B2:`allowed_actor_ids`/`difficulty_dimensions`/`levels` 有 max_length;`task_materializer_call_counts` 有硬上限 → 模型绕道 actors/dims 不再爆预算。
- AC-B3:可达性检查按 task 逐个(窄 task 也能在设计期被拒)。
- AC-B4:integration_budget_requirements 对任意合法设计 episodes 显著下降(< 1000)。
- AC-B5:runtime `_CandidateTaskFailure` 路由回 repair loop 带可操作消息。

---

## 边界/不变量

- `recipe_pointer_traverses_scalar` validator 语义不改(正确防御)。
- `integration_budget_requirements`/`release_without_interactive_budget_requirements` 公式不改(诚实反映设计;设计被约束后不再天文)。
- `ReachabilityPolicy` 已是框架约束,不动。
- 现有测试 fixture 无 >64 字面量(review 确认),`le=64` 不误伤。

## 测试策略

- A:枚举器从 runtime 真实值递归(对象键/真实数组索引/scalar 叶全部 emit,段数/长度上限);闭集外(越界索引、越 scalar)被 validator 拒;非 required 工具参数有候选;batch-2 形状闭集含合法深指针。
- B:schema 层 le 拒 12025;actors/dims/levels max_length 生效;`task_materializer_call_counts` 硬上限;按 task 可达性检查;integration episodes 显著下降;runtime 晚期失败路由。
- C:全测试绿;ruff/mypy 净;test-node 或新 E2E 验证 verifier_intent_batch + integration 能过。
