# 可维护 Agent World 框架计划

## 0. 先澄清概念

你的直觉基本正确：当前 AWM 更像环境生成与环境管理，Agent-World 更像把环境发现、任务生成、训练和自进化拼成一个 loop，但代码未开源，难以直接复现。

更稳的路线不是复刻论文，而是做一个可维护的 Agent World runtime，把已有组件装进统一框架：

- AWM 负责环境生成和 verifier 起点。
- CLI / MCP / Python / HTTP 都只是 tool adapter。
- Codex SDK、mini-swe-agent、deep search agent 都只是 runner。
- workflow 由代码或显式 DAG 执行，LLM 只负责生成候选 spec、诊断失败、提出修改。
- verifier 和 trace 是系统核心，训练只是消费这些产物。

一句话：先复用 AWM 做可观测、可验证、可回放的 agent-world 最小闭环，再接更多 runner、环境演化和 verl 或其他 RL 框架。

## 1. 核心判断

### Agent World 不是环境本身

环境只是 world substrate。真正应该构建的是：

```text
scenario -> task -> environment -> check -> release -> rollout -> verify -> reward -> feedback -> regenerate/retrain
```

这个链条里的每一步都应该产生明确 artifact，而不是只留在上下文窗口中。

### Loop Engineering 的正确落点

不要把 loop 理解成“让 LLM 一直自己想下一步”。更好的设计是：

- LLM 可以生成 workflow 草案。
- workflow 必须落成 YAML/JSON/Python DAG。
- DAG 节点调用确定性函数、CLI、MCP tool 或 agent runner。
- DAG 每一步都有输入、输出、错误、重试、预算和 verifier。
- 失败后由诊断 agent 生成结构化 feedback，而不是直接修改所有东西。

### Harness Engineering 的正确落点

harness 的责任不是重写一个完整 agent 系统，而是在 AWM、CLI、MCP、Codex SDK、mini-swe-agent 等组件之间提供一层薄控制缝合，控制模型不跑偏：

- 给它正确上下文。
- 限制它能调用的工具。
- 记录它每一步做了什么。
- 把环境状态和验证结果反馈给它。
- 在失败时让它进入恢复路径，而不是无限循环。
- 把每次运行变成可以审计的 episode package。

因此第一版 harness 的边界要收窄：能复用 AWM 的环境管理、MCP tool、agent demo、verifier，就先复用；只有某个 workflow 节点确实需要智能执行、搜索、调试或 review 时，才调用外部 agent runner。

### 数据库状态转移为什么重要

AWM 把数据库当作状态后端是对的。它类似编译器和测试系统：

- schema 检查工具是否能执行。
- 初始数据库定义 state。
- 工具调用改变 state。
- verifier 读取最终 state。
- reward 可以基于结构化状态，而不是依赖 LLM 主观打分。

这也是比纯 LLM simulator 更可靠的地方。

## 2. 目标系统

目标不是立即训练一个模型，而是先得到一个稳定框架：

```text
AgentWorldFramework
  input: scenario seeds / documents / web findings / existing AWM outputs
  output: checked environments, checked tasks, rollout traces, verifier results, reward datasets
```

最小可行版本应该做到：

1. 读取一个已有 AWM 环境或生成一个小环境。
2. 对环境做静态和动态 check。
3. 发布到本地 registry。
4. 用一个 runner 执行一个任务。
5. 记录完整 trajectory。
6. 用 verifier 输出 reward。
7. 导出训练样本或 eval 样本。

## 3. 建议架构

### 3.1 Artifact Registry

先定义 artifact，而不是先写复杂 agent。

建议 artifact 类型：

- `ScenarioSpec`: 场景名称、领域、约束、数据来源。
- `TaskSpec`: 用户任务、难度、允许工具、成功标准。
- `EnvironmentSpec`: 状态后端、工具接口、启动方式、依赖。
- `ToolSpec`: name、input schema、output schema、side effects、adapter type。
- `VerifierSpec`: 检查方式、输入、期望状态、reward mapping。
- `WorkflowSpec`: DAG 节点、依赖、预算、失败策略。
- `RunSpec`: runner、模型、环境实例、任务、预算。
- `Trace`: prompts、actions、tool calls、observations、state snapshots、errors。
- `RewardRecord`: verifier 输出、reward、失败分类、可训练字段。
- `FeedbackRecord`: 失败原因、建议修复、建议生成的新任务或 harness 修改。

这些 artifact 可以先用 JSONL 存，后续再进 SQLite/DuckDB。

### 3.2 Adapter Layer

不要押注 MCP 或 CLI。统一抽象为 adapter：

```text
Adapter.run(input) -> Observation
Adapter.check() -> CheckResult
Adapter.describe() -> ToolSpec
```

需要支持：

- `cli`: 调用 shell 命令，适合 clianything 这类项目。
- `mcp`: 复用 AWM 当前接口。
- `python`: 直接调用 Python 函数，适合内部 verifier 和环境构造。
- `http`: 调用真实服务或本地 server。
- `agent`: 调用 Codex SDK、mini-swe-agent 或 deep search agent。

CLI 很值得支持。LLM 确实擅长使用 shell，但 harness 必须提供命令白名单、cwd、timeout、stdout/stderr 截断、文件变更记录和退出码检查。

### 3.3 Workflow Engine

建议先不要引入复杂外部编排系统。第一版可以用 Python 执行 DAG：

```text
generate_scenario
  -> generate_task
  -> build_env
  -> check_env
  -> check_task
  -> release_env
  -> rollout_agent
  -> verify_trace
  -> export_reward
  -> diagnose_failure
```

LLM 可以生成 workflow spec，但必须经过：

- schema validation
- dependency validation
- tool availability check
- dry-run check
- budget check
- verifier presence check

### 3.4 Harness

harness 应该独立于 runner，负责薄控制面，不负责实现完整 agent，也不替代 AWM 已有环境和 verifier：

- context assembly：给 agent 什么任务、工具说明、约束和历史。
- permissions：哪些 CLI/MCP/API 可调用。
- sandbox：工作目录、可写目录、网络、超时。
- observability：每一步写 trace。
- recovery：失败时走重试、降级、人工确认或任务判失败。
- verification：调用 verifier 并生成 reward。
- replay：从 trace 重放关键步骤或至少审计关键证据。

当 workflow 节点确实需要 LLM 能力时，只暴露两个显式调用点：

```text
agent(task_prompt, verification_prompt=None, runner="scripted|mini_swe|codex_sdk|mcp|deep_search")
assert(prompt, evidence, runner="codex_sdk|llm_judge")
```

含义：

- `agent()` 负责干活，例如 repo 修改、搜索、工具调用、任务采样。
- `verification_prompt` 是单次 agent 调用的准出门，但不能替代外层 verifier。
- `assert()` 负责判断，例如 review、rubric 检查、失败归因。
- workflow 的控制流必须仍由代码或 DAG 执行，不能让 runner 自己决定整条 pipeline。
- 每次调用都必须进入 permissions、budget、trace、verifier/review gate。

核心壁垒不是“harness 做得大”，而是 artifact/trace/reward 协议稳定，且能把 AWM、CLI、MCP 和必要的 agent runner 统一进可审计闭环。

### 3.5 Rollout Runner

runner 应该可替换：

- `codex-sdk-runner`: 适合真实软件工程任务、文件修改、CLI-heavy 工作。
- `mini-swe-agent-runner`: 适合开源轻量软件工程采样。
- `mcp-agent-runner`: 适合当前 AWM MCP 工具环境。
- `deep-search-runner`: 适合需要 web/search/research 的任务。
- `scripted-baseline-runner`: 用确定性脚本建立下限和 sanity check。

不要让训练数据格式绑定某个 runner。

runner 接入顺序应该服从最小闭环，而不是为了接入而接入：

1. `scripted-baseline-runner`: 先建立可测下限。
2. `awm-cli/mcp runner`: 复用 AWM 的环境启动、检查、agent demo 和 verifier。
3. `fake-mini-swe-agent-runner`: 只有当某个节点需要 CLI-heavy agent 时，用固定 command/history 测 trace mapping 和 permission gate。
4. `mini-swe-agent-runner`: 接真实 mini-swe-agent，但所有 command 仍走 harness permission。
5. `fake-codex-sdk-runner`: 只有当某个节点需要 repo engineering/review 时，用固定文件修改、测试结果和 review 结果测 artifact mapping。
6. `codex-sdk-runner`: 接真实 Codex SDK，用于复杂调试和独立 review。
7. `deep-search-runner`: 只有研究和 web/search workflow 需要时再接。

mini-swe-agent 的价值是轻量、bash action、线性 history，适合受控采样；Codex SDK 的价值是复杂工程能力和独立 review；AWM 的价值是 code + DB backed environment 和 verifier reward。三者都不能绕过 harness。

### 3.6 Verification And Reward

reward 优先级：

1. 代码 verifier / unit test / command exit code。
2. 数据库最终状态检查。
3. 文件 diff 或 artifact 检查。
4. 多条件 rubric。
5. LLM judge 只作为补充。

每个 reward 都应该记录：

- 是否成功。
- 哪个 verifier 成功或失败。
- 失败证据。
- 是否可重试。
- 是否是环境错误、agent 错误、任务错误、verifier 错误或 harness 错误。

### 3.7 Training Bridge

不要第一步就做完整 verl 在线训练。先做训练数据出口：

- SFT 格式：任务、上下文、工具调用轨迹、最终答案。
- RL 格式：prompt、trajectory、reward、metadata。
- DPO/Preference 格式：成功轨迹 vs 失败轨迹。
- Verifier dataset：任务、答案、状态、verifier 输出。

等 trace/reward 稳定后，再接：

- verl
- OpenRLHF
- TRL
- 自定义 GRPO/PPO rollout loop

## 4. 分阶段路线

### Phase 1: 文档和 artifact contract

目标：把系统边界固定下来。

交付物：

- `AGENTS.md`
- `docs/agent-world-framework-plan.zh.md`
- artifact schema 草案
- 一条最小 workflow 的 JSON/YAML 示例

完成标准：

- 后续 LLM 能根据文档知道该做什么、不该做什么。

### Phase 2: 包装现有 AWM

目标：不改 AWM 核心逻辑，先把现有 CLI 包成 workflow 节点。

交付物：

- `workflow` 模块
- `artifact` 模块
- AWM command adapter
- `check_env`、`check_task`、`verify_trace` 节点封装

完成标准：

- 能从一个 seed scenario 跑到 checked environment artifact。
- 能从 `research/data/awm_1k_samples/` 离线导入至少一个 scenario/task/db/spec/verifier 组合。

### Phase 3: Trace-first rollout

目标：先采样，不训练。优先使用 scripted 或 AWM 现有 agent/MCP 路径，真实 Codex SDK/mini-swe-agent 不是本阶段必要条件。

交付物：

- runner interface
- 一个 scripted runner
- 一个 AWM CLI/MCP runner 或 AWM run importer
- trace schema
- reward record schema

完成标准：

- 一个任务可以被 runner 执行，完整记录 trace，并由 verifier 生成 reward。

### Phase 4: CLI adapter

目标：支持 clianything 风格的软件即工具。

交付物：

- CLI tool spec
- command whitelist / timeout / cwd / env 控制
- stdout/stderr capture
- file change capture

完成标准：

- 一个 CLI 工具可以被注册、检查、调用、记录、验证。

### Phase 5: Agent runners

目标：让复杂 workflow 节点可以调用 agent。只有当 AWM/scripted/MCP 不能覆盖该节点时才进入本阶段。

交付物：

- fake Codex SDK runner contract
- fake mini-swe-agent runner contract
- 按需实现真实 Codex SDK runner
- 按需实现真实 mini-swe-agent runner
- deep-search runner
- runner budget and stop conditions

完成标准：

- workflow 中某个节点可以委托给 agent，但 trace 仍由统一 artifact 协议记录。
- 如果没有真实 agent 节点需求，只保留 fake backend contract，不强行接真实模型。

### Phase 6: Training export

目标：接训练框架前先导出干净数据。

交付物：

- SFT exporter
- RL/reward exporter
- failure taxonomy
- dataset validation command

完成标准：

- 成功和失败 episodes 可以稳定导出，并能被训练脚本读取。

### Phase 7: Self-evolution

目标：让反馈指导下一轮任务、环境或 harness 修改。

交付物：

- failure analyzer
- task mutation generator
- verifier hardening generator
- harness edit proposal
- eval gate

完成标准：

- 系统能根据失败聚类提出下一轮要生成什么任务或修什么 harness，但所有修改都必须过 check。

## 5. 现在应该做什么

建议你现在不要先训练，也不要先做大规模环境生成。先做最小闭环：

```text
one scenario
one task
one AWM-backed or scripted environment
one scripted/AWM runner
one verifier
one trace
one reward record
one export file
```

这条闭环跑通以后，再扩展 runner、adapter、环境数量和训练。

## 6. 适合 Codex Goal Mode 的目标

可以用下面这个 goal：

```text
Implement the first vertical slice described in docs/agent-world-framework-plan.zh.md. Use the existing AWM CLI as the initial environment backend. Stop when one environment/task can be checked, sampled by a simple runner, verified, and exported as trace/reward artifacts. Preserve existing AWM behavior.
```

如果你要更保守，可以先用：

```text
Design and implement artifact schemas plus a dry-run workflow runner for the first vertical slice in docs/agent-world-framework-plan.zh.md. Do not add training integration yet.
```

## 7. 风险和取舍

- 不要过早接 verl。没有稳定 trace/reward，训练只会放大噪声。
- 不要把 MCP 当唯一接口。CLI 和 Python adapter 更容易 debug，也更适合验证。
- 不要让 LLM 直接自由修改 workflow。让它产出 proposal，再经过 schema、check 和 eval gate。
- 不要只做 LLM judge。能用代码、数据库、测试和命令检查的地方都应该先用确定性检查。
- 不要把 self-evolution 理解为无限自动递归。每轮 evolution 都要有固定预算、明确 hypothesis 和回归评测。

## 8. 第一版目录建议

```text
awmx/
  artifacts/
    schemas.py
    registry.py
  adapters/
    base.py
    cli.py
    mcp.py
    python.py
    codex_sdk.py
    mini_swe.py
  workflow/
    spec.py
    runner.py
    nodes.py
  harness/
    context.py
    agent_call.py
    gates.py
    permissions.py
    trace.py
    replay.py
    failure.py
  rollout/
    runner.py
    scripted.py
    mini_swe.py
    codex_sdk.py
  verification/
    verifier.py
    rewards.py
  training/
    export.py
```

这里用 `awmx` 是为了不干扰现有 `awm` 包。等框架稳定后再考虑合并。
