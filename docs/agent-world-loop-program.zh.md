# Agent World Loop Engineering Program

## 1. 总目标

本项目要做的是一个可维护、可扩展、可观测、可验证的 Agent World Runtime。

它不是单纯环境生成器，也不是一开始就接 RL 训练框架。它的核心是用 loop engineering 的方式，把 agent-world 工作固化成可执行闭环：

```text
scenario -> task -> env build -> env check -> task check -> release
  -> rollout -> trace -> verify -> reward -> feedback -> train/export/evolve
```

这条链路本身就是 loop。区别在于：不要让 LLM 在上下文里临场维持流程，而是让 LLM 生成或修改 workflow spec，再由代码执行 workflow，由 verifier 判断是否通过。

## 2. 设计原则

### 2.1 Code-first loop

LLM 可以生成 workflow、诊断失败、提出修复建议，但稳定流程必须落到代码、YAML、JSON schema 或显式 DAG。

### 2.2 Artifact-first runtime

每一步都必须产生可检查 artifact。没有 artifact，就没有可观测性、可回放性和训练数据。

### 2.3 Verifier-first reward

优先使用确定性 verifier：数据库状态、文件状态、命令退出码、单元测试、schema validation。LLM judge 只能作为辅助。

### 2.4 Runner-agnostic thin harness

Codex SDK、mini-swe-agent、deep search、MCP agent、CLI 脚本都只是 runner。训练数据和 trace 不能绑定某个 runner。

harness 不应该被实现成新的完整 agent 框架。第一阶段只需要最薄的一层控制缝合：

- 复用 AWM 已经有的环境管理、MCP 接口、agent demo 和 verifier。
- 在 workflow 节点需要智能执行时，再调用 Codex SDK、mini-swe-agent 或 deep-search runner。
- 所有 runner 只提交 action/result/evidence，不拥有 reward、release、training export 的最终决策。

### 2.5 Reuse before rebuild

不要为了抽象而重写 AWM 已经做好的部分。优先顺序是：

1. 直接导入 AWM 1K 数据样本和现有 CLI 输出。
2. 包装 AWM CLI/MCP/verifier 为 workflow node。
3. 只补 AWM 不负责的 artifact registry、trace/event package、dataset export 和 review gate。
4. 某个节点确实需要 agent 能力时，再接 Codex SDK、mini-swe-agent 或 deep-search。

### 2.6 TDD before pipeline

每个模块先写验收测试或 dry-run check，再实现。没有通过最小测试之前，不进入流水线化和训练化。

### 2.7 Reading gate before key nodes

关键节点不要只凭上下文记忆推进。进入 contracts、workflow、rollout、verification、evolution 这些节点前，负责实现或 review 的 agent 必须重新阅读：

- `docs/loop-engineering.md`
- `research/notes/agent-world-survey.zh.md`
- `research/notes/agent-world-timeline.zh.md`
- `research/papers/2602.10090.pdf`，即 Agent World Model
- `research/papers/2604.18292.pdf`，即 Agent-World

如果 PDF 阅读成本过高，至少先读本地综述和 timeline，再按需打开论文原文核对 AWM 的环境生成/验证设计，以及 Agent-World 的 environment-task discovery 和 self-evolving training arena。

## 3. 目标目录布局

第一版建议新增 `awmx/`，不直接改现有 `awm/`，避免破坏 AWM 原始 CLI。

注意：下面是可扩展目标布局，不代表第一阶段要实现所有文件。第一阶段只实现 AWM/scripted 最小闭环；`codex_sdk.py`、`mini_swe.py`、`deep_search` 相关文件先以 contract/fake backend 或 TODO 形式存在，只有 workflow 节点确实需要 agent 时才实现真实后端。

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
    trace.py
    logging.py
    permissions.py
    review.py
  rollout/
    base.py
    scripted.py
    mini_swe.py
    codex_sdk.py
  verification/
    base.py
    rewards.py
  training/
    export.py
  cli.py
```

配置和运行产物分开：

```text
configs/
  agent_world/
    base.yaml
    workflows/
      vertical_slice.yaml
    runners/
      scripted.yaml
      mini_swe.yaml
      codex_sdk.yaml
    adapters/
      cli.yaml
      mcp.yaml
    verifiers/
      deterministic.yaml

outputs/
  agent_world/
    registry/
      environments/
      tasks/
      verifiers/
    runs/
      <run_id>/
        run.yaml
        events.jsonl
        trace.jsonl
        reward.json
        review.json
        logs/
        artifacts/
    datasets/
      sft/
      rl/
      preference/
```

约定：

- `configs/` 放人可审查的稳定配置。
- `outputs/agent_world/registry/` 放已发布/可复用 artifact。
- `outputs/agent_world/runs/<run_id>/` 放每次执行的完整 episode package。
- `trace.jsonl` 记录 agent/action/observation。
- `events.jsonl` 记录 workflow 节点状态、check、retry、错误分类。
- `logs/` 放 stdout、stderr、LLM 调用摘要、adapter 日志。
- `reward.json` 是训练和演化消费的最终信号。

### 3.1 Thin Harness 和 Agent Backend 的边界

`harness/` 是薄控制面，不是完整 agent 系统。它负责把 workflow 节点变成可控、可观测、可验证的一次调用，但不重写 AWM 已有的环境、MCP、agent demo 或 verifier：

- `context.py`: 组装 task、environment、tool spec、历史轨迹、预算和安全约束。
- `agent_call.py`: 暴露统一的 `agent(task_prompt, verification_prompt=None, runner=...)` 和 `assert(prompt, evidence, runner=...)` 调用点。
- `permissions.py`: 命令、路径、网络、MCP tool、API、模型和 token 预算的准入控制。
- `trace.py` / `logging.py`: 把 prompt、action、observation、stdout/stderr、文件变化、错误分类写入 run package。
- `gates.py`: schema、dependency、permission、budget、verifier、review gate。
- `review.py`: 独立只读复核，不允许在 review 阶段直接修代码。

`rollout/` 和 `adapters/` 才连接具体后端。scripted、mini-swe-agent、Codex SDK、AWM MCP、deep search、CLI 工具都必须实现同一 runner contract。训练数据、trace、reward 只依赖 artifact/trace protocol，不依赖某个 agent scaffold。

判断某个后端是否应该接入的标准很简单：workflow 节点是否真的需要它。如果 AWM CLI/MCP/verifier 已经能完成该节点，就先复用 AWM。

### 3.2 mini-swe-agent 的使用位置

mini-swe-agent 适合作为某些软件工程或 CLI-heavy 节点的 agent runner，而不是替代 harness，也不是第一阶段最小闭环的必要条件。原因是它默认 action surface 很小：bash action、线性 history、每步独立执行命令，这便于采样和审计。

第一版只做薄包装：

```text
MiniSweRunner.run(RunSpec, HarnessContext) -> RunnerResult + Trace
```

硬约束：

- mini-swe-agent 产生的每个 command 必须先经过 `harness.permissions`。
- command 的 stdout、stderr、exit code、duration、cwd、env、截断摘要和原始日志路径必须进入 `trace.jsonl`。
- mini-swe-agent 不能直接写 reward，reward 只能由 verifier 生成。
- mini-swe-agent 的内部 history 只能作为 trace evidence，不能替代 `events.jsonl`。
- 先用 fake backend 做 contract/TDD；只有 workflow 节点需要真实 agent 采样时，再接真实 mini-swe-agent。

### 3.3 Codex SDK 的使用位置

Codex SDK 适合复杂 repo engineering、调试、测试修复、独立 review，以及 workflow 中明确需要 agent 判断的节点。它不是必选主路径，不能因为可用就把普通确定性节点改成 agent 节点。

建议调用点：

```text
agent(task_prompt, verification_prompt=None, runner="codex_sdk")
assert(prompt, evidence, runner="codex_sdk")
```

硬约束：

- Codex SDK 后端只能通过 harness 提供的 workspace、tool policy、预算和验收 prompt 执行。
- 任何文件修改、测试命令、失败诊断和最终结论都必须写入 trace/event/review artifact。
- Codex SDK 可以做 reviewer，但 reviewer goal 必须只读，且输出 pass/fail 和具体文件引用。

### 3.4 AWM 的使用位置

AWM 的核心价值是提供 code + DB backed environment、MCP interface、数据库状态 verifier 和已有 1K 环境数据。第一阶段主路径应该优先围绕 AWM，而不是先设计一套完整替代 runtime：

- 从 AWM JSONL 导入 `ScenarioSpec`、`TaskSpec`、`EnvironmentSpec`、`ToolSpec`、`VerifierSpec`。
- 用 AWM CLI/MCP 启动和检查环境。
- 用 AWM verifier 或纯代码 verifier 生成 reward。
- MCP 是 adapter，不是唯一运行时；CLI 和 Python adapter 也必须保留。

本地已经保存 AWM 数据集小样本到 `research/data/awm_1k_samples/`，用于 importer 和 verifier 的 TDD fixture。完整数据集来源是 `Snowflake/AgentWorldModel-1K`，总量约 520MB；没有明确需要时不要整包下载到仓库。

### 3.5 最小不可绕过协议

这不是要实现一个庞大的 harness，而是防止后端各自为政。第一版只需要守住下面的最小协议：

- `workflow/` 只负责 DAG、依赖、重试、预算和 gate，不直接调用 shell、MCP、SDK、HTTP 或 verifier。
- `rollout/` 负责 runner 生命周期、turn loop、终止条件和把 runner 输出转换成 canonical action/observation。
- `adapters/` 负责具体执行 CLI、MCP、Python、HTTP 或 AWM 命令；adapter 不决定 reward、release 或 training export。
- `verification/` 负责 verifier 执行和 reward mapping；runner final answer 不能直接成为 reward。
- `harness/` 只提供 context、permission、trace、event、review/replay 的薄控制缝合。

核心规则：

```text
runner proposes action
  -> permission/gate records decision
  -> adapter executes authorized action
  -> trace/event records evidence
  -> verifier scores
  -> exporter consumes trace + reward
```

任何 backend 如果不能进入这条链，就不能进入训练数据。

## 4. 并行推进方式

可以并行，但不是无约束并行。正确方式是先冻结最小 contract，然后多个 worktree 按 contract 并行实现。

### 4.0 启动前准备

从仓库根目录启动 Codex，确保能加载本项目的 `AGENTS.md`、`.codex/config.toml` 和 `.codex/agents/`：

```bash
cd /home/kelongzx/pycodes/loop_agent/agent-world-model
codex
```

如果执行环境的默认 `uv` cache 或 Python 安装目录不可写，先设置到可写目录：

```bash
export UV_CACHE_DIR=/tmp/uv-cache
export UV_PYTHON_INSTALL_DIR=/tmp/uv-python
```

如果需要做轻量 LLM smoke test，使用 OpenAI-compatible 环境变量。不要把 API key 写进仓库文件：

```bash
export OPENAI_BASE_URL="https://blog.r78xoaxrk.nyat.app:50903/v1"
export OPENAI_API_KEY="<set locally>"
export AWMX_SMOKE_MODEL="gpt-5.4-mini"
export AWMX_CODE_MODEL="gpt-5.3-codex"
```

约定：

- 普通连通性、judge mock、短文本诊断优先用 `gpt-5.4-mini`。
- 代码向 agent 节点 smoke test 可用 `gpt-5.3-codex`。
- 第一阶段默认仍不调用真实外部模型；只有明确需要 smoke test 时才使用这些变量。

本机当前可用校验命令示例：

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --no-sync --no-managed-python --python 3.14 python -c "import json, pathlib; [json.loads(line) for path in pathlib.Path('research/data/awm_1k_samples').glob('*.jsonl') for line in path.read_text().splitlines()]"
```

第一条消息不要直接要求写代码，先让 Codex 复述目标和读取来源：

```text
Read AGENTS.md, docs/agent-world-loop-program.zh.md, docs/goals.zh.md, docs/loop-engineering.md, research/notes/agent-world-survey.zh.md, and research/notes/agent-world-timeline.zh.md. Then summarize the implementation objective, the first acceptance gate, and what must not be done yet.
```

确认总结正确后，再启动主目标。

### 4.1 主干 goal

主线程只做 orchestration：

```text
/goal Coordinate the Agent World Loop Engineering Program in docs/agent-world-loop-program.zh.md. Maintain the artifact contracts, spawn or review branch goals, and only merge branches that pass their acceptance criteria and independent review.
```

### 4.2 Worktree 分支

建议分支：

| 分支 | 目标 | 依赖 | 是否可并行 |
| --- | --- | --- | --- |
| `awmx-contracts` | schema、配置布局、run artifact contract | 无 | 必须先完成或最先冻结 |
| `awmx-foundation` | registry、logging、trace writer、config loader | `awmx-contracts` | 可并行 |
| `awmx-workflow` | workflow spec、DAG runner、dry-run、node status | `awmx-contracts` | 可并行 |
| `awmx-rollout` | runner interface、scripted runner、trace/reward export | `awmx-contracts` | 可并行 |
| `awmx-adapters-cli` | CLI adapter、timeout、cwd、env、stdout/stderr capture | `awmx-foundation` | 可并行 |
| `awmx-review` | 独立 review、验收复核、风险清单 | 任意实现分支 | 每个分支完成后运行 |

### 4.3 工作树命令

需要实际开始分支时再运行：

```bash
git worktree add ../agent-world-model-contracts -b awmx-contracts
git worktree add ../agent-world-model-foundation -b awmx-foundation
git worktree add ../agent-world-model-workflow -b awmx-workflow
git worktree add ../agent-world-model-rollout -b awmx-rollout
```

注意：并行写代码时，不让多个分支同时修改同一个核心文件。公共 contract 变更必须先回到 `awmx-contracts`。

## 5. TDD 和验收标准

### Step 0: 合约冻结

交付：

- `awmx/artifacts/schemas.py`
- `configs/agent_world/base.yaml`
- `configs/agent_world/workflows/vertical_slice.yaml`
- `docs/agent-world-loop-program.zh.md`

TDD：

- 写 schema validation 测试。
- 写 sample config 加载测试。

验收：

- `uv run pytest tests/awmx/test_schemas.py`
- `uv run python -m awmx.cli validate-config configs/agent_world/base.yaml`
- 所有 artifact 都有 `id`、`version`、`created_at`、`source`、`metadata`。

独立 review：

- reviewer 只读检查 schema 是否能支持 env、task、run、trace、reward。
- reviewer 必须确认没有把 runner 细节写死进 artifact schema。

### Step 1: Foundation

交付：

- config loader
- artifact registry
- run directory creator
- trace/event logger

TDD：

- registry 写入和读取 roundtrip。
- run 目录创建。
- events/trace JSONL append。

验收：

- `uv run pytest tests/awmx/test_registry.py tests/awmx/test_trace.py`
- dry run 后出现：

```text
outputs/agent_world/runs/<run_id>/run.yaml
outputs/agent_world/runs/<run_id>/events.jsonl
outputs/agent_world/runs/<run_id>/trace.jsonl
outputs/agent_world/runs/<run_id>/logs/
```

独立 review：

- reviewer 检查 run artifact 是否足以审计一次 episode。

### Step 2: Workflow

交付：

- workflow YAML schema
- DAG runner
- node state machine
- dry-run mode

TDD：

- DAG 拓扑排序测试。
- 缺依赖、循环依赖、未知节点类型的失败测试。
- dry-run 不执行外部副作用，但记录计划。

验收：

- `uv run pytest tests/awmx/test_workflow.py`
- `uv run python -m awmx.cli workflow-dry-run configs/agent_world/workflows/vertical_slice.yaml`
- dry-run 的 `events.jsonl` 包含每个节点的 `planned`、`skipped` 或 `blocked` 状态。

独立 review：

- reviewer 确认 workflow 控制流由代码执行，不依赖 LLM 临场记忆。

### Step 3: Rollout And Verification

交付：

- runner interface
- scripted baseline runner
- AWM CLI/MCP runner 或 AWM run importer
- mini-swe-agent runner wrapper contract, fake backend only
- Codex SDK runner wrapper contract, fake backend only
- deterministic verifier interface
- reward exporter

TDD：

- scripted runner 固定输入输出测试。
- fake mini-swe-agent backend 输出 command/history，测试 trace mapping 和 permission gate。
- fake Codex SDK backend 输出 file edits/test results/review result，测试 artifact mapping。
- AWM path 使用本地样本或 fixture，不依赖真实 LLM API。
- verifier success/failure 测试。
- reward record schema 测试。

验收：

- `uv run pytest tests/awmx/test_rollout.py tests/awmx/test_rewards.py`
- 一个 demo task 能产生：

```text
trace.jsonl
reward.json
datasets/rl/*.jsonl
```

独立 review：

- reviewer 检查 reward 是否来自 verifier，而不是 runner 自评。
- reviewer 检查任何 agent backend 都不能绕过 `harness.permissions`、`trace.jsonl`、`events.jsonl` 和 verifier gate。
- reviewer 检查真实 mini-swe-agent/Codex SDK 没有被作为第一阶段硬依赖。

### Step 4: CLI Adapter

交付：

- CLI adapter spec
- command allowlist
- timeout / cwd / env control
- stdout/stderr capture

TDD：

- allowlist 拦截未授权命令。
- timeout 触发失败事件。
- stdout/stderr 被截断但原始日志落盘。

验收：

- `uv run pytest tests/awmx/test_cli_adapter.py`
- CLI 调用必须记录 command、cwd、exit_code、duration、stdout_path、stderr_path。

独立 review：

- reviewer 检查没有裸奔 shell 执行，没有无边界网络或危险命令。

### Step 5: AWM Integration

交付：

- AWM CLI adapter
- existing AWM output importer
- env check node
- task check node

TDD：

- 用 fixture 模拟 AWM output。
- 优先使用 `research/data/awm_1k_samples/` 里的 AWM JSONL 样本做 importer fixture。
- importer 必须按 `scenario` 和 `task_idx` join，不允许假设多个 JSONL 的行号完全对齐。
- importer 不依赖真实 LLM API。
- check node 能处理成功、失败、缺文件三种情况。

验收：

- `uv run pytest tests/awmx/test_awm_adapter.py`
- 至少一个现有 AWM artifact 被导入 registry。

独立 review：

- reviewer 确认没有破坏现有 `awm gen`、`awm env`、`awm agent`、`awm verify` 行为。

### Step 6: First End-to-End Slice

交付：

- `vertical_slice.yaml`
- 一个 demo environment/task/verifier
- 一个 scripted rollout
- 一个 reward export

验收：

- `uv run pytest`
- `uv run python -m awmx.cli run configs/agent_world/workflows/vertical_slice.yaml`
- 运行结束后必须存在：

```text
outputs/agent_world/runs/<run_id>/events.jsonl
outputs/agent_world/runs/<run_id>/trace.jsonl
outputs/agent_world/runs/<run_id>/reward.json
outputs/agent_world/datasets/rl/<dataset_id>.jsonl
```

独立 review：

- 使用 `awmx-reviewer` 子代理或独立 Codex goal 只读 review。
- review 必须给出 pass/fail。
- fail 时必须回到具体分支修复，不允许在 review 分支直接修。

## 6. Goal 拆分

### Goal A: Contracts

```text
/goal Implement the contracts slice in docs/agent-world-loop-program.zh.md. First reread docs/loop-engineering.md, research/notes/agent-world-survey.zh.md, and research/notes/agent-world-timeline.zh.md. Create schema/config tests first, then implement only the artifact schemas, config loader contract, and sample vertical_slice.yaml. Stop when validation tests pass and an independent review can understand all artifacts.
```

### Goal B: Foundation

```text
/goal Implement the foundation slice in docs/agent-world-loop-program.zh.md using the frozen contracts. Create tests first for registry, run directories, event logging, and trace logging. Stop when a dry run creates a complete observable run package under outputs/agent_world/runs/<run_id>/.
```

### Goal C: Workflow

```text
/goal Implement the workflow slice in docs/agent-world-loop-program.zh.md. First reread docs/loop-engineering.md and the AWM/Agent-World notes under research/notes. Create tests first for workflow schema validation, DAG ordering, blocked nodes, cycle detection, and dry-run event logging. Stop when vertical_slice.yaml can dry-run without side effects.
```

### Goal D: Rollout

```text
/goal Implement the rollout and verification slice in docs/agent-world-loop-program.zh.md. First reread the AWM verifier sections through research/notes and the local AWM paper if needed. Create tests first for scripted runner, deterministic verifier, reward record, and dataset export. Stop when one demo task produces trace.jsonl, reward.json, and an RL JSONL export.
```

如果要同时设计 mini-swe-agent 和 Codex SDK 后端 contract，使用这个更严格的 goal。注意只做 fake backend，不调用真实外部模型：

```text
/goal Implement the rollout and verification slice in docs/agent-world-loop-program.zh.md. Use uv for all Python commands. Make the first runnable path scripted or AWM-backed. First write tests with fake scripted, fake mini-swe-agent, and fake Codex SDK backends. Prove every backend goes through permissions, trace.jsonl, events.jsonl, verifier reward, and dataset export. Do not call real external models or make real mini-swe/Codex SDK integration mandatory yet. Stop when one demo task produces trace.jsonl, reward.json, and an RL JSONL export.
```

### Goal E: Independent Review

```text
/goal Review the completed implementation branch against docs/agent-world-loop-program.zh.md. Before reviewing, reread docs/loop-engineering.md and research/notes/agent-world-survey.zh.md. Do not modify files. Check TDD coverage, artifact layout, observability, verifier correctness, replay evidence, and whether existing AWM behavior is preserved. Return pass/fail with concrete file references.
```

## 7. Subagent Strategy

建议项目级 subagents：

- `awmx-architect`: 用 `gpt-5.5`，负责合约、边界、架构 review。
- `awmx-implementer`: 用 `gpt-5.4`，负责实现单个 slice。
- `awmx-test-engineer`: 用 `gpt-5.4-mini`，负责快速测试缺口和 fixture 设计。
- `awmx-reviewer`: 用 `gpt-5.5`，只读独立验收。

并行使用方式：

```text
Spawn awmx-architect to review the artifact contracts, awmx-test-engineer to propose tests, and awmx-implementer to implement only after tests are written. Wait for all agents and summarize conflicts before editing shared contracts.
```

写代码分支不应该互相并行改同一份 contract。review agent 必须只读。

## 8. 是否现在就训练

暂时不接 verl。正确顺序是：

```text
trace/reward 稳定 -> dataset export 稳定 -> offline eval 稳定 -> 再接训练
```

训练可以有两种节奏：

- batch mode：先生成 N 个环境和 episode，再训练。
- continual mode：每生成少量环境就采样、训练、诊断、扩展。

第一版采用 batch-lite：

```text
1-3 environments -> 10-30 episodes -> verifier reward -> export dataset -> 手动检查 -> 再训练
```

等 verifier 和 trace 稳定后，再考虑 continual evolution。
