# Implement — recipe 指针闭集生成 + curriculum 成本约束(修订版 v2)

顺序:B(小、独立、低风险)先做,再做 A(较大)。**最终约束值(与用户对齐):4/4/16 + scope 1024。**

---

## Part B:curriculum 成本约束(已完成 ✓)

### B1. 共享常量(contracts/design.py)
- [x] `MAX_DISTINCT_CURRICULUM_SAMPLES = 16`、`MAX_ACTORS_PER_TASK = 4`、`MAX_DIFFICULTY_DIMENSIONS = 4`、`MAX_LEVELS_PER_DIM = 16`。

### B2. 两个 minimum 字段 `le`
- [x] `CurriculumRequirements`(contracts/design.py):两个字段 `Field(ge=2, le=16)`。
- [x] `CurriculumPlanDraft`(designer/models.py):同。
- [x] `CurriculumPlanSourceDraft`(designer/models.py):同(draft 时即拒)。

### B3. 并行漏洞:actors/dims/levels `max_length`
- [x] `TaskRequirement.allowed_actor_ids`(design.py):`max_length=4`。
- [x] `TaskRequirement.difficulty_dimensions`(design.py):`max_length=4`。
- [x] `DifficultyDimension.levels`(design.py):`max_length=16`。
- [x] `CurriculumTaskPlan` / `CurriculumTaskPlanSourceDraft`(designer/models.py):actors/dims 同加 max_length。
- [x] contracts/`__init__.py` re-export 4 常量;judge_budgeting import。

### B4. 预算引擎硬上限(judge_budgeting.py)
- [x] `task_materializer_call_counts`:clamp actors≤4、dims≤4、minimum_distinct≤16(双保险)。

### B5. world-derived 可达性检查(按 task 逐个)
- [ ] **暂缓**(schema le=16 + actors/dims max 已挡住离谱值;窄 world 晚期失败是边缘,后续补)。

### B6. prompt 范围指导
- [ ] **暂缓**(软指导;核心硬约束已生效)。

### B7. runtime 晚期失败路由
- [ ] **暂缓**(风险最高,不阻塞核心目标)。

### B 验证
- [x] B-V1. 107 测试过(test_controller_judge_budget / test_config_budgets / test_builder_task_materializer_contracts / test_designer_batched_transactions)。
- [x] B-V2. 手测:12025 被拒、16 通过、20 actors 被拒。
- [x] B-V3. 默认设计 40 episodes、宽松最坏(16/4/4/8)776 episodes,装进 scope 1024。

---

## Part A:recipe 指针候选闭集(已完成 ✓)

### A1. 枚举器
- [x] `_enumerate_legal_pointers(schema, visible_fields=None)`(compiler.py):递归 schema,object→properties 键(segment-0 可见性),array→`/0` 进 items,scalar→停。返回 `(pointer, schema)` 列表。段数≤32。

### A2. 重写 `_solve_recipe_binding_guide`
- [x] 枚举**所有 frozen tools**(非仅 required)。每参数从 public_goal 枚举闭集候选,`_schemas_compatible` 过滤,输出 `candidates: [{source, pointer, value_type}]`。

### A3. prompt 文案
- [x] "not exhaustive" → "closed enumeration; use a pointer only if in guide, or literal"。

### A 验证
- [x] A-V1. 47 测试过(test_verifier_assertions / test_executable_verifier_contracts,含更新后的契约断言)。
- [x] A-V2. 枚举器对嵌套 schema 生成深指针(`/config/depth`、`/items/0/x`),全部通过 `_schema_at_pointer`(零假阳性)。
- [x] A-V3. 闭集保证:枚举指针全部通过 validator;越 scalar 不生成。

---

## 门禁
- [ ] G1. `pytest tests/agent_world/ -q` 全量(后台运行中)。
- [ ] G2. ruff + mypy 净(改动文件;S608 是 pre-existing baseline 告警,非本次引入)。
- [ ] G3. test-node 或新 E2E 验证 verifier_intent_batch + integration 能过(不造假)。

## 约束
- 不 commit(除非用户 go)。
- validator `recipe_pointer_traverses_scalar` 语义不改。
- `integration_budget_requirements` 公式不改。
- 凭证不进 tracked。
