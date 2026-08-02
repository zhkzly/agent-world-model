# 重构:recipe 指针代码生成 + curriculum 成本约束

## Goal

两个根因重构:(A) verifier_intent_batch recipe_pointer_traverses_scalar 反复失败——让代码生成合法指针候选集,模型受限选择,validator 变纯防御;(B) integration budget_exhausted(eval_episodes=72169)——minimum_distinct_initial_states 等决定成本量级的参数由框架约束,模型不得自由写天文数字。不考虑兼容性,直接重构。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
