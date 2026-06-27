# AWM 1K 数据样本说明

> 边界说明：本文只说明 AWM 样本如何作为背景资料或离线 fixture 使用。当前任务源以 `docs/agent-world-environment-generation.zh.md` 为准；不要把 AWM JSONL 或 MCP 形态当成新系统的核心格式。

## 来源

数据集：`Snowflake/AgentWorldModel-1K`

本地只保存了每个 JSONL 的前 3 条样本，用于理解格式和编写 importer/verifier fixture：

```text
research/data/awm_1k_samples/
  README.md
  gen_scenario.jsonl
  gen_tasks.jsonl
  gen_db.jsonl
  gen_sample.jsonl
  gen_spec.jsonl
  gen_envs.jsonl
  gen_verifier.jsonl
  gen_verifier.pure_code.jsonl
```

不要默认整包下载。HuggingFace 文件体量约为：

- `gen_scenario.jsonl`: 1.3MB
- `gen_tasks.jsonl`: 2.7MB
- `gen_db.jsonl`: 11.7MB
- `gen_sample.jsonl`: 37.1MB
- `gen_spec.jsonl`: 68.5MB
- `gen_envs.jsonl`: 104.0MB
- `gen_verifier.jsonl`: 247.9MB
- `gen_verifier.pure_code.jsonl`: 45.4MB

如果确实需要完整数据，优先下载到 `outputs/awm_1k_raw/`，不要放进 `research/`：

```bash
uvx --from huggingface_hub huggingface-cli download Snowflake/AgentWorldModel-1K --repo-type dataset --local-dir outputs/awm_1k_raw
```

## 字段观察

`gen_scenario.jsonl`

- 字段：`name`, `description`
- 映射：`ScenarioSpec`

`gen_tasks.jsonl`

- 字段：`scenario`, `tasks`
- `tasks` 是 10 条自然语言用户任务。
- 映射：`TaskSpec`

`gen_db.jsonl`

- 字段：`scenario`, `db_schema`, `db_path`
- `db_schema` 包含表结构。
- 映射：`EnvironmentSpec.state_backend`

`gen_sample.jsonl`

- 字段：`scenario`, `tables_count`, `inserts_count`, `sample_data`
- `sample_data` 是初始数据库数据。
- 映射：`EnvironmentSpec.initial_state`

`gen_spec.jsonl`

- 字段：`scenario`, `api_spec`
- `api_spec.api_groups[]` 包含 `group_name` 和 `endpoints`。
- endpoint 包含 `path`, `method`, `summary`, `description`, `operation_id`, `request_params`, `response`, `required_tables`, `required_fields`。
- 映射：`ToolSpec`

`gen_envs.jsonl`

- 字段：`scenario`, `db_path`, `full_code`
- `full_code` 是 FastAPI + MCP 风格的环境代码。
- 映射：可作为后续通用环境 artifact 转换 fixture。

`gen_verifier.jsonl`

- 字段：`scenario`, `task_idx`, `task`, `verification`
- `verification` 包含 `code` 和 `raw_response`。
- 映射：`VerifierSpec`，适合 code-augmented judge。

`gen_verifier.pure_code.jsonl`

- 字段同上。
- `verification.code` 是 `verify_task_completion(initial_db_path, final_db_path, final_answer=None) -> dict` 风格。
- 映射：优先用于 deterministic verifier fixture。

## 作为背景资料的使用边界

- AWM 1K 样本可以作为 source discovery 的本地材料或 verifier 设计参考。
- 不要求新系统复用 AWM JSONL 字段名或 MCP 暴露方式。
- 如果后续需要 importer，应把 AWM 样本转换成项目自己的通用环境生成 artifact，不能让 AWM 原始格式成为核心 schema。
- verifier 设计可以参考 `gen_verifier.pure_code.jsonl` 的 pure-code 形态。
- 本地样本优先用于离线实验；不要默认下载完整数据集到仓库。
- 所有运行命令使用 `uv run ...`，完整数据下载使用 `uvx ...`。
