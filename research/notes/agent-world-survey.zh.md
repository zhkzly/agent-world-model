# Agent World 方向综述

> 边界说明：本文是研究背景，不是当前仓库的实现计划。当前任务源以 `docs/agent-world-environment-generation.zh.md` 为准；AWM 只提供背景和可参考素材，不能被当成目标架构或默认 schema。

## 一句话判断

Agent World 不是单纯的环境建模。更准确地说，它是在构建一种用于训练、评测和持续改进智能体的可执行世界系统。

这个方向的核心对象不是一个静态 benchmark，也不是一个只会返回 observation 的 simulator，而是一套可被 agent 反复交互、可验证、可回放、可扩展、可用于强化学习的数据和执行基础设施。

## 为什么这个方向出现

LLM agent 的能力瓶颈已经不只是模型本身。真实 agent 需要在多轮交互中调用工具、读写状态、处理错误、恢复失败、完成长期目标。传统数据集很难覆盖这些行为，因为它们通常是静态的、单轮的、缺少环境状态，也缺少可靠的奖励信号。

早期 agent benchmark 可以评估工具调用能力，但很难支撑大规模训练。真实 API 成本高、不稳定，LLM simulator 又容易出现状态幻觉。于是研究重心开始转向可执行环境：用代码、数据库、工具接口和 verifier 搭建可交互世界，再让 agent 在这些世界中学习。

## 主线一：从任务数据到可执行环境

AWM 是这条线的标志性工作。它把环境合成拆成场景、任务、数据库、工具接口、环境代码和 verifier 生成几个阶段，最终形成 SQL-backed、MCP-exposed 的可执行工具环境。

这个设计的关键点是状态转移不再依赖 LLM 口头模拟，而是由代码和数据库执行。这样得到的环境更稳定，也更适合产生 RL 所需的奖励信号。

AutoForge、CuES、EnvFactory 进一步说明，环境合成不是孤立方案，而是一类正在成型的方法族。它们分别强调自动环境合成、环境内任务生成、真实资源探索、轨迹自然化和 robust RL。

## 主线二：从环境到任务和奖励

只合成环境还不够。agent 训练真正需要的是任务、轨迹和可验证反馈。

CuES 关注 task scarcity：当一个新环境没有人工任务时，agent 如何从工具结构和环境 affordance 中生成有意义、可执行的任务。AutoForge 和 EnvFactory 则更强调高难度、可验证、多轮任务，以及可用于 SFT/RL 的轨迹生成。

Agent-RLVR 代表另一条重要补充线：在复杂 agent 环境里，奖励通常太稀疏，单纯 RLVR 不够。它引入 guidance，让 agent 先尝试、拿到环境反馈和指导，再用 guided trajectory 做 RL。这个思路说明，agent world 不只是 world，还需要训练 loop 设计。

## 主线三：从合成环境到自进化 arena

Agent-World 相比 AWM 的推进在于，它把环境生成和训练闭环耦合起来。它不只是生成一批环境，而是构建一个 self-evolving training arena。

它的两个核心部件是：

1. Agentic Environment-Task Discovery：从真实世界主题、数据库和工具生态中发现可执行环境与可验证任务。
2. Continuous Self-Evolving Agent Training：用多环境 RL、动态任务生成和失败诊断推动 agent policy 与环境任务共同进化。

这一步把 agent world 从“训练环境库”推向“训练生态系统”。环境不是一次性资产，而是会随着 agent 的失败模式继续扩张。

## 主线四：Harness Engineering

当环境存在以后，另一个问题出现：模型如何稳定地使用环境？

Harness Engineering 把关注点放在模型外层的运行时系统。这个系统负责上下文选择、工具暴露、权限、记忆、日志、回放、验证、失败归因和人工介入记录。

AI Harness Engineering 明确提出，软件工程 agent 的能力来自 model-harness-environment system，而不是单独来自模型。Agentic Harness Engineering 更进一步，把 harness 自身也放进自动进化闭环，用 observability 把每次 harness edit 变成可验证的实验。

这对 Agent World 很关键：可执行环境只有被 harness 正确暴露、隔离和观测，才会变成可训练、可评估的 agent world。

## 主线五：Loop Engineering

Agent loop 是 agent 系统的控制流：模型观察上下文，决定动作，调用工具，读取结果，再继续。问题是简单 while-loop 很快会暴露结构性缺陷：依赖关系隐式、恢复路径不可控、历史状态难以复现。

Dive into Claude Code 指出，很多 agent 系统的核心确实是简单 loop，但工程复杂度集中在 loop 外围：权限、上下文压缩、MCP、skills、hooks、subagents、worktree isolation 和 session storage。

From Agent Loops to Structured Graphs 和 From Agent Loops to Deterministic Graphs 则把问题推进到图结构：把执行过程从隐式对话历史提升为显式 DAG、依赖、节点状态和 replay。这个方向和 Agent World 的关系很直接：当 world 变复杂，线性 loop 不足以稳定管理长期任务。

## 主线六：自治研究系统

NORA 和 Arbor 把这些组件放到更长周期的研究工作流里。NORA 展示 domain-specialized harness 如何组织 skills、subagents、MCP servers 和 safety gates。Arbor 用 Hypothesis Tree Refinement 管理长期假设、实验、证据和经验沉淀。

这说明 Agent World 的终点可能不是单个工具使用 agent，而是可以长期探索、实验、归纳和改进的 autonomous research system。

## 统一框架

可以把这条路线压成一个六层栈：

1. World substrate：代码、数据库、文件系统、API、工具接口。
2. Task synthesis：从环境 affordance 生成可执行、多轮、自然的任务。
3. Verification：用单元测试、数据库状态、规则、LLM judge 或代码 verifier 给出奖励。
4. Harness：把模型、工具、权限、记忆、日志、验证和人工介入组织成运行时系统。
5. Loop or graph：控制 agent 如何计划、行动、观察、恢复、终止和回放。
6. Self-evolution：用失败诊断和动态任务扩展持续改进 agent、harness 和环境。

## 对“Agent World 是不是环境建模”的回答

如果把环境建模理解为“构造 agent 可以交互的状态空间”，那 Agent World 包含环境建模。

但如果把 Agent World 等同于环境建模，就会低估这个方向。真正有价值的是可执行性、可验证性、训练闭环和系统工程。

更准确的说法是：

`Agent World = executable environment + task generator + verifier + harness + loop + training/evolution protocol`

## 值得继续追的问题

1. 环境真实性：合成环境是否真的覆盖真实 API、真实错误和真实任务分布。
2. 任务自然性：任务是否像真实用户意图，而不是暴露工具调用顺序的 instruction trace。
3. Verifier 可靠性：奖励是否能验证最终状态，而不是只验证文本答案。
4. Harness 可迁移性：一个 harness 的结构性改进是否能跨模型、跨 benchmark 迁移。
5. Loop 可控性：什么时候 while-loop 足够，什么时候必须升级成 graph。
6. Self-evolution 稳定性：自动扩展任务和环境时，如何避免训练偏向、奖励投机和环境塌缩。

## 推荐阅读顺序

1. Agent-RLVR：先理解复杂 agent 环境中的奖励稀疏问题。
2. CuES 和 AutoForge：理解任务生成和环境生成如何自动化。
3. Agent World Model：读环境合成的完整工程管线。
4. ResearchEnvBench：理解环境合成能力如何被评估。
5. Agent-World：读环境、任务、训练和自进化如何合成一个 arena。
6. EnvFactory：看更轻量但强调真实资源和自然轨迹的环境合成路线。
7. AI Harness Engineering 和 Agentic Harness Engineering：理解模型之外的 runtime substrate。
8. Dive into Claude Code 和 From Agent Loops to Structured Graphs：理解 loop engineering 为什么会成为单独问题。
9. Arbor：看这些组件如何进入长期自治研究系统。

## Sources

- Agent-RLVR: https://arxiv.org/abs/2506.11425
- CuES: https://arxiv.org/abs/2512.01311
- AutoForge: https://arxiv.org/abs/2512.22857
- Agent World Model: https://arxiv.org/abs/2602.10090
- ResearchEnvBench: https://arxiv.org/abs/2603.06739
- From Agent Loops to Structured Graphs: https://arxiv.org/abs/2604.11378
- Dive into Claude Code: https://arxiv.org/abs/2604.14228
- Agent-World: https://arxiv.org/abs/2604.18292
- Agentic Harness Engineering: https://arxiv.org/abs/2604.25850
- NORA: https://arxiv.org/abs/2605.02092
- From Agent Loops to Deterministic Graphs: https://arxiv.org/abs/2605.06365
- Harness Engineering as Categorical Architecture: https://arxiv.org/abs/2605.12239
- AI Harness Engineering: https://arxiv.org/abs/2605.13357
- EnvFactory: https://arxiv.org/abs/2605.18703
- What makes a harness a harness: https://arxiv.org/abs/2606.10106
- Arbor: https://arxiv.org/abs/2606.11926
