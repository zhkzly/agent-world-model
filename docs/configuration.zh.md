# Agent World 配置系统

项目配置入口是 `agent_world.config.load_agent_world_config()`。

配置模型只有一个：`AgentWorldConfig`。它包含：

- `agent_profiles`：可复用的 agent/backend profile，例如 `semantic`、`implementation`。
- `stage_agent_profiles`：每个 pipeline stage 使用哪个 profile。
- `research`：source discovery provider 配置，例如 `local`、`jina`、`searxng`、`process`。
- `node_execution_mode`：节点执行模式，默认 `agent`。

## 默认行为

默认无需配置文件：

```bash
export AGENT_WORLD_OPENAI_API_KEY=...
```

默认语义节点使用：

- profile: `semantic`
- backend: `llm`
- base url: `https://blog.r78xoaxrk.nyat.app:50903/v1`
- model: `gpt-5.3-codex-spark`

默认 `IMPLEMENT` 使用 profile `implementation`。如果没有显式覆盖实现 profile，并且没有设置全局 `AGENT_WORLD_AGENT_BACKEND`，实现 backend 默认是 `codex_sdk`；如果设置了全局 backend，则 implementation 会继承该 backend。

`codex_sdk` 是 IMPLEMENT 的真实 code agent 路径：SDK 在隔离 workspace 中直接生成 `generated/` 和 `agent-output/candidate_manifest.json`。`llm_file_codegen` 只是低能力兼容适配器：它调用 OpenAI-compatible LLM 产出 `files[]` JSON，再由框架代写文件；它不是 Codex SDK，也不应作为默认实现路径。

## YAML 配置

可以通过 `AGENT_WORLD_CONFIG` 指向 YAML：

```yaml
agent_profiles:
  semantic:
    backend_kind: llm
    base_url: https://blog.r78xoaxrk.nyat.app:50903/v1
    model: gpt-5.3-codex-spark
    api_key_env: AGENT_WORLD_OPENAI_API_KEY

  implementation:
    inherits: semantic
    backend_kind: codex_sdk
    model: gpt-5.3-codex-spark
    code_repair_thread_mode: continue

stages:
  default_agent_profile: semantic
  agent_profiles:
    IMPLEMENT: implementation

research:
  backend: jina
  max_results: 5
```

配置文件只能写 secret 的环境变量名，例如 `api_key_env`，不能写真实 key、token 或 secret 值。

## Env 覆盖规则

Env 优先级高于 YAML。

全局语义 profile：

```bash
AGENT_WORLD_AGENT_BACKEND=llm
AGENT_WORLD_OPENAI_BASE_URL=https://...
AGENT_WORLD_OPENAI_MODEL=gpt-5.3-codex-spark
AGENT_WORLD_OPENAI_API_KEY=...
```

实现 profile 覆盖：

```bash
AGENT_WORLD_IMPLEMENT_AGENT_BACKEND=codex_sdk
AGENT_WORLD_IMPLEMENT_OPENAI_MODEL=gpt-5.4
AGENT_WORLD_IMPLEMENT_CODE_REPAIR_THREAD_MODE=continue
```

Research provider：

```bash
AGENT_WORLD_RESEARCH_BACKEND=jina
AGENT_WORLD_JINA_SEARCH_URL=https://s.jina.ai
AGENT_WORLD_JINA_READER_URL=https://r.jina.ai
```

Stage 绑定覆盖：

```bash
AGENT_WORLD_STAGE_IMPLEMENT_AGENT_PROFILE=implementation
AGENT_WORLD_STAGE_S1_AGENT_PROFILE=semantic
```

## Runtime Artifact

Pipeline 会把解析后的 profile 写成 `AgentBackendConfig` artifact，供 agent invocation record 和 gates 引用。IMPLEMENT 的 profile 也会被记录为 backend-config artifact，但它来自同一个 `AgentWorldConfig`，不是另一套独立配置系统。
