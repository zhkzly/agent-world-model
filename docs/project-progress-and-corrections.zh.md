# Project Progress And Corrections

本文记录项目当前真实状态和已经纠正的偏差。它不替代 `docs/agent-world-environment-generation.zh.md`。

## 当前任务

本项目要做的是类似 Agent-World / AW 的环境生成系统，而不是 AWM 论文复现。

目标输入可以是环境需求、模型能力缺口、领域 seed、PRD、repo、MCP server、CLI、API/SDK docs、数据库 schema 或其他资料。目标输出是可复现、可验证、可发布、可被训练/评估消费的可执行环境包。

这里的“环境”应理解为后端/runtime 代码包：状态转移逻辑、工具 surface、seed/state fixture、任务、verifier、check/replay、release metadata 和后续 consumer 入口。LLM/Codex 等 agent 负责显式节点上的搜索、抽取、代码实现、review 或 repair；框架代码负责状态、gate、记录、retry budget 和 release 决策。

## 当前已完成的真实能力

- `run_request_driven_pipeline()` 是当前 active path。
- 任意非空 raw request 会产生 `DomainPlan`、`StrategySelection`、source evidence、`KnowledgePack`、`EnvironmentSpec`、`LogicalToolGraph`、`TaskSet`、`VerifierPlan`、`FeasibilityReport` 和 `ImplementationRequest`。
- environment id、工具、任务和 replay cases 从 request/source artifact 派生，不靠固定环境分支。
- IMPLEMENT 阶段强制走 `AgentBackend`，由 agent 在 isolated workdir 写 `runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`。
- 框架执行 manifest/path/hash/security check、generated self-check、generic independent verifier、bounded repair 和 package/release。
- `input/framework-replay-contract.json` 由框架生成，描述 runtime entrypoint、constructor、helpers、manifest rules、trace contract 和 replay cases。
- independent verifier 只按 accepted task replay contract 执行正反例，不再按 environment id 分发到专用 verifier。
- 成功 release 后，generated runtime 被复制到 `envpkg/runtime/generated/<bundle_id>/`，并写入 `envpkg/release/generated-runtime-index.yaml`。
- `run_packaged_generated_bundle_check(package_dir)` 可以从 package 内重新执行 generated check 和 framework independent verifier。
- `awm` CLI 作为兼容入口保留。

## 已纠正的偏差

### 1. AWM 复现偏差

早期理解曾偏向 AWM-first 或 demo-first。当前纠正为：

- AWM 只作为背景知识和可选 source。
- 旧 AWM 数据格式和 MCP 形态不能主导新框架结构。
- 保留 `awm` CLI 兼容，但不让它定义环境生成架构。

### 2. CLI 概念偏差

曾把 runtime control CLI 和 environment tool CLI 混在一起。当前纠正为：

- environment CLI 是环境工具 surface。
- runtime control CLI 是 harness/debug/control entrypoint。
- agent backend CLI 是 code-agent runner 适配器。
- 当前 active slice 只要求 generated Python callable surface 可执行，其他 surface 可以先作为 descriptor。

### 3. 训练/rollout 先行风险

早期曾先补下游 consumer，容易让人误判环境生成已经完成。当前纠正为：

- 训练框架是 release package 的下游 consumer，不是 core dependency。
- 当前没有真实 trainer loop、GPU/Ray/vLLM/SGLang worker 或训练结果反馈闭环。
- 后续训练反馈必须作为显式 feedback edge 接入。

### 4. 硬编码环境路径风险

早期存在固定 fixture registry、固定 task、固定 replay case 和专用 verifier 分支。当前纠正为：

- active package 删除了旧 fixture/runtime/training/rollout modules。
- `PipelineRunner()` 默认使用 request-driven registry。
- generic verifier 只消费 `TaskSet.framework_replay.tool_calls`。
- tests 聚焦 generic request-driven generated bundle、bounded repair、candidate check、package consumer 和 artifact/gate contracts。

### 5. Code agent 与 release authority

用户明确要求真实 code generation workflow，而不是只调用 LLM 或本地模板。当前纠正为：

- `AgentBackend` 是唯一 codegen/runner 调用边界。
- agent 写候选文件，不决定 release。
- generated check stdout 只是辅助证据。
- 框架侧 independent verifier 和 gate 决定是否进入 S10/S11。
- repair packet 作为结构化 observation 喂回同一 backend。

## 当前真实性等级

能声称：

- 通用 request-driven pipeline 结构已跑通。
- agent-backed candidate bundle contract 已跑通。
- framework replay contract 和 independent verifier 已跑通。
- generated check forgery、bad verifier、runtime traceback、repair success、repair exhaustion 均有测试覆盖。
- package-relative generated runtime consumer 已跑通。

不能声称：

- 任意领域都能高质量生成。
- 已经实现 live 网络 discovery。
- 已经实现成熟的 source-grounded schema/task/verifier synthesis。
- live external code agent 默认稳定成功。
- 已经实现通用 deployment/rollout/online adapter。
- 已经接入真实 trainer。

## 下一优先级

- 扩展 source planning，使本地 PRD/schema/CLI/API docs/repo/MCP 描述能作为 source 输入。
- 提升 extraction/synthesis 质量，减少 raw-request-only heuristic。
- 增强 `ImplementationRequest` 和 `framework-replay-contract.json`，让 live code agent 更容易生成满足 contract 的 runtime/verifier。
- 基于 packaged generated runtime index 设计通用 rollout/online adapter。
- 在 rollout/online adapter 稳定后，再设计训练反馈到环境生成的外层 loop。

## 持续警惕

- 不要新增硬编码 smoke domain 来绕过 request-driven path。
- 不要把 deterministic template 输出称为真实 codegen。
- 不要把 process helper 当成 live code agent 质量证明。
- 不要把 API key、base URL credential、auth token 写进 artifact 或 trace 明文。
- 不要让 live backend 成为默认测试依赖。
- Python 验证命令默认用 `uv run ...`。
