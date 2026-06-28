# Goal 04: 纠偏并实现 Environment CLI Surface

本文定义第四条 Goal 模式任务。它是一次概念纠偏任务：当前已实现的 `agent_world.cli_runtime` 是 runtime control CLI，不是用户要求的 environment CLI surface。

## 1. 当前已完成内容审视

当前 `agent_world/` 已经有这些可保留能力：

- S0-S11 artifact workflow。
- artifact validators、deterministic gates、ReviewRecord、AgentInvocationRecord。
- support-desk-lite Python callable fixture。
- deterministic replay/verifier。
- Goal 02 的 rollout/eval、reward records、training export、DatasetOnly/Noop trainer consumer。
- Goal 03 的 OnlineEnvRuntime、OnlineEnvSession、online step/final records、GRPO/verl metadata-only adapter。
- HTTP runtime wrapper：通过 HTTP 控制 runtime 的 health/reset/observe/step/finalize。
- CLI runtime wrapper：通过命令行控制 runtime 的 health/reset/observe/step/finalize。

这些内容不应简单删除。它们是 harness/trainer 侧控制环境的能力。

但当前偏移点是：

```text
agent_world.cli_runtime
  = runtime control CLI
  != environment CLI surface
```

它不能代表用户真正要求的 CLI 环境。

## 2. 用户当前真正目标

用户要的是一个 Agent-World-like 环境生成系统。环境发布后，agent/trainer 可以通过不同真实 surface 操作环境：

- Python callable。
- HTTP API。
- MCP server。
- Environment CLI。

这里的 Environment CLI 指环境工具本身就是命令行程序，例如：

```text
lark doc create ...
lark doc update ...
gh issue create ...
kubectl apply ...
aws s3 cp ...
```

它不是：

```text
agent_world.cli_runtime reset
agent_world.cli_runtime step
agent_world.cli_runtime finalize
```

后者只是 runtime control/harness entrypoint。

## 3. 必须区分的三类 CLI

### 3.1 Environment CLI Surface

这是本 Goal 要实现的重点。

语义：

```text
logical tool
  -> environment_cli descriptor
  -> argv template
  -> subprocess.run(argv, shell=False)
  -> stdout/stderr/exit_code observation
  -> verifier reward
```

示例：

```text
RuntimeAction(create_doc, {"title": "...", "content": "..."})
  -> ["lark", "doc", "create", "--title", "...", "--content", "..."]
```

### 3.2 Runtime Control CLI

当前 `agent_world.cli_runtime` 属于这一类。

语义：

```text
health / reset / observe / step / finalize
```

它可以保留，但必须重新标注为 `runtime_control_cli`，不能冒充 environment CLI surface。

### 3.3 Agent Backend CLI

例如 Codex CLI、search CLI、mini-swe-agent CLI。

语义：

```text
workflow node uses an external agent process for search/extract/review/implement
```

它属于 `AgentBackend` / `AgentInvocationRecord` 范畴，不是环境 surface。

## 4. 新的 package descriptor 要求

`release/surface-runtime-index.yaml` 必须区分：

```yaml
descriptors:
  - kind: python_callable
    status: implemented

  - kind: http_service
    status: implemented_or_deferred

  - kind: runtime_control_cli
    status: implemented
    purpose: harness_control
    commands: [health, reset, observe, step, finalize]

  - kind: environment_cli
    status: implemented
    purpose: agent_tool_surface
    discovery:
      help_command: [...]
      schema_ref: spec/surfaces.yaml
    tool_command_templates:
      - logical_tool_id: search_tickets
        tool_name: search_tickets
        argv_template: [...]
        input_schema: {...}
        output_parser: json_stdout
        allowed_exit_codes: [0]
        timeout_ms: 1000
        state_scope: session
```

不允许把 `kind: cli` 同时承担 runtime control 和 environment tool surface 两种语义。

## 5. 第一版实现范围

第一版不接真实飞书/lark，也不需要网络认证。先用 support-desk-lite 做一个真实 CLI fixture，证明模型动作可以通过真实 subprocess CLI 命令改变环境状态。

建议新增：

```text
agent_world/fixtures/support_desk_lite_cli.py
```

命令示例：

```bash
uv run python -m agent_world.fixtures.support_desk_lite_cli \
  --db <session-db> search-tickets --status open --customer-tier vip --keyword refund

uv run python -m agent_world.fixtures.support_desk_lite_cli \
  --db <session-db> get-ticket --ticket-id T-100

uv run python -m agent_world.fixtures.support_desk_lite_cli \
  --db <session-db> add-ticket-note --ticket-id T-100 --visibility internal --body "..."
```

这些命令是真正的 environment CLI tool surface，因为它们直接代表环境工具，而不是调用 `agent_world.cli_runtime step`。

## 6. Online Runtime 需要支持 CLI Surface

`OnlineEnvRuntime.step(RuntimeAction)` 应能选择 surface。

第一版可以通过 action metadata 或 runtime 参数指定：

```python
RuntimeAction(
    kind="tool_call",
    tool_name="add_ticket_note",
    arguments={...},
    metadata={"surface": "environment_cli"},
)
```

执行路径：

```text
RuntimeAction
  -> lookup environment_cli tool template
  -> render argv using session db/state refs
  -> reject unsafe argv
  -> subprocess.run(argv, shell=False, timeout=...)
  -> parse JSON stdout
  -> capture stderr/exit_code
  -> write OnlineStepRecord with command evidence
```

如果 metadata 未指定，当前 Python callable surface 可以继续作为默认 surface，避免破坏 Goal 03。

## 7. 安全边界

Environment CLI 不能退化成 generic shell executor。

禁止：

- `shell=True`
- `bash -c`
- `sh -c`
- 管道 `|`
- 重定向 `>` / `<`
- `&&` / `||` / `;`
- 未声明 executable。
- 未声明子命令。
- 任意用户拼接 argv。

允许：

- package descriptor 中声明的 executable。
- package descriptor 中声明的 argv template。
- schema validation 后填充的参数。
- 固定 timeout。
- stdout/stderr preview 进入 records。

## 8. Records 要求

使用 environment CLI surface 执行的 step record 必须包含：

- `surface_kind: environment_cli`
- `command_descriptor_ref`
- `command_template_id`
- `rendered_argv`
- `exit_code`
- `stdout_preview`
- `stderr_preview`
- `parsed_output_preview`
- `state_snapshot_hash`
- `trace_ref`
- `error`

不能包含：

- secret。
- absolute db path。
- 未脱敏 token。
- shell command string。

## 9. 测试要求

新增 deterministic tests，至少覆盖：

- environment_cli descriptor 与 runtime_control_cli descriptor 被区分。
- `support_desk_lite_cli --help` 或等价 help/discovery 能运行。
- task-1 通过 environment_cli surface 成功：

```text
search-tickets -> get-ticket -> add-ticket-note -> finalize -> reward=1.0
```

- 错误 CLI action 得到 verifier failure，reward=0.0。
- 未声明 tool 被拒绝。
- shell metacharacter / bash -c / pipe / redirect 被拒绝。
- online step records 包含 CLI command evidence。
- 当前 `agent_world.cli_runtime` 仍可作为 runtime_control_cli 使用，但不再被当作 environment CLI surface。
- Goal 02 full-chain、Goal 03 online runtime、HTTP runtime、旧 `awm` CLI 不破坏。

## 10. 不做

本 Goal 不做：

- 真实飞书/lark 接入。
- 真实网络认证。
- 真实 MCP server。
- 通用 shell。
- 真实 verl/Ray/vLLM/SGLang 训练。
- 通用 CLI discovery agent。

后续可以在 Source Discovery 中读取真实 CLI docs/help，并由 agent backend 辅助抽取 command templates。

## 11. 给 Goal 模式的建议 Prompt

```text
阅读 AGENTS.md、docs/agent-world-environment-generation.zh.md、docs/goal-03-online-runtime-grpo.zh.md、docs/goal-04-environment-cli-surface-correction.zh.md。

目标：纠正当前 CLI 概念偏移。已有 agent_world.cli_runtime 是 runtime_control_cli，只能作为 harness/debug/control entrypoint，不能代表 environment CLI surface。本 Goal 要实现真正的 Environment CLI Surface：环境工具本身通过 CLI 命令暴露，类似 lark doc create、gh issue create、kubectl apply 这种工具接口。

不要实现 generic bash executor。不要允许任意 shell、bash -c、管道、重定向或未声明命令。environment_cli surface 必须通过 package descriptor 中声明的 allowlisted argv templates 调用。模型/adapter 可以输出 RuntimeAction(tool_name,args)，runtime 根据 descriptor 渲染成 argv 并执行 subprocess.run(argv, shell=False)。

实现要求：
1. 保留 agent_world.cli_runtime，但重新标注为 runtime_control_cli，不再把它当作 environment cli surface。
2. surface-runtime-index 中区分 runtime_control_cli 和 environment_cli。
3. 新增 support-desk-lite environment CLI fixture，例如 agent_world.fixtures.support_desk_lite_cli。
4. environment_cli descriptor 必须包含 discovery/help、allowed tool names、argv_template、input schema、output parser、allowed exit codes、timeout 和 state scope。
5. OnlineEnvRuntime.step(RuntimeAction) 支持选择 environment_cli surface 执行。
6. CLI step record 必须记录 rendered argv、exit_code、stdout/stderr preview、descriptor ref、snapshot hash 和 trace ref。
7. 用 environment_cli surface 跑通 task-1 成功路径，finalize 后 reward=1.0。
8. 用 environment_cli surface 跑一个失败路径，finalize 后 reward=0.0，并有 deterministic verifier failure。
9. 测试必须证明未声明 tool、shell metacharacter、bash -c、pipe、redirect 被拒绝。
10. 保持 Python runtime、runtime_control_cli、HTTP runtime、Goal02 full-chain、Goal03 online runtime、旧 awm CLI 不破坏。

验收：
- `uv run pytest` 全部通过。
- 可以通过 Python API 或测试明确选择 environment_cli surface 执行 RuntimeAction。
- support-desk-lite task-1 经真实 subprocess CLI command 完成，reward=1.0。
- surface-runtime-index 中 environment_cli 为 implemented，runtime_control_cli 单独标注。
- agent_world.cli_runtime 不再被误解为环境工具 CLI surface。
```
