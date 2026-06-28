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

## 第一实现切片

第一实现切片的阶段边界、artifact contracts、deterministic/static gates、surface 边界、首个 runnable fixture、release format 和验收标准已在 [docs/agent-world-environment-generation.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/agent-world-environment-generation.zh.md) 中冻结。

当前第一条 vertical slice 是非 AWM 的硬编码 `support-desk-lite` fixture。它已经覆盖 S0-S11 artifact workflow、deterministic gates、independent review records、backend-neutral `AgentBackend` / `AgentInvocationRecord`、Python callable fixture、release package、replay/verifier、Goal 02 的 rollout/reward/training export consumer、Goal 03 的 online runtime/GRPO metadata，以及 Goal 04 的 environment CLI surface correction。

边界仍然要明确：`support-desk-lite` 是 fixture/full-chain demo，不是通用环境自动生成器。`SurfacePlan` 保留第一切片的 surface-neutral 计划，其中 Python 是最小 required surface；release runtime descriptors 额外标注了当前硬编码 fixture 已实现的 `runtime_control_cli`、`environment_cli` 和本地 HTTP wrapper。Goal 05 已实现最小本地 source-grounded connector/extractor 和 agent-backed implementation slot；Goal 08 已让 `project-board-lite` 的 agent-backed bundle 在 mock/process backend 下通过 build/check/replay。通用/网络 source discovery、多领域 knowledge extraction、通用 environment spec synthesis、verifier synthesis、MCP 全量实现和真实 trainer 集成仍未实现。

当前真实性等级：code agent runner contract implemented, packaged generated runtime callable, independent generated bundle verifier and bounded repair loop implemented, and request-driven probe paths exist for `booking-service-lite` and `library-lending-lite`。仓库已经新增 `agent_world.pipeline`、`agent_world.store` 和 `agent_world.sources`，把 S0-S11 表达为可替换 node registry，把 artifact / gate / review / agent invocation / trace 写入统一 store。默认 `support-desk-lite` 路径从本地 PRD 生成 source-grounded artifacts；Goal 06 新增 `project-board-lite`，从 CLI help、YAML schema 和 examples 三类真实本地文件生成 `SourceEvidenceIndex`，再提取带 source refs 的 `KnowledgePack`，并通过同一个 `PipelineRunner`、`NodeRegistry`、`ArtifactStore`、gate/review 和 implementation/code-agent slot 跑通 S0-S11。Goal 07 已让 project-board deterministic implementation node 写出 isolated `GeneratedEnvironmentBundle`。Goal 08 新增 `openai_codegen` backend：它调用 OpenAI-compatible chat-completions endpoint，让模型返回 bundle file contents，由 backend 写入 isolated workdir，记录 `AgentInvocationRecord`，通过 path/hash/security checks，再从 generated files 执行成功任务和负例 verifier 后才进入 S10/S11。Goal 09 新增 `code_agent_runner` / `codex_cli_runner` runner path：pipeline 会写入 `input/` workspace packet，外部 runner 在 `generated/` 写环境代码、运行 check、在 `agent-output/` 产出 manifest 和命令日志；框架随后只从 `generated/` 验证并 release。Goal 10 新增 package 化入口：成功 S11 后会把 accepted generated bundle 复制到 `envpkg/runtime/generated/<bundle_id>/`，写 `envpkg/release/generated-runtime-index.yaml`，并可通过 `run_packaged_generated_bundle_check()` 从 package 内执行。Goal 11 新增 framework-owned independent verifier：bundle/package gate 不再只信任 generated `check_replay.py` stdout，而是直接加载 generated `runtime.py`、`verifier.py`、`seed_state.json`，覆盖 generated bundle 的 positive/negative records，并拒绝 forged success-only check；同时 `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 支持 bounded framework repair loop。Goal 12 已接入 request-driven environment generation pipeline：`raw_request` 为订票服务时发布 `booking-service-lite`；`raw_request` 为图书馆借阅管理时发布 `library-lending-lite`；两者都通过 planner/selector/source/codegen/verifier/release 路径，不能继续落回 `project-board-lite`。

边界仍然明确：这不是通用环境自动生成器。`support-desk-lite` 和 `project-board-lite` 都仍是 fixture/domain-specific node set；`booking-service-lite` 和 `library-lending-lite` 是 request-driven strategy probes，不证明任意领域自动生成。S3-S7 虽然从 `KnowledgePack` 派生，但 synthesis 逻辑仍由领域策略提供。`project-board-lite` deterministic bundle 仍是模板输出；independent verifier 目前覆盖已注册 generated bundle 策略，不等于通用 verifier synthesis。`openai_codegen` 是真实 OpenAI-compatible file-content codegen 通道，但默认测试使用本地 fake endpoint 验证协议；`code_agent_runner` 已证明外部 agent 命令可以接收 workspace packet、写文件、跑 check、产出 manifest，但默认测试使用本地 runner fixture，未默认调用 live Codex/Claude/mini-swe-agent。外部模型或 live runner smoke 需要显式配置 base URL、API key、model、command、allowlist 和 network/auth permission。bounded repair loop 由框架控制 attempt/failure packet/backend reinvocation，不表示 agent 可以控制 pipeline 流程。`project-board-lite` 的 CLI help 是 source evidence，不等于已实现 project-board environment CLI runtime。当前如果调用 `project_board_lite_node_registry()` 并传入“订票服务” raw request，仍会发布 `project-board-lite`；Goal 12 修正的是 `request_driven_node_registry()` / `run_request_driven_pipeline()` 入口，而不是让手动 registry 神奇变成 request-driven。Goal 02-04 的 full chain、online runtime、environment CLI、HTTP wrapper 和旧 `awm` CLI 仍作为回归保留，不代表真实 trainer、通用/网络 search、通用 synthesis、全 surface 发布或任意 shell executor 已完成。部署环境、verl/GRPO 在线采样、SFT 数据生产、以及根据训练结果反向迭代环境，都是后续动态 consumer/feedback loops；当前文档不能把这些写成已完成核心能力。

## 下一 Goal

当前 staged Goal 文档包括：

- [docs/goal-02-hardcoded-full-chain.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-02-hardcoded-full-chain.zh.md)：基于硬编码 `support-desk-lite` 打通 release package -> rollout/eval -> reward records -> training export -> dataset-only trainer consumer。
- [docs/goal-03-online-runtime-grpo.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-03-online-runtime-grpo.zh.md)：基于同一 fixture 补齐 online runtime contract 和 GRPO/verl metadata-only adapter。
- [docs/goal-04-environment-cli-surface-correction.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-04-environment-cli-surface-correction.zh.md)：区分 runtime control CLI 与真正的 environment CLI surface，并用 allowlisted argv template + `subprocess.run(shell=False)` 跑通 support-desk-lite CLI 工具面。
- [docs/goal-05-open-pipeline-structure.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-05-open-pipeline-structure.zh.md)：停止继续堆 fixture runtime，打开真实生成流水线结构，拆分 pipeline orchestration、节点接口、artifact store、source-grounded synthesis 和 agent-backed implementation 插槽。
- [docs/goal-06-second-source-family.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-06-second-source-family.zh.md)：引入第二个本地 source family，例如 CLI help + schema/examples，验证同一套 pipeline/node/source-grounded 结构可以复用。
- [docs/goal-07-generated-environment-bundle.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-07-generated-environment-bundle.zh.md)：让 implementation 节点从 source-grounded artifacts 写出 isolated generated environment bundle，并从生成文件构造环境、运行 verifier、通过 build/check/replay 后再 release。
- [docs/goal-08-agent-backed-environment-codegen.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-08-agent-backed-environment-codegen.zh.md)：让 code agent 通过可插拔 `AgentBackend` 在 isolated workdir 内生成 environment bundle 文件，并在 build/check/replay verified 后才进入 release。
- [docs/goal-09-real-code-agent-runner.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-09-real-code-agent-runner.zh.md)：区分 LLM/file-content codegen 与真正 code agent runner，让外部 runner 接收 workspace packet、写 `generated/`、运行 check、输出 manifest 和命令日志。
- [docs/goal-10-packaged-generated-runtime-consumer.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-10-packaged-generated-runtime-consumer.zh.md)：把 verified generated bundle 复制进 `envpkg/runtime/generated/<bundle_id>/`，并提供 package-relative runtime index 和 consumer check。
- [docs/goal-11-independent-verifier-bounded-repair.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-11-independent-verifier-bounded-repair.zh.md)：为 generated bundle 增加框架侧 independent verifier，并在 agent implementation 失败时执行 bounded repair loop。
- [docs/goal-12-request-driven-generation-pipeline.zh.md](/home/kelongzx/pycodes/loop_agent/agent-world-model/docs/goal-12-request-driven-generation-pipeline.zh.md)：实现 request-driven environment generation pipeline；订票服务和图书馆借阅管理是当前验收探针，必须通过 planner/selector/source/codegen/verifier/release 路径分别发布 `booking-service-lite` 和 `library-lending-lite`。

Goal 02-04 都仍然不是通用环境自动生成。Goal 05 的重点是结构收敛；Goal 06 的重点是复用验证；Goal 07 的重点是代码生成门槛；Goal 08 的重点是 file-content agent-backed codegen；Goal 09 的重点是真正 runner 形态；Goal 10 的重点是让 generated runtime 进入稳定 package；Goal 11 的重点是 release gate 独立验证和有界修复反馈；Goal 12 的重点是 request-driven generation pipeline。当前已有的 `booking-service-lite` 和 `library-lending-lite` 只是验收探针，用来证明 raw request 能驱动领域选择、source/codegen/verifier/release，而不是继续发布 `project-board-lite` 或靠手动第三 registry 绕过流水线。下一步应继续把 planner、source planning/discovery、codegen strategy、independent verifier strategy 和 bounded repair 泛化；运行中仍必须无人参与，不能等待人工选择 registry/source/strategy/verifier/repair；每一步必须消费上游 artifact refs、写出下游 artifact lineage，失败必须变成 failure packet 进入受控 retry/repair edge，达到上限写 terminal failed/blocked artifact。
