# Codex 凭证与本机运行能力迁移

本文说明如何在新机器恢复 Agent World Foundry 的真实 Codex 调用能力，同时保持凭证和
路由信息不落盘。

## 认证与路由合同

Foundry 只支持环境变量句柄：

```toml
[agent]
model = "YOUR_MODEL"
api_key_environment = "OPENAI_API_KEY"
openai_base_url_environment = "OPENAI_BASE_URL"
```

TOML、`ResolvedAgentProfile`、生成的 `CODEX_HOME/config.toml`、Artifact、trace、manifest、
envpkg 和报告中只允许出现这两个变量名，绝不出现其实际值。

运行时，`CodexSdkBackend` 将 API key 和 base URL 只保留在隔离 worker/app-server 环境。worker 为每个
Codex thread 通过 SDK 的进程内 request config 选择 framework-owned custom provider；其 `env_key` 是
`OPENAI_API_KEY`。两者都不写入 `CODEX_HOME/config.toml`、SDK `--config` override 或命令行参数。worker
不调用 `login_api_key()`、不读取或复制 `auth.json`，并以 `cli_auth_credentials_store = "keyring"`
禁止文件凭证存储。SDK-bundled app-server 必建的 SQLite state/log 平面被定向到单次调用的内存目录，
backend 在返回 durable 结果前销毁该目录，不能回退到 profile/artifact 根目录。

`chatgpt_auth_file` 和字面 `openai_base_url` 是已移除的配置键。加载器会在不回显旧值的前提下
fail closed，并提示改用上述环境句柄。

## 新机器准备

```bash
git clone <PRIVATE_REPOSITORY_URL>
cd agent-world-model
uv sync
```

使用受信任的 secret manager、CI secret 注入或当前用户受控的进程环境向启动 Foundry 的同一
进程提供 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。不要将值写入项目 TOML、`.env`、命令行参数、
systemd unit 正文、Git、聊天记录或普通归档。

若使用自定义 Codex 二进制，`agent.codex_bin` 必须是新机器上的真实绝对可执行路径；否则使用
项目 pin 的 SDK-bundled runtime。

## 真实验证

先执行不花模型 token 的预检：

```bash
uv run agent-world doctor --config /absolute/path/to/config.toml
```

再执行真实 SDK 路径验证：

```bash
uv run agent-world doctor --config /absolute/path/to/config.toml --live-agent
```

第二条命令会真实消耗一次模型调用。它失败时保留安全的终态类别；不得改为 curl、mock、模板或
人工写入 Artifact。只在 `doctor --live-agent` 与后续分段节点证据均通过时继续真实生成。

## 安全检查

迁移或每次真实诊断后，审计运行目录时只比较内存中的凭证/路由值与文件字节并输出计数、布尔值
和路径，不显示值本身。任何命中都使该 run 非 releasable，必须删除可再生的运行缓存并修复写入
路径后重新执行真实节点。

## 常见失败

| 现象 | 处理 |
|---|---|
| `agent.openai_base_url is forbidden` | 删除字面 URL，改为 `openai_base_url_environment = "OPENAI_BASE_URL"`。 |
| `agent.chatgpt_auth_file is forbidden` | 改为 API-key 环境句柄；不要复制 `auth.json`。 |
| `model credential environment is unavailable` | 由 secret manager 向同一启动进程注入 `OPENAI_API_KEY`。 |
| `model routing value environment is unavailable` | 由 secret manager 向同一启动进程注入 `OPENAI_BASE_URL`。 |
| `routing_environment_invalid` | 修正环境中的 URL 形状；不要把它写回 TOML。 |
| `HostExecutionUnavailable` | 检查本机 Python/子进程启动链；不得跳过 Judge，也不要添加 bwrap/user namespace 回退。 |
