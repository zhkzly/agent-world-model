# Agent World 环境生成项目目标

本文是项目目标源文档。旧任务记录、会话记录、研究说明或实现计划若与本文冲突，以本文为准。

## 目标

构建一个 Agent-World-like 的环境生成系统：

- 输入：环境需求、能力缺口、领域 seed、PRD、repo、MCP server、CLI、API/SDK 文档、数据库 schema、本地资料或环境样本。
- 输出：可复现、可验证、可发布、可被训练/评估消费的可执行环境包。
- 环境形态：后端/runtime 代码包，而不是 prompt、方案文档或静态 JSON/YAML。

环境包至少表达：

- 状态模型与状态转移逻辑。
- seed/state fixture。
- logical tool 到 concrete surface 的绑定。
- task set。
- deterministic verifier。
- check/replay 入口。
- release metadata。
- downstream loader/consumer contract。

参考锚点：Agent-World 论文把核心问题描述为，通用 agent 需要与外部、有状态的 tool environments 交互，但训练鲁棒 agent 缺少真实环境和持续学习机制。它提出的两个关键模块是 Agentic Environment-Task Discovery，以及 Continuous Self-Evolving Agent Training。本文档参考这些系统思想，但不复现论文数据格式或实现边界。论文链接：https://arxiv.org/abs/2604.18292

## 流水线

本质上这是 loop engineering：把环境构造拆成可审计节点，由代码维护流程、状态、artifact、gate 和 retry/repair；需要智能判断或生成的节点声明 deterministic、llm 或 agent execution mode，并在需要模型/工具调用时通过 invocation backend 执行一次 attempt。人类只在必要时介入，例如需求歧义、权限授权、外部凭证、风险确认、发布决策或 repair 预算升级。

典型输入可以只是一个文本需求，例如“生成一个飞机订票场景环境”。Pipeline 后续应自动完成需求调研、MCP/CLI/API/SDK/tool surface 发现、knowledge extraction、task generation、verifier planning、code generation、运行检查、独立验证、repair 和发布打包。

目标流程：

```text
request / source material
  -> source discovery
  -> knowledge extraction
  -> environment specification
  -> logical tool graph
  -> task generation
  -> surface planning
  -> verifier planning
  -> implementation request
  -> Codex SDK / agent-backed runtime implementation
  -> framework-owned build/check/replay
  -> independent verification
  -> bounded repair when needed
  -> publishable envpkg / environment-pack
```

框架负责流程控制、artifact、gate、trace、预算、repair 和 release 决策。Agent 只在显式节点中负责搜索、抽取、生成、判断、代码实现或修复。

每个关键节点都必须有可检查输出：输入 artifact、输出 artifact、invocation record、gate/review result、失败原因和必要的 repair packet。不能让某一步只存在于 prompt、stdout 或人类记忆里。

与论文思想的对应关系：

- Environment-task discovery：从文本需求、文档、数据库、MCP/CLI/API/SDK/tool ecosystem 中发现环境主题、状态空间、工具面和可验证任务。
- Controllable difficulty：task generation 需要记录依赖路径、允许工具、预期状态变化和 verifier，而不是只生成自然语言任务。
- Capability gap：失败样本、repair packet、verifier observation 和后续训练/评估结果都应能回流为下一轮环境或任务生成信号。
- Co-evolution：环境生成、任务生成、agent 能力评估和训练消费是外层反馈 loop，但 core release 仍由 framework verification 决定。

## Codex SDK

Codex SDK 是优先支持的真实 code-agent invocation backend；Claude Code SDK 或其他同级 runner 也应通过相同 invocation backend contract 接入。

- 真实调用官方 Codex SDK，不用 mock、demo 或通用 shell runner 伪装。
- SDK 调用集中在 `InvocationBackend` adapter，例如 `codex_sdk`。
- Pipeline core 只依赖 backend contract，不散落 SDK 调用。
- 每次调用记录 backend-neutral invocation record。
- token、API key、secret-bearing URL、本地 Codex auth 状态不得写入 artifact、trace 或 release package。

## 不变量

- 成功路径必须由 artifact 派生，不能依赖固定 environment id、固定 task id、固定 replay case 或领域 registry。
- Source、task、tool、surface、verifier、runtime、package 都必须可追溯。
- logical tool 和 concrete surface 必须分离；surface 可以是 Python callable、CLI、HTTP、MCP、database 或 local service。
- Generic shell executor 不能冒充环境 tool surface。
- Generated self-check 只是辅助证据，release authority 属于 framework-owned independent verifier。
- 失败后只能进入 bounded repair；agent 不能控制 pipeline flow 或自行决定 release。

## 发布结构

单环境包稳定入口采用 contract-project 形态。环境内部代码由 code agent 根据需求自由实现；框架只固定发布、加载和运行控制边界：

```text
envpkg/
  manifest.json
  runtime/
    runtime_index.json
    project/
      contract.json
      source/
      state/
      adapters/
      scripts/
      spec/
  spec/
    need.json
    environment.json
    tool_graph.json
    tasks.jsonl
    verifiers.jsonl
  checks/
    independent_verification_report.json
    invocation_records.jsonl
  release/
    release_manifest.json
    runtime_index.json
```

`contract.json` 必须声明 `agent-world.runtime-abi.v1` 的八个接口：`describe`、`setup`、`reset`、`health`、`invoke`、`verify`、`export_trace`、`teardown`。MCP、CLI、HTTP、数据库、本地服务或 Python callable 都只是这些接口背后的 adapter，不是所有环境都必须采用的固定形态。

多环境 pack 使用目录型主形态：

```text
environment-pack/
  pack.json
  environments.jsonl
  data/*.jsonl
  packages/<environment_id>/<version>/envpkg/
  runner/
  archives/      # optional
  exports/       # optional
```

`manifest.json`、runtime index、release manifest 和 pack index 必须交叉校验 `environment_id`、`version` 和 implementation identity。

## 边界

- AWM 只作为背景知识和 source evidence，不是目标架构、数据格式或系统边界。
- 训练/评估框架是 consumer，不是 core dependency。
- 保留 `awm` CLI 兼容，除非用户明确要求改变。
- 普通测试不能依赖 live model、网络或 credential。
- Python 命令使用 `uv`。
