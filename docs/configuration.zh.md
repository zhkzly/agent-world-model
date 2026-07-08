# Agent World 配置系统

项目配置入口是 `agent_world.config.load_agent_world_config()`。

默认非 secret 配置放在：

```text
config/agent-world.default.yaml
```

用户平时只需要在 shell 里配置 secret 和机器相关值：

```bash
export OPENAI_API_KEY=...
export JINA_API_KEY=...
# 可选：覆盖 YAML 里的 OpenAI-compatible base URL
export OPENAI_BASE_URL=https://...
```

不要把真实 key 写入 YAML、artifact、trace、manifest 或 release 包。

## 配置模型

配置只有一套：`AgentWorldConfig`。

- `invocation_profiles`：可复用的 backend profile，例如 `semantic`、`implementation`。
- `stages`：需要调用外部 backend 的 pipeline stage 使用哪个 profile；deterministic stage 不配置 profile。
- `research`：source discovery provider 配置，例如 `jina`、`searxng`、`process`。

`semantic` 不是语义搜索，也不是一次固定调用。它是 PLAN、S0-S7 等非实现且需要模型/agent 调用阶段的默认 profile：这些阶段主要产出结构化 JSON artifact 或 source evidence。默认让它走 OpenAI-compatible `llm`，用 `gpt-5.4-mini`。

`implementation` 是 IMPLEMENT 阶段的 profile。默认走真实 `codex_sdk`，用 `gpt-5.4`，让 Codex SDK 在隔离 workspace 中生成 `generated/` 和 `agent-output/candidate_manifest.json`。

## 默认行为

默认使用 `config/agent-world.default.yaml`：

```yaml
invocation_profiles:
  semantic:
    backend_kind: llm
    provider: openai_compatible
    base_url: https://blog.r78xoaxrk.nyat.app:50903/v1
    model: gpt-5.4-mini
    api_key_env: OPENAI_API_KEY
    model_candidates:
      - gpt-5.4-mini
      - gpt-5.4
      - gpt-5.5
    network: true

  implementation:
    inherits: semantic
    backend_kind: codex_sdk
    provider: codex
    model: gpt-5.4

stages:
  default_invocation_profile: semantic
  invocation_profiles:
    IMPLEMENT: implementation

research:
  backend: jina
  jina_search_url: https://s.jina.ai
  jina_reader_url: https://r.jina.ai
  jina_api_key_env: JINA_API_KEY
```

如果要使用另一套非 secret 配置，只设置：

```bash
export AGENT_WORLD_CONFIG=/path/to/agent-world.yaml
```

## Jina

默认 source discovery 使用 Jina Search/Reader：

- `research.backend: jina`
- `research.jina_search_url: https://s.jina.ai`
- `research.jina_reader_url: https://r.jina.ai`
- `research.jina_api_key_env: JINA_API_KEY`

Jina Search 需要 API key。Reader 读取已知 URL 可能允许匿名，但 pipeline 的 search 阶段应配置 `JINA_API_KEY`。

## Env 边界

配置行为由 YAML 决定。环境变量只用于：

- `OPENAI_API_KEY`：OpenAI-compatible/Codex SDK 鉴权。
- `OPENAI_BASE_URL`：本机临时覆盖 OpenAI-compatible base URL。
- `JINA_API_KEY`：Jina Search/Reader 鉴权。
- `AGENT_WORLD_CONFIG`：选择另一份 YAML。

历史 backend/model/stage/research 环境变量覆盖入口不再作为配置来源。内部执行时注入的运行时变量只给子进程使用，不属于用户配置面。
