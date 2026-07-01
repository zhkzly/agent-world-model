# Agent World Environment Generation

本仓库目标：把用户给出的环境需求、能力缺口、PRD、repo、MCP/CLI/API/SDK 文档、数据库 schema 或其他 source material，生成可复现、可验证、可发布的可执行环境包。

唯一项目目标源文档：

- [docs/agent-world-environment-generation.zh.md](docs/agent-world-environment-generation.zh.md)

背景材料：

- [docs/loop-engineering.md](docs/loop-engineering.md)

配置说明：

- [docs/configuration.zh.md](docs/configuration.zh.md)

验证入口：

```bash
uv run pytest tests/agent_world
```
