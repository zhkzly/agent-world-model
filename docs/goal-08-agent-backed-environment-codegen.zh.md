# Goal 08: Agent-backed Environment Code Generation

本文定义第八条 Goal 模式任务。Goal 07 已经让 `project-board-lite` 从 source-grounded artifacts 写出 isolated `GeneratedEnvironmentBundle`，但当前 bundle 仍由 deterministic template/codegen 产生。Goal 08 的目标是补上真正缺失的一环：由可配置 code agent 在受控工作区内生成可执行环境代码，并经过同一套 build/check/replay gate 后才允许 release。

## 1. 任务定位

当前状态：

```text
project-board-lite sources
  -> SourceEvidenceIndex / KnowledgePack / S3-S7 artifacts
  -> ImplementationRequest
  -> deterministic template/codegen writes GeneratedEnvironmentBundle
  -> build/check/replay
  -> package/release
```

Goal 08 必须推进为：

```text
accepted artifacts + ImplementationRequest + bundle contract
  -> code-agent implementation node
     - AgentBackendConfig
     - AgentInvocationRecord
     - isolated writable workdir
     - explicit budget / timeout / permissions
  -> agent-generated candidate files
  -> GeneratedEnvironmentBundle
  -> build/check/replay from generated files
  -> package/release only after verified
```

重点不是绑定某一个 agent 产品，而是让 implementation node 可以真实调用 code agent 写环境代码。`openai_codegen` 是当前真实 OpenAI-compatible codegen backend：它调用 chat-completions endpoint，接收模型返回的 file contents，写入 isolated workdir，再交给 build/check/replay。Codex SDK/CLI、mini-swe-agent、Claude Agent SDK、OpenAI-compatible structured generation 或自定义 process agent 都只能作为 adapter。

## 2. 核心原则

- code agent 是 workflow node，不是隐藏人工步骤。
- code agent output 不能直接 release，必须通过 artifact validator、gate、independent review 和 build/check/replay。
- 生成物必须是可执行环境文件，不是只生成 JSON/YAML 计划。
- 默认 CI 路径仍可使用 deterministic/mock backend，但必须测试真实 adapter wiring 和安全约束。
- live backend smoke 必须可跳过；没有凭证、base URL、模型或网络权限时不能导致 deterministic tests 失败。
- API key 只能通过 env var 或 secret ref 传入，不得写入 artifact、prompt preview、trace preview 或 release package。
- 不能把 generic shell executor 当环境 CLI surface；process agent 只是 implementation node 的 backend adapter。

## 3. 推荐设计

### 3.1 Agent Codegen Node

新增或收紧 implementation node，例如 `AgentCodegenImplementationNode`。

输入：

- `ImplementationRequest`
- `NeedSpec`
- `SourceEvidenceIndex`
- `KnowledgePack`
- `EnvironmentSpec`
- `LogicalToolGraph`
- `TaskSet`
- `SurfacePlan`
- `VerifierPlan`
- `GeneratedEnvironmentBundle` contract / expected layout
- build/check/replay requirements

输出：

- `AgentInvocationRecord`
- code-agent trace refs
- generated candidate file manifest
- `GeneratedEnvironmentBundle`
- build/check/replay records
- failure class and recovery suggestion on failure

### 3.2 Backend Adapters

至少保留这些 backend 形态：

- `mock` / `manual`: deterministic tests 默认使用。
- `openai_codegen`: 调用 OpenAI-compatible chat-completions endpoint，让模型返回 `files[]` 的 path/content，由 backend 写入 isolated workdir 并计算 candidate manifest。
- `process_agent`: 调用外部 code-agent command，例如 mini-swe-agent、自定义脚本或 wrapper。必须固定 argv，使用 `subprocess.run(argv, shell=False)`，禁止 shell 拼接。测试 helper 不能被称为真实 codegen。
- `codex_cli`: 可选 adapter，使用配置中的 Codex command 或 `AGENT_WORLD_CODEX_CMD`。
- `codex_sdk`: 可选 adapter，作为后续更深集成；不能成为 core dependency。
- `openai_compatible`: 直接调用 OpenAI-compatible API 生成结构化 file bundle，可作为最小 live backend。
- `claude_agent_sdk` / `mini_swe_agent` / `custom`: 只能通过 adapter 接入。

core 代码只依赖 `AgentBackend` / `AgentBackendConfig` / `AgentInvocationRecord`，不得 import 某个 SDK 作为必需依赖。

### 3.3 安全边界

code agent 工作区必须隔离：

- 只允许写入本次 run 的 build/work dir，例如 `pipeline-store/build/agent-runs/<run_id>/`。
- 不允许直接修改仓库源文件、`.git`、`.codex`、`.agents`、用户 home 或 release 目录。
- candidate files 进入 bundle 前必须做 path normalization，拒绝绝对路径、`..`、symlink escape 和重复覆盖。
- generated file hashes 必须记录。
- stdout/stderr 只保存 preview，且执行 redaction。
- prompt/instruction 只能引用 secret env var 名称，不得包含 secret 明文。
- backend config 必须记录 model/base_url/api_version/backend kind/command/permissions/budget/timeout，但不记录 API key。
- 网络、认证和文件系统权限必须显式进入 `AgentInvocationRecord.permissions`。
- live network/code-agent 调用默认关闭，只有显式配置和用户批准时才运行。

### 3.4 生成物要求

code agent 至少要生成 `project-board-lite` 的一套可执行 bundle：

```text
generated/
  runtime.py
  seed_state.json
  verifier.py
  surface_descriptor.json
  check_replay.py
  build_manifest.yaml
```

要求：

- `runtime.py` 自己实现 state/reset/tool behavior，不能 import `agent_world.fixtures.project_board_lite` 冒充生成环境。
- `verifier.py` 自己实现 deterministic verifier，包含正反例检查。
- `surface_descriptor.json` 标明已实现 surface；未实现 CLI/HTTP/MCP 只能 deferred。
- `check_replay.py` 从 generated files import/加载 runtime 和 verifier，执行成功任务与负例。
- `build_manifest.yaml` 记录 source artifact refs、implementation request ref、file hashes、commands 和 check result。

## 4. 配置策略

优先使用已有 `AgentBackendConfig`。环境变量建议：

- `AGENT_WORLD_AGENT_BACKEND`: 默认 agent backend。
- `AGENT_WORLD_CODE_AGENT_CMD`: generic process-agent/code-agent command。
- `AGENT_WORLD_CODEX_CMD`: Codex CLI command，仅供 `codex_cli` adapter 使用。
- `AGENT_WORLD_OPENAI_BASE_URL`
- `AGENT_WORLD_OPENAI_API_KEY`
- `AGENT_WORLD_OPENAI_MODEL`
- `AGENT_WORLD_SMOKE_OPENAI_MODEL`
- `AGENT_WORLD_OPENAI_API_VERSION`

兼容 fallback：

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

实现不能把模型名写死在 core 代码。真实 codegen smoke 使用 `AGENT_WORLD_AGENT_BACKEND=openai_codegen`，并显式设置 base URL、API key、model 和 `AGENT_WORLD_AGENT_NETWORK=1`。Goal/live smoke 如果需要真实模型，使用 `AGENT_WORLD_SMOKE_OPENAI_MODEL` 或配置文件指定的便宜模型；未配置时跳过。

## 5. 不做什么

不要实现：

- 真实 trainer loop。
- GPU/Ray/vLLM/SGLang。
- 第三个领域。
- 通用网络 search 默认路径。
- MCP 全量 server。
- generic shell executor。
- 让 code agent 直接修改 repo 并把 diff 当作 release。

不要误判：

- deterministic template/codegen 不等于 agent-generated environment。
- `AgentInvocationRecord` 存在不等于生成物已 verified。
- Codex/Claude/mini-swe 的 CLI 能运行不等于它们是环境 CLI surface。
- live smoke pass 不等于通用环境生成已完成。

## 6. 验收标准

完成后应满足：

- `uv run pytest` 全部通过。
- 旧 `awm` CLI 行为不破坏。
- `support-desk-lite` full chain 仍通过。
- `project-board-lite` deterministic generated bundle 回归仍通过。
- 新增 agent-backed implementation path。
- 新增真实 `openai_codegen` implementation backend，能调用 OpenAI-compatible endpoint，解析模型返回的 file contents，写入 isolated workdir。
- agent-backed path 产生 `AgentInvocationRecord`，记录 backend kind、model/runtime、base URL 或 command ref、权限、预算、trace、输入输出 artifact refs，并做 secret redaction。
- mock/process code agent 在 isolated workdir 生成 bundle files 用于 deterministic wiring tests；不得把本地 helper 输出称为真实 codegen。
- build/check/replay 从 agent-generated files 执行，成功任务 pass，负例 fail。
- malformed agent output、path traversal、缺失 runtime/verifier/check file、hash mismatch 或 check failure 时不得生成 release。
- release/package plan 只能引用 verified agent-generated bundle。
- live backend smoke 默认 skip；显式配置后只验证 wiring 和小规模 bundle，不依赖外部网络作为常规测试。

## 7. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、README.md、docs/agent-world-environment-generation.zh.md、docs/goal-07-generated-environment-bundle.zh.md、docs/goal-08-agent-backed-environment-codegen.zh.md、docs/project-progress-and-corrections.zh.md。

目标：实现 Goal 08。当前 project-board-lite 的 GeneratedEnvironmentBundle 由 deterministic template/codegen 生成；本 Goal 要新增 agent-backed implementation path，让一个可配置 code agent 在 isolated workdir 内生成可执行环境 bundle 文件，并通过同一 build/check/replay gate 后才允许 S10/S11 release。

实现要求：
1. 新增或收紧 AgentCodegenImplementationNode / 等价节点。
2. core 只能依赖 AgentBackend、AgentBackendConfig、AgentInvocationRecord，不得把 Codex SDK、mini-swe-agent、Claude Agent SDK 或某个具体 SDK 作为必需依赖。
3. 支持 deterministic mock/manual backend 作为默认测试路径。
4. 支持真实 codegen backend：openai_codegen。它必须调用 OpenAI-compatible chat-completions endpoint，让模型返回 files[] path/content，由 backend 写入 isolated workdir 并计算 candidate manifest。
5. 支持至少一个本地 adapter slot：process_agent 或 codex_cli。process adapter 必须固定 argv，使用 subprocess.run(argv, shell=False)，禁止 shell=True、bash -c、管道、重定向和任意 shell 拼接。process test helper 不得被称为真实 codegen。
6. 支持 AGENT_WORLD_CODE_AGENT_CMD、AGENT_WORLD_CODEX_CMD、AGENT_WORLD_OPENAI_BASE_URL、AGENT_WORLD_OPENAI_API_KEY、AGENT_WORLD_OPENAI_MODEL、AGENT_WORLD_SMOKE_OPENAI_MODEL、AGENT_WORLD_OPENAI_API_VERSION；openai_codegen live smoke 还必须显式设置 AGENT_WORLD_AGENT_NETWORK=1；secret 只能记录 env var/ref，不得落盘明文。
7. code agent 只能写 isolated build/work dir。进入 bundle 前必须拒绝绝对路径、..、symlink escape 和未声明文件。
8. agent-backed path 必须生成 runtime.py、seed_state.json、verifier.py、surface_descriptor.json、check_replay.py、build_manifest.yaml。
9. generated runtime/verifier/check 不能 import agent_world.fixtures.project_board_lite 冒充环境实现。
10. build/check/replay 必须从 agent-generated files import/执行，至少覆盖一个成功任务和一个负例。
11. malformed output、缺失文件、hash mismatch、check failure 或 path traversal 时 pipeline fail/needs_human，不能生成 ReleaseManifest。
12. 保持 Goal 02-07 回归、support-desk-lite full chain、project-board deterministic bundle、environment_cli、HTTP wrapper 和旧 awm CLI 不破坏。
13. 更新 README、docs/agent-world-environment-generation.zh.md、docs/project-progress-and-corrections.zh.md，明确当前真实性等级和剩余边界。

不要做：
- 不实现真实 trainer。
- 不实现 GPU/Ray/vLLM/SGLang。
- 不新增第三领域。
- 不实现 MCP 全量 server。
- 不把 generic shell executor 当 environment CLI。
- 不让 live network/model 调用成为默认测试依赖。
- 不把 deterministic template 输出冒充 agent-generated code。

验收：
- PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
- project-board-lite agent-backed path 生成 isolated bundle。
- openai_codegen backend 通过本地 fake OpenAI-compatible endpoint 测试，确认模型返回 file contents 后由 backend 写入 generated files。
- bundle 文件 hash 和 source refs 被记录。
- AgentInvocationRecord redaction 正确。
- 成功任务 verifier pass，负例 verifier fail。
- 破坏 generated runtime/verifier/check 或模拟恶意路径时不得 release。
- live backend smoke 在无配置时 skip，在显式配置时只做最小 wiring 检查。

完成后请输出：
- PASS / PASS WITH RISKS / FAIL
- 改动文件列表
- agent-backed implementation path 如何调用 backend
- generated bundle 文件结构
- 安全边界如何执行
- build/check/replay 如何验证生成环境
- 哪些内容仍然是 fixture/domain-specific
- 如何运行完整验证
- 下一 Goal 建议
```
