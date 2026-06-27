# Agent World Environment Generation

本仓库当前任务是实现一个类似 Agent-World / AW 的环境生成系统。

用户给出环境需求、模型能力缺口、领域种子、工具生态、PRD、repo、MCP server、CLI、API/SDK 文档或其他资料后，系统应生成可复现、可验证、可发布、可被训练/评估流程消费的可执行环境包。

## 当前任务源

以 [docs/agent-world-environment-generation.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/agent-world-environment-generation.zh.md) 为准。

辅助背景：

- [docs/loop-engineering.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/loop-engineering.md)
- [research/notes/](/home/kelongzx/pycodes/loop_agent/agent-world-model/research/notes)

这些背景材料用于理解环境生成、任务生成、verifier、harness、workflow 和训练消费关系，不是直接实现计划。

## 与 AWM 的关系

本仓库来自 Agent World Model 代码，但当前目标不是复现 AWM 论文，也不是把 AWM JSONL、MCP 暴露形式或数据结构当成通用标准。

原有 `awm` CLI 仍可作为背景实现和兼容入口保留，后续只在明确需要时复用其中的环境管理、MCP surface、verifier 或样本处理能力。

## 当前不做

- 不继续 `awmx` demo。
- 不先实现 scripted rollout / reward / export demo。
- 不把所有环境固定成 MCP-only 或 CLI-only。
- 不把 generic shell command executor 当作环境 CLI surface。
- 不把 Codex SDK、mini-swe-agent、deep-search 或单一训练框架直接绑定进核心；需要时通过可插拔 agent backend adapter 调用。
- 不把训练框架集成作为第一步。
- 不下载完整 AWM 1K 数据到仓库。

## 设计方向

当前推荐形态不是固定“两条 loop”，而是一个确定性的环境生成工作流，并允许在明确 gate 后回到上游阶段：

```text
EnvironmentNeed / CapabilityGap / DomainSeed
  -> source discovery
  -> knowledge extraction
  -> environment specification
  -> tool dependency graph
  -> task generation
  -> surface planning
  -> verifier planning
  -> feasibility filtering
  -> implementation plan or code-agent request
  -> implementation and checks
  -> release package
  -> rollout/export/evaluation consumers
  -> failure analysis feedback
```

LLM 或 agent 可以作为 search、extraction、synthesis、judge、implementation 等显式节点，但流程控制、artifact、gate、日志和可重放状态必须由代码、typed config 或显式 DAG 表达。

需要调研 MCP、CLI、API/SDK 文档、repo 或其他资料时，可以在 workflow 中启动 search/code agent backend，例如 Codex SDK/CLI 或 deep-search adapter。此类调用必须写入 `AgentInvocationRecord`，并把结果转换成可审计 artifact，不能隐藏在 prompt 或人工临时步骤里。

Agent backend 的 OpenAI-compatible 配置使用新系统自己的环境变量：

- `AGENT_WORLD_AGENT_BACKEND`
- `AGENT_WORLD_OPENAI_BASE_URL`
- `AGENT_WORLD_OPENAI_API_KEY`
- `AGENT_WORLD_OPENAI_MODEL`
- `AGENT_WORLD_SMOKE_OPENAI_MODEL`
- `AGENT_WORLD_OPENAI_API_VERSION`
- `AGENT_WORLD_CODEX_CMD`

其中 API key 只能作为 env var 或 secret ref 使用，不能写入 artifact。`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` 可以作为兼容 fallback；旧 AWM 变量只允许作为 legacy fallback。

Goal/CI/live smoke test 如需真实模型，应优先用便宜模型，例如：

```bash
export AGENT_WORLD_SMOKE_OPENAI_MODEL=gpt-5.4-mini
# 或在可用时：
export AGENT_WORLD_SMOKE_OPENAI_MODEL=gpt-3-codex-spark
```

模型名必须来自配置或环境变量，不能在核心代码里写死。没有凭证、base URL、模型或网络权限时，live smoke test 应跳过，deterministic mock/manual tests 仍应运行。

## 第一实现切片

第一实现切片的阶段边界、artifact contracts、deterministic/static gates、surface 边界、首个 runnable fixture、release format 和验收标准已在 [docs/agent-world-environment-generation.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/agent-world-environment-generation.zh.md) 中冻结。

当前第一条 vertical slice 已进入 runtime 实现：第一 fixture 是非 AWM 的 `support-desk-lite`；Python callable 是最小 required surface，CLI、HTTP、MCP 只作为 planned-but-deferred surfaces 进入 `SurfacePlan`。第一实现切片包含可运行的 backend-neutral `AgentBackend` / `AgentInvocationRecord` 机制，并至少提供 deterministic mock/manual backend 和一个真实可调用的本地 agent backend，例如受控 `process_agent` 或 Codex CLI adapter。

## 下一 Goal

[docs/goal-02-hardcoded-full-chain.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-02-hardcoded-full-chain.zh.md) 定义下一阶段：基于当前硬编码 `support-desk-lite` 案例走通 release package -> rollout/eval -> reward records -> training export -> dataset-only trainer consumer。

这个 Goal 仍然不是通用环境自动生成。它的目的只是先把已发布环境到训练/评估消费的全链路打通，并保持训练框架作为可插拔 consumer。
