# Codex 凭证与本机运行能力迁移

本文说明如何在新机器恢复 Agent World Foundry 的真实 Codex 调用能力。仓库只保存配置字段和操作约定，不保存任何 token、API key、`auth.json`、Codex session 或 shell snapshot。

Foundry 支持两种互斥的模型认证方式：

1. ChatGPT 登录文件：适合使用本地 Codex 登录额度；
2. API key 环境变量：适合自动化或 OpenAI-compatible Base URL。

不要同时配置两种方式。`openai_base_url` 只能与 API key 方式一起使用。

## 1. 迁移前需要记录什么

只记录非秘密信息：

```text
Git branch: codex-agent-world-runtime-redesign
Python: 3.12
model: 由 agent.model 显式选择（当前实验优先 grok-4.5；备用 gpt-5.4-mini）
认证方式: chatgpt_auth_file 或 api_key_environment
Codex 安装方式/版本
研究 provider: searxng 或 jina
state_root 的迁移目标位置
是否需要迁移脱敏后的 .agent-world-live 状态
```

不要把以下内容写入迁移文档、Git、Issue、聊天记录或普通压缩包：

```text
auth.json 的内容
API key / access token
<node-workspace>/.agent-runtime/codex-home/
<node-workspace>/.agent-runtime/home/
Codex sessions、state、logs、history 或 shell snapshots
未经脱敏的 .agent-world-live/
```

## 2. 新机器恢复共同依赖

```bash
git clone <PRIVATE_REPOSITORY_URL>
cd agent-world-model
git switch codex-agent-world-runtime-redesign
uv sync
command -v codex
codex --version
```

安装支持项目 SDK 协议的当前 Codex 预览版。配置里的 `agent.codex_bin` 必须是新机器上的真实可执行文件绝对路径，不能沿用旧机器路径，也不能指向符号链接。Linux/WSL 可用下面的命令得到解析后的路径：

```bash
readlink -f "$(command -v codex)"
```

## 3. 方式 A：ChatGPT 登录文件

这是本项目使用本地 Codex 登录时的推荐方式。官方 Codex 可能把凭证放进系统 keyring；当前 Foundry 明确接收一个 `auth.json` 文件，因此需要让 Codex 使用 file credential store。

Codex 的默认 home 是 `~/.codex`。如果自定义了 `CODEX_HOME`，以下所有路径都应以该目录为准。在用户级 `$CODEX_HOME/config.toml` 中保留或加入：

```toml
cli_auth_credentials_store = "file"
```

随后在新机器重新登录，优先于复制旧 token：

```bash
codex login
codex login status
```

无图形浏览器时可使用：

```bash
codex login --device-auth
codex login status
```

确认凭证文件存在并收紧权限。不要打印其内容：

```bash
chmod 700 "${CODEX_HOME:-$HOME/.codex}"
chmod 600 "${CODEX_HOME:-$HOME/.codex}/auth.json"
test -s "${CODEX_HOME:-$HOME/.codex}/auth.json"
```

Foundry TOML 使用绝对路径：

```toml
[agent]
model = "YOUR_CODEX_MODEL"
codex_bin = "/absolute/resolved/path/to/codex"
chatgpt_auth_file = "/home/NEW_USER/.codex/auth.json"
```

此方式不要再设置 `api_key_environment` 或 `openai_base_url`。

如果确实无法重新登录，只能通过受控的秘密管理器或加密介质迁移旧 `auth.json`，在目标机恢复为 `0600`，验证成功后删除中间副本。不要用 Git、普通网盘、聊天附件或未加密归档传输。

## 4. 方式 B：API key 或兼容 Base URL

配置只保存环境变量名称，不保存 key：

```toml
[agent]
model = "YOUR_OPENAI_COMPATIBLE_MODEL"
model_provider = "openai"
codex_bin = "/absolute/resolved/path/to/codex"
openai_base_url = "https://YOUR-ENDPOINT.example/v1"
api_key_environment = "AGENT_WORLD_MODEL_API_KEY"
```

此方式不要设置 `chatgpt_auth_file`。在启动 Foundry 的同一个受信任进程环境中，从操作系统 secret store、密码管理器或私有 CI secret 注入变量。例如交互式终端可避免把 key 写入 shell 历史：

```bash
read -rsp "Model API key: " AGENT_WORLD_MODEL_API_KEY
export AGENT_WORLD_MODEL_API_KEY
test -n "$AGENT_WORLD_MODEL_API_KEY"
```

不要把 key 写进项目 TOML、`.env`、systemd unit 正文或命令行参数。Research 使用的 Jina key 是另一项独立凭证，只在选择 Jina provider 时通过 `research.jina_api_key_environment` 指定环境变量名称。

## 5. Foundry 如何使用 CODEX_HOME

个人 `$CODEX_HOME` 只是认证来源和本机 Codex 配置位置。Foundry 不把整份个人 Codex home 交给 Agent，也不依赖其中的 session 恢复业务 Artifact。

每次真实 Agent 节点执行时，`IsolatedAgentProfileProvider` 会创建隔离目录：

```text
<node-workspace>/.agent-runtime/codex-home/
```

它只物化该角色获准使用的认证、模型/provider 配置、skills、hooks 和工具能力。Researcher、Environment Engineer 与 Challenger 的 HOME、CODEX_HOME、workspace、网络和 sealed evidence 彼此隔离。节点结束后，这些目录是可重建的敏感运行材料，不是可发布 Artifact。

因此迁移时：

- 需要恢复认证来源、Codex 二进制和 Foundry TOML；
- 不需要迁移节点级 `codex-home`、session、state 或 shell snapshot；
- 精确续跑依靠脱敏后的 Foundry `state_root` 和 ArtifactStore，不依靠 Codex 会话目录；
- 若旧 Builder session 已丢失，需要返工时启动新的真实 Builder，不能伪造 session continuation。

## 6. 恢复后的真实验证

先复制并修改非秘密配置模板：

```bash
mkdir -p ~/.config/agent-world
if [ ! -e ~/.config/agent-world/config.toml ]; then
  cp config/agent-world.example.toml ~/.config/agent-world/config.toml
fi
chmod 600 ~/.config/agent-world/config.toml
```

完成路径、认证方式、Research provider 和 `state_root` 配置后运行：

```bash
uv run agent-world --config ~/.config/agent-world/config.toml doctor
uv run agent-world --config ~/.config/agent-world/config.toml doctor --live-agent
```

第一条检查本机依赖和配置；第二条会真实消耗一次当前 `agent.model` 所选的 Codex SDK 调用，用来证明凭证、隔离 profile、SDK 和模型路径可以工作，不是 mock。Research 也恢复后，执行完整生产预检：

```bash
uv run agent-world --config ~/.config/agent-world/config.toml doctor --production
```

只有真实 Agent 与真实 Research probe 都通过时，`production_ready` 才应为 `true`。

## 7. 常见迁移失败

| 现象 | 原因 | 处理 |
|---|---|---|
| 找不到 `auth.json` | Codex 使用了 keyring/auto | 在用户级 Codex config 选择 `file` 后重新登录 |
| auth permissions too broad | 文件权限宽于 `0600` | `chmod 600 "${CODEX_HOME:-$HOME/.codex}/auth.json"` |
| authorized login path invalid | 使用相对路径、符号链接或空文件 | 使用真实文件的绝对路径并重新登录 |
| exactly one authentication mode | TOML 同时或都未配置两种认证 | 只保留 `chatgpt_auth_file` 或 `api_key_environment` |
| base URL requires API-key authentication | 用 ChatGPT auth 配置兼容 endpoint | 改用环境变量 API key 方式 |
| model credential environment unavailable | 启动进程没有继承指定变量 | 从 secret store 向同一进程注入变量 |
| configured codex_bin must be a real executable | 沿用旧路径或配置了符号链接 | 在新机器重新解析 `command -v codex` |

## 8. 官方参考

- [Codex Authentication](https://learn.chatgpt.com/docs/auth)
- [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands#codex-login)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)
