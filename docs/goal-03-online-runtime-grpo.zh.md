# Goal 03: Online Runtime 与 GRPO Adapter 骨架

本文定义第三条 Goal 模式任务。它不替代 `docs/agent-world-environment-generation.zh.md` 的长期目标；它是在 Goal 02 已经打通 release package -> rollout/eval -> reward records -> training export 后，补齐在线强化学习需要的环境运行时接口。

## 1. 任务定位

Goal 02 的训练消费链路主要是离线的：

```text
release package
  -> scripted rollout
  -> deterministic verifier reward
  -> SFT/eval records
  -> DatasetOnlyAdapter
```

这可以证明环境包能被执行、验证和导出数据，但不能直接支撑 GRPO/PPO 这类在线强化学习。GRPO/PPO 训练需要 trainer 在 rollout 阶段调用当前 policy 生成 action，再和环境交互，获得 observation、done、reward，然后计算 advantage 并更新 actor。

Goal 03 的目标是证明：

```text
一个已发布的环境包
  -> 可以暴露 online runtime contract
  -> 可以被外部 trainer 按 reset/step/finalize/verify 调用
  -> 可以记录在线 step trace 和 verifier reward
  -> 可以给 GRPO/verl 类 adapter 提供桥接接口
```

本 Goal 仍然基于硬编码 `support-desk-lite`，不是通用环境自动生成器。

### 1.1 纠偏说明

Goal 03 的 online runtime、HTTP runtime wrapper，以及后续出现的 `agent_world.cli_runtime` 只能证明 release package 可以被外部 harness/trainer 控制：

```text
health / reset / observe / step / finalize
```

这类接口是 runtime control surface，不等于用户要求的 environment CLI surface。

用户要求的 environment CLI surface 是真实环境工具通过命令行暴露，例如：

```text
lark doc create ...
gh issue create ...
kubectl apply ...
```

这种 CLI 必须从 CLI help/docs/examples 或受控探针中发现，固化成 logical tool 的 argv template、input schema、output parser、allowed exit codes 和 verifier evidence。该纠偏任务见 `docs/goal-04-environment-cli-surface-correction.zh.md`。

## 2. 核心边界

环境生成系统发布的是环境包和 runtime contract，不是训练框架本身。

verl、verl-agent、LLaMA-Factory、OpenRLHF、TRL 或自定义 GRPO trainer 都只是 consumer。它们可以有 adapter，但不能成为 core dependency。

第一版可以实现：

- Python callable runtime。
- OnlineEnvRuntime / OnlineEnvSession protocol。
- support-desk-lite 的 reset/step/finalize/verifier bridge。
- GRPO/verl adapter skeleton 或 config/export bridge。
- deterministic tests。

第一版不实现：

- 真实 GPU 训练。
- 真实 verl 依赖安装。
- vLLM/SGLang/Ray worker 集成。
- 真实 MCP/CLI/HTTP surface 实现。
- 通用环境自动发现或通用代码生成。

## 3. Online Runtime Contract

新增一个环境运行时抽象。建议命名：

```text
agent_world.online_runtime
```

核心对象：

```python
class OnlineEnvRuntime:
    def start(self) -> None: ...
    def close(self) -> None: ...
    def reset(self, task_id: str, *, run_id: str | None = None) -> OnlineEnvSession: ...

class OnlineEnvSession:
    def observe(self) -> RuntimeObservation: ...
    def step(self, action: RuntimeAction) -> RuntimeStepResult: ...
    def finalize(self, answer: str | None = None) -> RuntimeFinalResult: ...
```

第一版可以不用严格照抄以上代码，但语义必须清楚：

- `start`: 准备 surface runtime，例如 import Python module、启动服务或检查 CLI。
- `reset`: 为某个 task 创建隔离状态，不能污染其他 task 或其他 run。
- `observe`: 返回当前可给 agent 的 observation，不泄漏 verifier/schema/backend 内部名。
- `step`: 执行一个 tool/action，返回 observation、tool result、done、error 和 trace ref。
- `finalize`: 运行 deterministic verifier，返回 reward、success、verifier checks 和 final trace。
- `close`: 清理进程、临时目录、连接或端口。

### 3.1 RuntimeAction

建议字段：

- `action_id`
- `kind`: `tool_call`, `final_answer`, `noop`
- `tool_name`: surface exposure name，不是内部 verifier 名。
- `arguments`
- `raw_model_output`
- `metadata`

第一版可以让测试直接构造 `RuntimeAction(kind="tool_call")`，不要求实现完整模型输出 parser。

### 3.2 RuntimeObservation

建议字段：

- `task_id`
- `natural_request`
- `messages` 或 `observation_text`
- `available_tools`
- `last_tool_result`
- `error`
- `done`
- `trace_ref`

Observation 不能泄漏：

- database field 内部名。
- verifier id。
- dependency path。
- backend id。
- seed fixture 路径。

### 3.3 RuntimeStepResult

建议字段：

- `task_id`
- `step_index`
- `action`
- `observation`
- `tool_result`
- `done`
- `error`
- `trace_ref`
- `state_snapshot_hash`

### 3.4 RuntimeFinalResult

建议字段：

- `task_id`
- `run_id`
- `success`
- `reward`
- `reward_source`: 必须是 `deterministic_verifier`
- `verifier_result`
- `surface_trace_ref`
- `step_trace_ref`
- `initial_snapshot_hash`
- `final_snapshot_hash`
- `failure_class`
- `recovery_suggestion`

reward 第一版可以仍然是：

```text
success=true  -> 1.0
success=false -> 0.0
```

但 reward 必须来自 verifier，不能来自 LLM 自评。

## 4. Surface Launcher Contract

Online runtime 不应假设环境一定是 Python。release package 需要描述 surface 如何启动和调用。

建议新增：

```text
release/runtime-index.yaml
release/surface-runtime-index.yaml
```

第一版只需要实现 Python surface，其他 surface 只定义 descriptor，不要求可执行。

### 4.1 Python Surface

必须包含：

- `kind: python_callable`
- `surface_class`
- `seed_function`
- `reset_function`
- `verifier_function`
- `tool_bindings`
- `health_check`: import check + callable existence check

当前 `support-desk-lite` 使用 Python surface：

- `agent_world.fixtures.support_desk_lite.SupportDeskLite`
- `agent_world.fixtures.support_desk_lite.create_seed_db`
- `agent_world.fixtures.support_desk_lite.reset_environment`
- `agent_world.fixtures.support_desk_lite.verify_task_completion`

### 4.2 MCP Surface Descriptor

只定义 contract，不实现真实 MCP server。

必须能表达：

- `kind: mcp_server`
- `launch_command`
- `transport`: `stdio`, `http`, `sse` 等。
- `host`
- `port`
- `health_check`
- `list_tools_check`
- `tool_schema_ref`
- `shutdown_policy`

MCP surface 的核心是可启动服务，而不是把所有环境都变成 MCP。

### 4.3 CLI Surface Descriptor

只定义 contract，不实现真实 CLI surface。

必须能表达：

- `kind: cli`
- `mode`: `one_shot`, `json_stdin_stdout`, `daemon`
- `launch_command`
- `health_check_command`
- `reset_command`
- `step_command`
- `finalize_command`
- `timeout_ms`
- `working_dir_policy`

在线 RL 不适合每一步都启动重进程。若 CLI surface 面向 GRPO，优先选择 `json_stdin_stdout` 或 `daemon` 模式。不能把 generic shell command executor 当环境 CLI surface。

### 4.4 HTTP Surface Descriptor

只定义 contract，不实现真实 HTTP service。

必须能表达：

- `kind: http_service`
- `launch_command`
- `base_url`
- `health_endpoint`
- `reset_endpoint`
- `step_endpoint`
- `finalize_endpoint`
- `verify_endpoint`
- `auth_policy`
- `timeout_ms`

## 5. Online Rollout Records

Goal 03 需要区分 Goal 02 的 scripted rollout 和在线交互 rollout。

建议新增：

```text
online_rollouts/<run_id>/step-records.jsonl
online_rollouts/<run_id>/final-records.jsonl
checks/online-step-records.jsonl
checks/online-final-records.jsonl
```

每个 step record 至少包含：

- `environment_id`
- `release_id`
- `task_id`
- `run_id`
- `session_id`
- `step_index`
- `action_kind`
- `tool_name`
- `argument_keys`
- `observation_ref`
- `tool_result_preview`
- `state_snapshot_hash`
- `trace_ref`
- `error`

每个 final record 至少包含：

- `environment_id`
- `release_id`
- `task_id`
- `run_id`
- `session_id`
- `success`
- `reward`
- `reward_source`
- `verifier_result`
- `initial_snapshot_hash`
- `final_snapshot_hash`
- `surface_trace_ref`
- `step_trace_ref`
- `failure_class`
- `recovery_suggestion`

记录中不得包含 secret。路径应优先使用 package-relative ref。

## 6. GRPO / verl Adapter 骨架

新增 trainer adapter 只做桥接，不引入真实 verl 依赖。

建议命名：

```text
agent_world.adapters.grpo
agent_world.adapters.verl
```

第一版可以只实现：

- `GrpoAdapterConfig`
- `VerlAdapterExport`
- `build_prompt_dataset(package_dir)`
- `build_reward_bridge_config(package_dir)`
- `consume_runtime_contract(package_dir)`

输出可以写入：

```text
training/grpo-adapter-index.yaml
training/verl-adapter-config.yaml
```

adapter 需要表达：

- prompt dataset 如何从 task set 生成。
- rollout 阶段如何创建 `OnlineEnvRuntime`。
- model action 如何映射为 `RuntimeAction`。
- verifier reward 如何映射为 trainer reward。
- trace/reward 如何回写为 records。

不要求第一版真的 import `verl`。如果将来接 `verl-agent`，可以在 optional adapter 中实现它需要的 custom tool / BaseTool / tools_config_file，而不是把这些类写进核心。

## 7. Package Integration

release package 需要新增引用：

```text
release/runtime-index.yaml
release/surface-runtime-index.yaml
training/grpo-adapter-index.yaml
checks/online-step-records.jsonl
checks/online-final-records.jsonl
```

`ReleaseManifest.consumer_outputs` 或 `ConsumerIndex` 应能让外部 trainer 找到：

- task records。
- surface runtime descriptor。
- reset/step/finalize contract。
- verifier function/ref。
- reward record schema。
- online rollout trace schema。
- adapter config refs。

## 8. 验收标准

完成后应能运行：

```bash
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -p no:cacheprovider
```

并能通过 Python API 证明：

```text
generate support-desk-lite package
  -> load OnlineEnvRuntime from package
  -> reset task-1
  -> execute tool_call steps through runtime.step
  -> finalize
  -> deterministic verifier reward
  -> write online step/final records
  -> export GRPO/verl adapter metadata
```

至少验证：

- `OnlineEnvRuntime` 可以从 release package 加载。
- 每个 task 都能创建隔离 session。
- 正确 action 序列可以得到 `success=true` 和 `reward=1.0`。
- 错误 action 或缺失 action 可以得到 `success=false` 或明确 verifier failure。
- step/final records 落盘且可校验。
- package manifest 引用 runtime/adapters/online records。
- `DatasetOnlyAdapter` 和 Goal 02 full-chain 不被破坏。
- 旧 `awm` CLI 行为不被破坏。

## 9. 当前仍然不做

本 Goal 不做：

- 真实 GRPO/PPO 训练。
- 真实 verl、verl-agent、Ray、vLLM、SGLang 依赖。
- 真实 MCP server 实现。
- 真实 CLI daemon 实现。
- 真实 HTTP service 实现。
- 通用 action parser。
- 通用环境自动生成。
- LLM reward。
- 把 trainer 逻辑写进环境生成 core。

## 10. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、docs/agent-world-environment-generation.zh.md、docs/goal-02-hardcoded-full-chain.zh.md、docs/goal-03-online-runtime-grpo.zh.md。

目标：基于当前 support-desk-lite release package，补齐在线强化学习需要的 OnlineEnvRuntime、SurfaceLauncher descriptor、在线 step/final records，以及 GRPO/verl adapter 骨架。

不要把本任务误解成真实 verl 训练或通用环境自动生成。不要引入 verl/Ray/vLLM/SGLang 作为 core dependency。不要实现真实 MCP/CLI/HTTP surface；第一版只要求 Python surface 可执行，其他 surface 只定义 descriptor。reward 必须来自 deterministic verifier，不能来自 LLM 自评。

实现要求：
1. 新增 OnlineEnvRuntime / OnlineEnvSession contract，支持 start/reset/observe/step/finalize/close。
2. 基于 support-desk-lite package 实现 Python callable runtime。
3. 新增 runtime/surface descriptor records，并写入 release package。
4. 新增 online step/final records，记录 action、observation、trace、snapshot、verifier reward。
5. 新增 GRPO/verl adapter skeleton，能导出 prompt dataset 和 reward/runtime bridge metadata，但不依赖真实 verl。
6. 保持 Goal 02 rollout/reward/training export 可用。
7. 所有新增内容必须有 deterministic tests。
8. 保持旧 awm CLI 行为不破坏。

验收：
- `uv run pytest` 全部通过。
- 一个完整在线 runtime 测试能从 package reset task、step 调用工具、finalize 并得到 deterministic verifier reward。
- 正确路径 reward=1.0；错误路径有明确 failure_class/recovery_suggestion。
- package manifest 能定位 runtime descriptor、online records 和 GRPO/verl adapter metadata。
```
