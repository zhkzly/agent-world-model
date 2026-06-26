# AWM 1K 数据样本说明

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
- 映射：`EnvironmentSpec.runtime` 和 AWM adapter fixture。

`gen_verifier.jsonl`

- 字段：`scenario`, `task_idx`, `task`, `verification`
- `verification` 包含 `code` 和 `raw_response`。
- 映射：`VerifierSpec`，适合 code-augmented judge。

`gen_verifier.pure_code.jsonl`

- 字段同上。
- `verification.code` 是 `verify_task_completion(initial_db_path, final_db_path, final_answer=None) -> dict` 风格。
- 映射：优先用于 deterministic verifier fixture。

## 对 awmx 的约束

- importer 必须支持从这些 JSONL 样本构造 `ScenarioSpec`、`TaskSpec`、`EnvironmentSpec`、`ToolSpec`、`VerifierSpec`。
- importer 测试必须使用本地小样本，不依赖网络和真实 LLM API。
- verifier 测试优先使用 `gen_verifier.pure_code.jsonl` 的接口形态。
- AWM MCP 只能作为 adapter 或 runner 后端，不允许让 AWM 数据格式泄漏到通用 trace/reward schema。
- 所有运行命令使用 `uv run ...`，完整数据下载使用 `uvx ...`。
