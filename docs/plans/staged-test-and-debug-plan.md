# 已归档：旧分段测试与调试计划

> 本文的旧执行策略已于 2026-07-30 退休，不能作为当前调试、Prompt、Skill 或 E2E 的操作说明。

它描述了已经删除的“角色 developer instruction = Runtime Skill”路径、把所有语义节点
视为同一 Engineer Skill 的做法，以及过时的分片/重试策略。不要从它恢复兼容分支或把旧
bad-case 路由复制回当前实现。

现行权威入口：

- [产品与调用边界](../agent-world-environment-generation.zh.md)：尤其是 5.4 的 Direct LLM
  Prompt-only 与 Codex Agent Skill+Prompt+tool 区分；
- [项目调试规范](../../.trellis/spec/guides/agent-llm-node-debugging.md)；
- [项目执行 Agent 的调试 Skill](../../.agents/skills/agent-world-debugging/SKILL.md) 与
  [真实执行验证 Skill](../../.agents/skills/agent-world-real-execution-proof/SKILL.md)。

历史运行证据仍应从 durable state、`observe scene`、任务记录和当前代码读取；它们不是本
文中旧的固定节点策略。
