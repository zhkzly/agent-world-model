# Agent World 相关论文列表

> 边界说明：本文是研究背景，不是当前仓库的实现计划。当前任务源以 `docs/agent-world-environment-generation.zh.md` 为准；论文时间线只帮助判断设计取舍，不能直接变成实现路线。

排序规则：按 arXiv 首次发布时间排列。核心层指直接讨论 agent world、环境合成、任务合成、可执行环境或环境奖励的论文；扩展层指 harness、loop、自治研究等支撑 agent world 的系统论文。

## 核心发展顺序

| 时间 | 论文 | 层级 | 作用 |
| --- | --- | --- | --- |
| 2025-06-13 | [Agent-RLVR: Training Software Engineering Agents via Guidance and Environment Rewards](https://arxiv.org/abs/2506.11425) | 核心前置 | 说明复杂 agent 环境中 RLVR 奖励稀疏，需要 guidance 和环境反馈参与训练闭环。 |
| 2025-12-01 | [CuES: A Curiosity-driven and Environment-grounded Synthesis Framework for Agentic RL](https://arxiv.org/abs/2512.01311) | 核心 | 解决新环境没有预定义任务的问题，从环境结构和 affordance 中自动生成任务。 |
| 2025-12-28 | [AutoForge: Automated Environment Synthesis for Agentic Reinforcement Learning](https://arxiv.org/abs/2512.22857) | 核心 | 提出自动化环境合成和环境级 RL，强调高难度、易验证任务。 |
| 2026-02-10 | [Agent World Model: Infinity Synthetic Environments for Agentic Reinforcement Learning](https://arxiv.org/abs/2602.10090) | 核心 | 用场景、任务、数据库、工具接口、环境代码和 verifier 生成 1,000 个可执行 SQL-backed 环境。 |
| 2026-03-06 | [ResearchEnvBench: Benchmarking Agents on Environment Synthesis for Research Code Execution](https://arxiv.org/abs/2603.06739) | 核心评测 | 把“能否合成可运行研究环境”作为 benchmark，关注依赖、版本和运行时配置。 |
| 2026-04-20 | [Agent-World: Scaling Real-World Environment Synthesis for Evolving General Agent Intelligence](https://arxiv.org/abs/2604.18292) | 核心 | 从真实主题发现环境和任务，并把多环境 RL、动态任务生成和失败诊断组成 self-evolving arena。 |
| 2026-05-18 | [EnvFactory: Scaling Tool-Use Agents via Executable Environments Synthesis and Robust RL](https://arxiv.org/abs/2605.18703) | 核心 | 从真实资源探索和验证 stateful executable environments，并生成更自然的多轮轨迹。 |

## 扩展系统顺序

| 时间 | 论文 | 层级 | 作用 |
| --- | --- | --- | --- |
| 2026-04-13 | [From Agent Loops to Structured Graphs: A Scheduler-Theoretic Framework for LLM Agent Execution](https://arxiv.org/abs/2604.11378) | Loop | 把 agent loop 解释为调度问题，主张用显式图结构提升可控性和可验证性。 |
| 2026-04-14 | [Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems](https://arxiv.org/abs/2604.14228) | Loop/Harness | 通过 Claude Code 架构说明核心 loop 简单，但权限、上下文、MCP、skills、hooks 和 subagents 决定系统能力。 |
| 2026-04-28 | [Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses](https://arxiv.org/abs/2604.25850) | Harness | 把 harness 改造变成可观测、可回放、可验证的自动进化闭环。 |
| 2026-05-03 | [NORA: A Harness-Engineered Autonomous Research Agent for End-to-End Spatial Data Science](https://arxiv.org/abs/2605.02092) | Harness/Research | 展示面向具体科研领域的 skills、subagents、MCP servers、safety gates 和 state persistence。 |
| 2026-05-07 | [From Agent Loops to Deterministic Graphs: Execution Lineage for Reproducible AI-Native Work](https://arxiv.org/abs/2605.06365) | Loop | 用 DAG 和 execution lineage 解决 loop 式工作流的可复现、可维护和局部更新问题。 |
| 2026-05-12 | [Harness Engineering as Categorical Architecture](https://arxiv.org/abs/2605.12239) | Harness | 尝试给 harness engineering 形式化基础，关注组合、编译和结构性保证。 |
| 2026-05-13 | [AI Harness Engineering: A Runtime Substrate for Foundation-Model Software Agents](https://arxiv.org/abs/2605.13357) | Harness | 把 agent 能力重定义为 model-harness-environment system 的产物，提出 harness 责任清单。 |
| 2026-06-08 | [What makes a harness a harness: necessary and sufficient conditions for an agent harness](https://arxiv.org/abs/2606.10106) | Harness 概念 | 给 agent harness 划边界，区分 harness、framework、SDK、IDE plugin、eval harness 和 orchestrator。 |
| 2026-06-10 | [Toward Generalist Autonomous Research via Hypothesis-Tree Refinement](https://arxiv.org/abs/2606.11926) | Research/Loop | 用 Hypothesis Tree Refinement 管理长期假设、实验、证据和经验，是 agent world 走向长期自治研究的代表。 |

## 最短阅读路径

如果只看 agent world 主线，读这 7 篇即可：

1. Agent-RLVR
2. CuES
3. AutoForge
4. Agent World Model
5. ResearchEnvBench
6. Agent-World
7. EnvFactory

如果要理解为什么 agent world 会扩展到 harness 和 loop，再追加：

1. Dive into Claude Code
2. AI Harness Engineering
3. Agentic Harness Engineering
4. From Agent Loops to Structured Graphs
5. Arbor
