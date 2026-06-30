# Agent World Environment Generation

本仓库当前任务是实现一个类似 Agent-World / AW 的环境生成系统。

用户给出环境需求、模型能力缺口、领域种子、工具生态、PRD、repo、MCP server、CLI、API/SDK 文档或其他资料后，系统应生成可复现、可验证、可发布、可被训练/评估流程消费的可执行环境包。

这里的“环境”不是一份 prompt 或单纯 JSON/YAML 计划，而是可执行后端/runtime 代码包：状态转移逻辑、seed/state fixture、logical tool surface、任务、deterministic verifier、check/replay 脚本、release metadata 和后续 consumer 入口都必须能被框架检查。Codex 或其他 code agent 可以参与写这些后端文件，但只能作为显式 workflow node；框架负责可执行性验证、正反例 verifier、bounded repair、打包和 release 决策。

## 当前任务源

以 [docs/agent-world-environment-generation.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/agent-world-environment-generation.zh.md) 为准。

辅助背景：

- [docs/loop-engineering.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/loop-engineering.md)
- [research/notes/](/home/kelongzx/pycodes/loop_agent/agent-world-model/research/notes)
- [docs/project-progress-and-corrections.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/project-progress-and-corrections.zh.md)

这些背景材料用于理解环境生成、任务生成、verifier、harness、workflow 和训练消费关系，不是直接实现计划。

## 本地环境与验证

本项目默认使用 `uv` 管理 Python 环境和执行命令。常用验证入口：

```bash
uv run pytest tests/agent_world/test_goal12_request_driven_pipeline.py
uv run pytest tests/agent_world
```

需要隔离缓存或 CI-like 运行时，可沿用 Goal 文档里的形式：

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
```

## 与 AWM 的关系

本仓库来自 Agent World Model 代码，但当前目标不是复现 AWM 论文，也不是把 AWM JSONL、MCP 暴露形式或数据结构当成通用标准。

原有 `awm` CLI 仍可作为背景实现和兼容入口保留，后续只在明确需要时复用其中的环境管理、MCP surface、verifier 或样本处理能力。

## 当前不做

- 不继续 `awmx` demo。
- 不把 scripted rollout / reward / export demo 当成通用环境生成能力。
- 不把所有环境固定成 MCP-only 或 CLI-only。
- 不把 generic shell command executor 当作环境 CLI surface。
- 不把 Codex SDK、mini-swe-agent、deep-search 或单一训练框架直接绑定进核心；需要时通过可插拔 agent backend adapter 调用。
- 不把 deterministic template/codegen 输出称为 agent-generated environment code。
- 不把本地 process test helper 称为真实 code generation；真实 codegen backend 必须从外部模型/agent 返回文件内容。
- 不把 `openai_codegen` 这种“模型返回 files[]，框架写文件”的后端称为完整 code agent runner。
- 不把真实训练框架、GPU/Ray/vLLM/SGLang 或 trainer loop 集成进核心。
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
  -> generated backend/runtime implementation and checks
  -> release package
  -> rollout/export/evaluation consumers
  -> failure analysis feedback
```

这是 loop-engineering 的落点：把原本反复手调 prompt、靠 agent 临场维持顺序的工作，固化成可重复、可审计、可中断/续跑的 workflow。LLM 或 agent 可以作为 search、extraction、synthesis、judge、implementation、repair 等显式节点，但流程控制、artifact、gate、日志、状态、retry budget 和 release 决策必须由代码、typed config 或显式 DAG 表达。

需要调研 MCP、CLI、API/SDK 文档、repo 或其他资料时，可以在 workflow 中启动 search/code agent backend，例如 Codex SDK/CLI 或 deep-search adapter。此类调用必须写入 `AgentInvocationRecord`，并把结果转换成可审计 artifact，不能隐藏在 prompt 或人工临时步骤里。

Agent backend 的配置使用新系统自己的环境变量。真实 file-content codegen 使用 `AGENT_WORLD_AGENT_BACKEND=openai_codegen`；真实 code agent runner 使用 `AGENT_WORLD_AGENT_BACKEND=code_agent_runner` 或 `codex_cli_runner`，并通过命令适配 Codex CLI、Claude Code、mini-swe-agent 或自定义 SWE agent：

- `AGENT_WORLD_AGENT_BACKEND`
- `AGENT_WORLD_CODE_AGENT_CMD`
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

## 当前实现切片

当前 active slice 是 request-driven generated environment pipeline：

- `PipelineRunner()` 默认使用 `request_driven_node_registry()`。
- `run_request_driven_pipeline()` 从 raw request 生成 S0-S11 artifacts。
- implementation 必须通过 `AgentBackend` 写 isolated candidate bundle。
- 框架验证 candidate manifest、path、hash、安全边界、generated self-check 和 independent verifier。
- independent verifier 从 accepted `TaskSet.framework_replay.tool_calls` 执行正反例，不按固定 environment id 分支。
- bounded repair loop 由 `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 控制。
- 成功 release 后，runtime 会复制到 `envpkg/runtime/generated/<bundle_id>/`，并通过 `envpkg/release/generated-runtime-index.yaml` 被 package consumer 加载。

当前能声称：

- request-driven artifact path 已跑通。
- agent-backed generated bundle contract 已跑通。
- framework replay contract、candidate check、independent verifier、repair packet 和 package consumer 已跑通。
- `awm` CLI 兼容入口保留。

当前不能声称：

- 任意领域都能高质量自动生成。
- 已实现 live 网络 discovery。
- 已实现成熟通用 verifier synthesis。
- live code agent 默认稳定成功。
- 已实现通用 rollout/online adapter 或真实 trainer。

旧的 staged fixture goal 文档已经从 active docs 中删除。后续新增能力必须继续走 request-driven planner/source/extraction/synthesis/implementation/verifier/package path，不能用新的固定 demo registry 代替通用流水线。
