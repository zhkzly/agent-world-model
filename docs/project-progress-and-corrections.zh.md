# Project Progress And Corrections

本文是项目推进过程中的事实记录和偏差记录。它用于减少后续 Goal 误解，不替代 `docs/agent-world-environment-generation.zh.md`。

维护规则：

- 每次 Goal 完成后更新当前真实性等级、已完成内容、剩余风险和下一步。
- 记录理解错误时要写清楚“错在哪里”和“如何纠正”，不要只写结果。
- 不把计划、愿望或 prompt 当成已实现功能。
- 如果使用 subagent/independent reviewer，结论应追加到本文或对应 Goal 文档，并保留 review 证据引用。

## 当前任务

本项目要做的是类似 Agent-World / AW 的环境生成系统，而不是 AWM 论文复现。

目标输入可以是环境需求、模型能力缺口、领域 seed、PRD、repo、MCP server、CLI、API/SDK docs、数据库 schema 或其他资料。目标输出是可复现、可验证、可发布、可被训练/评估消费的可执行环境包。

这里的“环境”应理解为后端/runtime 代码包：状态转移逻辑、工具 surface、seed/state fixture、任务、verifier、check/replay、release metadata 和后续 consumer 入口。项目目标不是让 agent 每次临场照 prompt 写一遍流程，而是把 source discovery、任务构造、code-agent implementation、验证、repair、package/release 固化成 loop-engineering workflow。LLM/Codex 等 agent 负责显式节点上的搜索、抽取、代码实现、review 或 repair；框架代码负责状态、gate、记录、retry budget 和 release 决策。

当前最重要的缺口已经从“request-driven 只是两条领域探针”转为“通用 request-driven 生成路径已经跑通，但仍不是任意领域高质量自动生成”。`run_request_driven_pipeline()` 现在从任意非空 `raw_request` 生成 `DomainPlan`、`StrategySelection`、source evidence、`KnowledgePack`、`EnvironmentSpec`、`LogicalToolGraph`、`TaskSet`、`VerifierPlan` 和 `ImplementationRequest`；环境 ID、工具、任务和 replay cases 从请求/source artifact 派生，不再靠 booking/library/project-board 等领域分支。IMPLEMENT 阶段强制走 `AgentBackend`，由 agent 在 isolated workdir 写 `runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`，框架再执行 manifest/path/hash/security check、generated self-check、generic framework independent verifier、bounded repair 和 package/release。Goal 10 的 package-relative runtime index 与 Goal 11 的 failure packet / repair loop 仍保留；当前新增的是通用 replay contract 输入和通用 contract-driven independent verifier。

项目默认使用 `uv` 管理 Python 环境和执行验证命令。后续文档、smoke 和测试说明应优先写成 `uv run ...`，除非是在 generated bundle 内描述由 package check 实际执行的命令。

## 已纠正的偏差

### 1. AWM 复现偏差

早期理解曾偏向 AWM-first 或 `awmx` demo，容易把 AWM JSONL、AWM MCP 或论文复现当成系统边界。

纠正：

- AWM 只作为背景知识和可选 source。
- 当前任务源以 `docs/agent-world-environment-generation.zh.md` 为准。
- 旧 `awm` CLI 保留兼容，但不能主导新框架结构。

### 2. CLI 概念偏差

早期把 CLI 理解成 runtime control CLI，例如 `health/reset/observe/step/finalize`，而用户实际要的是环境工具本身通过命令行暴露，例如 `lark doc create`、`gh issue create`、`kubectl apply`。

纠正：

- `runtime_control_cli` 与 `environment_cli` 已在文档和 descriptor 中拆开。
- environment CLI 必须映射 logical tool，使用 allowlisted argv template 和 `subprocess.run(argv, shell=False)`。
- generic shell executor 不能冒充 environment CLI。

### 3. 训练/rollout 先行风险

Goal 02-04 提前补了 rollout、reward export、training export、online runtime、GRPO metadata、HTTP wrapper 和 fixture CLI。这些对下游 consumer 有价值，但容易让人误判“环境生成已经完成”。

纠正：

- 训练框架是 consumer，不是 core dependency。
- support-desk-lite full chain 只是 fixture 回归。
- 后续 Goal 优先补环境生成主线，尤其是 source-grounded synthesis 和 implementation/codegen。

### 4. 硬编码流水线风险

早期 S1-S7 很多 artifact 由常量或领域 fixture 直接构造，无法证明真实 source discovery / extraction / synthesis。

纠正：

- Goal 05 引入 `PipelineRunner`、`NodeRegistry`、`ArtifactStore`、local source connector、source-grounded `KnowledgePack` 和 implementation/code-agent slot。
- Goal 06 引入第二个本地 source family：`project-board-lite` 的 CLI help、schema 和 examples。
- 当前仍不是通用 synthesis；只是把硬编码边界暴露成可替换 node。

### 5. “生成环境代码”真实性不足

Goal 07 已经写出 isolated `GeneratedEnvironmentBundle`，包含 runtime、seed、verifier、surface descriptor、check/replay 和 build manifest，并从 generated files 执行验证。

Goal 08 已纠正的部分：

- `project-board-lite` 新增 agent-backed implementation path。
- code agent 通过 `AgentBackend` 调用，生成 `AgentInvocationRecord`，并只被允许写 isolated workdir。
- process backend 可以在该 workdir 写出 `runtime.py`、`seed_state.json`、`verifier.py`、`surface_descriptor.json`、`check_replay.py`、`build_manifest.yaml`，但这只是本地 adapter/wiring 测试。
- `openai_codegen` backend 调用 OpenAI-compatible chat-completions endpoint，要求模型返回 `files[]` 的 path/content，由 backend 写入 isolated workdir、计算 hash，并交给同一 build/check/replay gate。
- 进入 bundle 前执行 path/hash/security checks，拒绝 malformed output、绝对路径、`..`、symlink escape、未声明文件、hash mismatch、fixture runtime import 和 check failure。
- 通过 build/check/replay 后才生成 `ReleaseManifest`；成功任务 verifier pass，负例 verifier fail。

仍有问题：

- `project-board-lite` 的 source extraction、S3-S7 synthesis 和 generated behavior 仍是领域节点与测试 fixture 支撑，不是通用 synthesis。
- mock/process backend 证明 agent-backed wiring 与安全边界；不等于真实 codegen。`openai_codegen` 是真实 OpenAI-compatible codegen 通道，但默认测试使用本地 fake endpoint；外部模型 live smoke 仍需显式配置和权限。
- Codex SDK/CLI、mini-swe-agent、Claude Agent SDK、OpenAI-compatible structured generation 仍只能作为 adapter，不能成为 core dependency。

### 6. LLM 与 code agent runner 混淆

用户进一步指出：LLM 可以作为判断、打分、抽取、review 节点，但复杂代码实现、搜索、运行检查和修复更应交给通用 agent；这些 agent 可以通过 skills 和提示词封装，可能是 search agent、code agent 或 review agent。

纠正：

- Goal 09 新增 `code_agent_runner` 和 `codex_cli_runner` backend kind。
- pipeline 在 runner 模式下写出 `input/` workspace packet：artifact JSON、implementation brief、acceptance checks 和 codegen skill。
- runner 必须在隔离 workspace 内写 `generated/`，运行 check，并把 manifest/command log 写入 `agent-output/`。
- 框架只把 `generated/` 作为候选 bundle 验证；`input/` 和 `agent-output/` 不进入 release。
- `AgentInvocationRecord.trace_ref` 使用稳定 `agent-workspace://...` 引用，绝对临时路径只留在本地 workspace，不写成 artifact ref。

仍有问题：

- 默认测试 runner 是本地 fixture，用来证明 runner contract，不代表 live Codex/Claude/mini-swe-agent 已默认执行。
- Goal 11 已补上框架级 bounded repair loop；runner 仍可以内部自修复，但框架现在会在 agent candidate 失败后写 failure packet，并在 repair budget 内重新调用同一个 backend。
- runner contract 和 independent verifier 仍绑定 `project-board-lite` 的 generated bundle checker，后续要提炼成通用 bundle check strategy。

### 7. Generated runtime 只在临时 workdir 可用

真实 Codex runner 成功后，用户追问“是否可以被之后的环节调用”。当时的问题是：release artifact 已引用 generated bundle，但实际 runtime 仍位于 `/tmp/.../agent-runs/.../generated`，后续模块没有 package 内稳定入口。

纠正：

- Goal 10 新增 `agent_world.generated_bundle`。
- `PipelineRunner` 成功完成 S11 后会自动写 `output_dir/envpkg`。
- accepted generated files 被复制到 `envpkg/runtime/generated/<bundle_id>/`，并保持 sha256 校验。
- `envpkg/release/generated-runtime-index.yaml` 描述 runtime dir、entrypoints、files、check/replay command 和 consumer contract。
- `run_packaged_generated_bundle_check(package_dir)` 可作为 downstream smoke consumer，从 package 内执行 generated runtime。

仍有问题：

- 这只是 package-relative runtime/check consumer，还不是通用 rollout/online adapter。
- support-desk 的 Goal 02-04 rollout/training consumer 仍未泛化到所有 generated environments。
- 真正给 verl/GRPO 使用，还需要在线 session/action/reward adapter。

### 8. Generated check 自报过度可信与无框架修复循环

Goal 07-10 的 generated bundle gate 会执行 generated `check_replay.py`，但旧实现仍把 stdout JSON success 当成主要放行证据。agent-backed implementation 失败后也只会停止，不会构造 failure packet 并由框架重新调用 code agent。

纠正：

- Goal 11 新增 `agent_world.independent_verifier`。
- `check_project_board_generated_bundle()` 与 package-level `run_packaged_generated_bundle_check()` 现在要求 generated check 和 independent verifier 同时通过。
- independent verifier 直接从 generated bundle/package 加载 `runtime.py`、`verifier.py`、`seed_state.json`，检查 import、seed load、entrypoints、runtime tool methods、`check_replay.py` 结构 sanity。
- 对 `ReleaseManifest` / `TaskSet` 中的 `pb-task-1`、`pb-task-2`、`pb-task-3` 分别生成 positive/negative task records；release 声明的 task 未覆盖或 unsupported 会阻止 release。
- 伪造只打印 success JSON 的 `check_replay.py` 会被拒绝，不能进入 S10/S11。
- `PipelineRunConfig.max_repair_attempts` 与 `AGENT_WORLD_MAX_REPAIR_ATTEMPTS` 控制框架级 bounded repair loop。
- 每次 agent implementation attempt 都记录 `AgentInvocationRecord`、candidate paths/file hashes、check/replay records；失败 attempt 生成 failure packet，包含 failure class、failed task/verifier、command、exit code、stdout/stderr preview、manifest/path/hash/check failure 与 recovery suggestion。
- repair attempt 使用同一个 `AgentBackend`，并把 previous attempt 和 failure packet 作为 instruction/workspace input；达到上限仍失败时停止，不生成 `ReleaseManifest`。

仍有问题：

- independent verifier 目前是 `project-board-lite` generated bundle 的框架侧 verifier，不是通用 verifier synthesis。
- bounded repair loop 只负责 implementation node 的受控反馈，不负责 source discovery、task synthesis 或 trainer/rollout 修复。
- 默认测试仍使用 fake/model fixture 或本地 runner fixture；live Codex/Claude/mini-swe-agent 仍需显式配置和权限。

### 9. raw_request 不能真正驱动通用生成

该偏差已在当前 Trellis task 中进一步纠正。上一版 Goal 12 虽然让 raw request 不再落回 `project-board-lite`，但仍通过 booking/library 领域词表、source packet、task IDs、replay cases 和 independent verifier 分支完成，不能算“全自动生成”。

纠正：

- `agent_world.request_driven` 已重写为通用 artifact pipeline：`DomainPlan.domain_seed`、operation IDs、state entities、TaskSet 和 replay cases 从 raw request/source evidence 派生，不包含 booking/library/project-board/support-desk 领域常量。
- `run_request_driven_pipeline()` 会把 request-driven run 强制切到 `implementation_mode="agent"`；deterministic path 只会返回 `agent_backend_required`，不会偷偷用模板产出 release。
- `pipeline._run_agent_implementation_attempt()` 只在存在 `DomainPlan` / `StrategySelection` 的 request-driven run 中调用通用 agent candidate handler；旧 support/project fixture 的 agent mode 保持原兼容行为。
- `input/framework-replay-contract.json` 和 `agent_world.replay_contract` 不再按 environment_id 查硬编码 replay case，而是读取 `TaskSet.framework_replay.tool_calls`，缺省时从 `dependency_path` 派生。
- `agent_world.independent_verifier` 增加 generic contract verifier：直接加载 generated runtime/verifier/seed，按 accepted tasks 的 replay contract 执行工具调用，检查 trace 顺序、state/answer evidence，并用正反例约束 verifier；旧 fixture 专用 verifier 只作为历史回归路径保留。
- Goal 12 测试改为任意 incident/runbook raw request，mock code agent 从 artifact JSON 写候选 bundle，框架完成 package/release；伪造 `check_replay.py`、坏 verifier、repair 成功、repair 耗尽和 traceback observation 都被覆盖。
- 手动 `project_board_lite_node_registry()` 加任意 raw request 仍会发布 `project-board-lite`，测试明确证明这不是 request-driven success。

### 10. 环境包与训练反馈边界

新的澄清：环境生成的核心交付不是规格草案，而是可执行后端/runtime 代码包。`GeneratedEnvironmentBundle` 必须包含 runtime、seed、verifier、surface descriptor、check/replay 和 build manifest，并通过 generated check 与框架侧 independent verifier 后才能进入 release/package。Code agent 写代码、运行检查和修复失败都必须在 `AgentBackend` / `AgentInvocationRecord` / bounded repair loop 下发生，不能让 agent 自己控制是否发布。

训练、部署、verl/GRPO 在线采样、SFT 数据生产，以及根据训练结果反向生成更多环境或修正环境，是后续动态流程。当前已有 Goal 02-04 的 dataset-only/export/online runtime metadata 和 support-desk fixture consumer，但还没有通用 rollout/online adapter，也没有真实训练框架集成。后续可以把训练反馈作为新的显式 loop 或 upstream retry edge 接入，但当前不能把它写成已完成能力。

### 11. 真实 Codex CLI runner 实跑结果

用户进一步澄清：这里需要的不是 unit test，而是由 Codex 代替人实际启动一次真实 code agent 执行，使用当前环境中的 base URL、API key、model 等配置，监控从 request-driven pipeline 到 code agent、repair、independent verifier 的真实结果。

已纠正：

- `codex_cli_runner` 现在会为子进程创建隔离 `CODEX_HOME`，把 base URL/model 写入该 workspace 内的 `config.toml`，并只通过 `CODEX_API_KEY` 给子进程传 API key；secret value 不写入 artifacts。
- code-agent workspace packet 现在明确写出 manifest kind 表、runtime entrypoint、constructor、trace JSONL、verifier kwargs、framework replay expectations 和 candidate manifest path 规则。
- failure packet 现在给 runner 提供相对 candidate paths、manifest contract、failed task ids、failed task stderr preview 和 failed prerequisite checks，避免把绝对 `/tmp` workdir 路径误当成 manifest path。
- candidate validator 忽略 `__pycache__/*.pyc` 这类 Python bytecode cache，但仍拒绝真正的 undeclared generated files。

真实监控结论：

- 多次 live `codex_cli_runner` run 均成功启动真实 Codex CLI，读取 `input/` packet，写 `generated/` 六个文件，并产生 `agent-output/candidate_manifest.json` 与 command log。
- pipeline 走过 request/domain planner、strategy selector、S0-S9，并进入 implementation/repair gate。
- 这些 live run 均未进入 S10/S11 release。最终失败仍是 `independent_generated_bundle_verification_failed`；manifest 已合规，剩余问题是 agent 生成的 runtime/verifier 行为没有满足当时框架侧 replay。
- 因此当前只能声称“真实 Codex CLI runner path 已接入、可监控、会被 framework gate 拦截错误产物”，不能声称“live Codex 默认能稳定生成并发布任意 request-driven 环境”。

下一步如果继续推进 live runner 质量，应优先做两件事：把 independent verifier replay contract 抽成更机器可读的 `input/framework-replay-contract.json`，并提供一个 runner 可本地执行的 framework-owned preflight command，而不是让 agent 只靠自然语言 brief 推断 replay shape。

### 12. 可执行 verifier feedback workflow

用户进一步强调：环境生成不是一次代码生成调用，而是多层 workflow。外层是 S0-S11 的 request/source/spec/task/surface/verifier/package/release workflow；中层是 code-agent implementation 和 bounded repair workflow；内层是 framework-owned executable verifier/check observation workflow。代码必须经过执行，失败必须形成可喂回 agent 的 observation，最终 release 权仍属于框架。

当前已补齐的机制：

- code-agent runner workspace 现在写入 `input/framework-replay-contract.json`。该文件由已接受 artifacts 和 verifier strategy knowledge 生成，包含 runtime entrypoint、constructor、helpers、required methods、verifier kwargs、trace contract、manifest kind mapping 和 replay cases。
- 新增 framework-owned candidate check API / module：`agent_world.candidate_check.check_generated_candidate()`，可对 generated candidate import/execute independent verifier，并返回 JSON-compatible `framework_check_observation`。
- independent verifier report 增加 `framework_check_observation`，包含 schema version、environment_id、failed_task_ids、prerequisite/task observations、expected/actual evidence、exception type/message/traceback。
- bounded repair packet 现在携带 `framework_check_observation`，并继续保留相对 candidate paths/hashes 和 manifest contract，便于下一轮 Codex/code-agent 把它当作 tool-call observation 修复 generated bundle。
- generated `check_replay.py` 仍只是辅助证据；伪造 success stdout 仍会被 framework independent verifier 拒绝。

这不表示已经完成高质量通用 verifier synthesis，也不表示 live Codex 默认能稳定发布任意 request-driven 环境。它表示 implementation 阶段从“自然语言 brief + 失败摘要”推进为“机器可读 replay contract + 框架执行检查 + 结构化失败 observation + bounded repair”的多层 workflow。

## 当前真实性等级

截至当前 Trellis task：

- `support-desk-lite`: runnable fixture，支持 Python callable、deterministic verifier、release package、replay、rollout/export consumer、online runtime、runtime control CLI、environment CLI 和 HTTP wrapper 回归。
- `project-board-lite`: 第二 source family，使用本地 CLI help、schema、examples 生成 source-grounded artifacts；deterministic generated bundle 和 agent-backed generated bundle 都必须同时通过 generated check 与 framework independent verifier，覆盖 `pb-task-1`、`pb-task-2`、`pb-task-3` 的正反 records；成功 S11 后复制到 `envpkg/runtime/generated/<bundle_id>/` 供后续模块按 package-relative index 调用。
- agent backend: 已有 backend-neutral contract、invocation record、mock/manual/process/codex-like slot、真实 `openai_codegen` backend，以及 `code_agent_runner` / `codex_cli_runner` runner path；`openai_codegen` 从模型响应写文件，`code_agent_runner` 使用固定 allowlisted argv 和 `subprocess.run(argv, shell=False)` 调用外部 agent 命令，workspace packet、manifest、command log、trace ref 都可审计，secret 只记录 env var/ref；implementation 失败时框架可按 bounded repair loop 生成 failure packet 并重新调用同一 backend。真实 `codex_cli_runner` 已实跑并可监控，但 live runner 质量仍取决于模型/提示和 replay contract，不是默认稳定发布能力。
- training: 只有 dataset-only/export/metadata consumer，不是 verl/LLaMA-Factory/OpenRLHF/TRL 真实训练集成。
- request-driven generation pipeline: 已从两条领域探针改为通用 artifact path。任意非空 raw request 会产生 request-derived environment id、source evidence、knowledge pack、tools、tasks、surface plan、verifier plan、machine-readable replay contract、agent-generated bundle、generic framework independent verifier records、bounded repair 和 package release。测试使用 incident/runbook 请求证明不再依赖 booking/library/project-board/support-desk 常量。该能力仍只能证明“通用结构和执行闭环跑通”，不等于任意领域语义都高质量，也不等于真实网络 discovery 或 live code agent 默认稳定成功。
- environment package: 当前 generated environment 已能以 package-relative runtime index 被加载检查；这证明后续模块可以调用 packaged generated backend/runtime，但不等于已实现部署、policy rollout、SFT/GRPO 采样或训练反馈闭环。

当前不能声称：

- 已经实现通用环境自动生成。
- 已经实现真实网络 search/discovery。
- 已经实现通用 verifier synthesis。
- 已经实现通用 code-agent 环境生成质量保证。
- 已经能从任意 raw_request 动态生成对应新领域。
- 已经默认跑通 live Codex/Claude/mini-swe-agent。
- live Codex CLI runner 已能稳定通过任意 request-driven environment 的 independent verifier 并发布 release。
- 已经实现通用 rollout/online runtime adapter 读取任意 generated bundle。
- 已经实现 MCP/HTTP/CLI/Python 全 surface 通用发布。
- 已经接入真实 RL trainer。
- 已经实现根据训练结果自动迭代环境生成。

## 下一优先级

下一 Goal 应优先提升通用 request-driven path 的语义质量，而不是再新增手动领域 registry：

- 把当前 raw-request-only source discovery 扩展为可配置 source planning：本地 PRD/schema/CLI/API docs/repo/MCP/API docs 优先，默认不做 live crawler。
- 把通用 extraction/synthesis 从简单请求词派生升级为 source-grounded schema/task/verifier synthesis，保持 artifacts 和 replay contract 机器可读。
- 增强 `ImplementationRequest` 和 `framework-replay-contract.json`，让 live code agent 更容易写出满足 contract 的 runtime/verifier。
- 继续保留 bounded repair loop、AgentBackend、isolated workdir、安全检查、build/check/replay gate 和 generic independent verifier。
- 基于 `envpkg/release/generated-runtime-index.yaml` 实现通用 rollout/online adapter：读取 TaskSet，加载 runtime/verifier entrypoints，执行外部 policy action，产出 rollout/reward records。
- 在通用 rollout/online adapter 稳定后，再设计训练结果反馈到 source/task/verifier/environment generation 的外层 loop。
- 继续让外部模型/live runner smoke 默认 skip；显式配置时可以用 `AGENT_WORLD_AGENT_BACKEND=openai_codegen` 做最小真实 file-content codegen 检查，或用 `AGENT_WORLD_AGENT_BACKEND=code_agent_runner` / `codex_cli_runner` 做真实 runner 检查。

## 需要持续警惕的问题

- 不要继续堆 runtime/training consumer 来替代 generator 能力。
- 不要把 deterministic template 输出称为 agent codegen。
- 不要把 process-agent test helper 输出称为真实 codegen；真实 file-content codegen 要来自 `openai_codegen` 或等价外部模型返回的 file contents；真实 code agent runner 要由外部 agent 命令/SDK 接收 workspace packet、写文件并跑检查。
- 不要把 process agent / Codex CLI / mini-swe-agent 的命令行调用混同为 environment CLI surface。
- 不要把 API key、base URL credential、auth token 写进 artifact 或 trace 明文。
- 不要让 live backend 成为默认测试依赖。
- 不要新增手动领域 registry 来绕过 request-driven pipeline；后续新领域必须继续通过 planner/selector/source/codegen/verifier/release path。
- 不要把训练、部署、采样或训练反馈闭环写成当前已完成能力；它们应作为 release package 的下游 consumer 或后续显式 loop。
- Python 验证命令默认用 `uv run ...`，不要在新文档里回退到裸 `pytest` 作为推荐入口。

## 后续 Review 记录模板

```text
日期：
Review 类型：human / llm_agent / static_check / peer_process
Review 范围：
结论：PASS / PASS WITH RISKS / FAIL
Blocking findings：
Non-blocking findings：
与任务源是否一致：
新增偏差：
需要更新的文档：
需要补的测试：
```
