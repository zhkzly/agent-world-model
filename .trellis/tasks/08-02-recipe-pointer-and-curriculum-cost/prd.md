# 重构:recipe 指针代码生成 + curriculum 成本约束

## 背景(两个独立根因,一次 E2E 暴露)

第二个 release run(`e2e-release-20260802T074026Z`,scope `generate-job:7c73dbfc`)在 verifier 和 integration 两处失败:

1. **verifier_intent_batch(batch-2)**:challenger 3 次栽同一个 `recipe_pointer_traverses_scalar` → `repair_denied_repair_local_exhausted`。batch-1/batch-3 用同一份代码/指南成功,只有 batch-2 触发。历史已第 3 次撞此错(`[[recipe-pointer-scalar-guidance-gap]]` 补指南后仍复发)。
2. **integration.runtime_integration**:`budget_exhausted(evaluation_episodes)`,真实需求 **72169**(复算 `integration_budget_requirements`),scope 预算 200 装不下。根因是 design 阶段 luna 把 `minimum_distinct_initial_states` / `minimum_distinct_tasks_per_type` 从默认 2 写到 **12025**(无上界)。

## 共同判断(用户授权,不考虑兼容性)

**"决定成本/正确性的可判定决策,不该交给模型自由发挥。"** 两个问题同根:模型被允许在不可判定的空间自由构造(指针、采样数),框架只能事后拒绝 → 反复 repair 烧模型费。应让确定性代码生成合法候选/约束,模型在闭集内选择。

## 方向 A:recipe 指针代码生成(合法候选闭集)

### 问题
`_solve_recipe_binding_guide`(compiler.py:3591)只给类型兼容的**浅** public_goal 指针;模型自由构造深指针时踩 `recipe_pointer_traverses_scalar`。

### 目标
对每个 tool 参数的每个可见 source,代码**穷举所有合法指针**(每段穿 object property/array item,停在 scalar 或结构化值,绝不越 scalar)+ literal 候选,challenger **只能从候选闭集选择**,不能自由发明。`recipe_pointer_traverses_scalar` 在正常流程不再触发,validator 变纯防御。

### 可见 source
public_goal / reset_observation / 先前 public tool results+observations;其 schema 全部在 challenger 上下文可见。

## 方向 B:curriculum 成本参数框架约束

### 问题
`minimum_distinct_initial_states`/`minimum_distinct_tasks_per_type`(默认 2,`Field(ge=2)` 无上界)可被设计模型写成 12025 → 下游 integration/release 评估成本爆炸。

### 目标
成本决定的采样参数由框架给出合理默认/上界(按 task 类型数 + 难度维数推导),设计模型只能在受限范围内微调或不得越界。integration/release 预算派生仍诚实反映设计,但设计本身不再能产生天文数字。

## 约束

- 不考虑兼容性,直接重构。
- 不造假成功;改动后必须用真实 E2E 或 test-node 验证。
- 凭证/敏感值不进 tracked 文件。
- validator 语义(recipe_pointer_traverses_scalar 的定义)是**对的,不改**;改的是"怎么让模型不触发它"。

## 验收

- AC-A1:challenger 上下文中的指针候选是**闭集**,且每个候选逐段解析合法(不越 scalar);模型不再能构造闭集外的指针。
- AC-A2:对引发 batch-2 失败的 task 形状,生成的闭集包含合法深指针,不再触发 `recipe_pointer_traverses_scalar`。
- AC-A3:validator 保留,但正常流程不再触发;有测试证明闭集外的指针被 validator 拒绝(防御性)。
- AC-B1:curriculum 采样参数有框架约束,设计模型不能写 12025 级天文数字;integration_budget_requirements 对任意合法设计 ≤ 合理上界。
- AC-B2:约束后 integration eval_episodes 需求显著下降(回到任务数×合理样本),scope 预算可装下。
- AC-C:全测试绿;ruff/mypy 净;用 test-node 或新 E2E 验证 verifier_intent_batch + integration 能过。
