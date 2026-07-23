# Agent World Foundry 配置

配置入口是 `agent_world.config.load_foundry_config()`。默认读取
`~/.config/agent-world/config.toml`；CLI 的 `--config` 或环境变量
`AGENT_WORLD_CONFIG` 可以显式选择其他文件。

配置只保存模型名、端点、预算、隔离策略和凭证“句柄”。API key、登录 token、Cookie、
private key 等值不得写入 TOML、Artifact、日志、manifest 或 envpkg。

## 最小可运行配置

```toml
state_root = "/home/me/.local/state/agent-world"

[agent]
model = "YOUR_CODEX_MODEL"
codex_bin = "/absolute/path/to/a/current/codex"
chatgpt_auth_file = "/home/me/.codex/auth.json"
reasoning_researcher = "medium"
reasoning_engineer = "medium"
reasoning_challenger = "medium"
invocation_timeout_seconds = 2700
structured_invocation_timeout_seconds = 2700
environment_codegen_invocation_timeout_seconds = 2700
structured_output_transport = "provider_schema"
tool_output_token_limit = 2048
structured_turn_token_limit = 65536
environment_codegen_turn_token_limit = 262144
engineer_network_domain_ceiling = ["pypi.org", "files.pythonhosted.org"]
engineer_dependency_network_domains = []

[research]
provider = "searxng"
searxng_base_url = "http://127.0.0.1:8080"
searxng_allow_private_endpoint = true
allow_rfc2544_synthetic_egress = false
use_jina_reader_fallback = true
jina_reader_url = "https://r.jina.ai"
request_timeout_seconds = 30
max_response_bytes = 8388608
max_parallel_searches = 4
max_parallel_fetches = 4

[judge]
clean_build_timeout_seconds = 600
uv_cache_dir = "/home/me/.cache/uv"

[release_profile]
profile_id = "default-release"
required_hard_gates = [
  "schema",
  "supply_chain",
  "static_assurance",
  "public_self_check",
  "runtime_protocol",
  "task_materialization",
  "task_reachability",
  "behavior",
  "sealed_release",
  "clean_deployment",
]
maximum_risk = "medium"
require_reproducible_reset = true
require_unknown_seed_testing = true
require_clean_install = true
require_package_relative_paths = true
allow_unresolved_assumptions = false
```

配置 loader 会把 TOML array 显式转换为严格 `ReleaseProfile` tuple。省略
`required_hard_gates` 时使用与上面相同的封闭十门默认；显式覆盖意味着有意定义一套 release
policy，不能用它跳过 framework 始终强制的安全检查，也不能让 Agent、Policy 或 LLM score 覆盖
失败 Gate。生产配置建议保留上面的完整列表，使 no-mock 发布合同在配置审查中可见。

`YOUR_CODEX_MODEL` 必须替换为当前 Codex SDK 账户可用的真实模型。`codex_bin` 指向用户
明确选择的当前官方 Codex CLI；profile 会绑定其内容哈希，worker 在启动 app-server 前再次
校验。若省略则使用 SDK 精确 pin 的 bundled runtime，但 `doctor` 会 fail closed，因为 beta
SDK 的 bundled CLI 可能已被在线服务拒绝。系统不会在失败时切换成模板、假 backend 或另一模型。

## 模型认证

只允许二选一。

### 显式授权现有 ChatGPT/Codex 登录

```toml
[agent]
model = "YOUR_CODEX_MODEL"
codex_bin = "/absolute/path/to/a/current/codex"
chatgpt_auth_file = "/absolute/path/to/auth.json"
```

该路径是用户明确授予 Foundry 的 handle。`ProfileResolver` 会把内容复制到本次 Agent 的
隔离 `CODEX_HOME`，权限固定为 `0600`；源路径、内容和哈希不进入公共 metadata。系统不会
自行扫描 `$HOME/.codex`。

### API 环境句柄

```toml
[agent]
model = "YOUR_CODEX_MODEL"
codex_bin = "/absolute/path/to/a/current/codex"
api_key_environment = "OPENAI_API_KEY"
# 可选：显式覆盖 Codex 内置 openai provider 的 API 根路径
openai_base_url = "https://compatible-provider.example/v1"
```

然后只在启动进程的环境中提供值：

```bash
export OPENAI_API_KEY='...'
```

TOML 中保存的是变量名，不是 key。`openai_base_url` 只允许与 API-key 模式和内置
`openai` provider 配合，不能与 ChatGPT 登录混用，也不能包含用户名、密码、query 或
fragment。Profile Resolver 会把它写入每次隔离的 `$CODEX_HOME/config.toml` 并纳入 profile
hash；不会从宿主环境隐式继承兼容端点。

`structured_output_transport` 默认是 `provider_schema`：直接把收窄后的 JSON Schema 交给
provider。只有已通过真实 probe 证明某个兼容 gateway 会拒绝嵌套 schema 时，才显式设为
`json_envelope`。后者只把 provider 层收窄为 `{"artifact_json":"..."}`，内部 JSON 仍由
原始 Pydantic contract、确定性 compiler、Scheduler repair 和所有 Release Gate 验证；它不是
模板、mock 或放宽输出/发布验收的开关。

## 三种隔离 Agent Profile

系统只物化三种 profile：

- `researcher`：只读 workspace、真实 evidence Skill、无 workspace edit、无发布权；
- `environment-engineer`：独立可写 workspace、真实 build/test、无 sealed verifier；
- `challenger`：只读设计和运行观测、产生 data-only verifier proposal、无代码修改权。

每次物化都使用独立 HOME、CODEX_HOME、workspace、Skill bundle 和项目根 marker。默认不
继承全局 Skills、Hooks、MCP、AGENTS.md 或 shell 环境。当前内置组合显式配置空 Hooks 与空
MCP；后续接入 MCP 时必须通过 `McpServerSpec` 同时声明 server、transport、tool allowlist、
domain 和 credential handle，不能把 MCP SDK 调用散落到 pipeline core。

`engineer_network_domain_ceiling` 是 Environment Engineer 角色的 operator ceiling，不是默认
联网授权；`engineer_dependency_network_domains` 是 Builder 节点执行 `uv lock`/真实依赖检查时
实际需要的精确域名，必须是 ceiling 的子集，默认空即 Builder Agent 离线。每次真实调用先由 framework 编译 `EffectiveCapabilityPlan`：角色 ceiling、当前
Generate/Expand Job 的 `PermissionScope` 与节点的 typed requirement 三者都允许，最终 profile
才获得节点实际需要的外部能力。Builder requirement 总是包含隔离 workspace 的内建
`shell + workspace_edit`，并仅在 `engineer_dependency_network_domains` 非空时要求其中的精确
域名。CLI 会把这个显式选择冻结进 Generate/Expand Job；为保持 ResearchToolchain 原有的任意
公开 Web 检索，它在 Job 网络授权中同时写入 `*`，但 Engineer 最终仍受角色 ceiling 和节点
requirement 收窄，只获得精确 dependency domains。Python API 调用方若未授予同一网络范围，
Builder 会在模型调用前返回 `needs_human`。内建 sandbox 能力和外部 `tool_allowlist` 是不同命名空间。

计划及三份输入的 canonical hash 都进入 profile hash 与 continuation identity。缺少节点必需的
domain/tool/credential 时调用会在物化 profile 前 fail closed，并由生成流程报告
`needs_human`；不会继承全局 Codex 权限，也不会把空交集替换成 ceiling。

## Research Provider

### SearXNG

```toml
[research]
provider = "searxng"
searxng_base_url = "https://search.example.org"
searxng_allow_private_endpoint = false
```

本机或局域网 SearXNG 必须显式把 `searxng_allow_private_endpoint` 设为 `true`；普通 evidence
URL 仍执行逐跳 redirect、DNS 和私网地址拒绝。SearXNG 必须启用 JSON format。

某些受控执行沙箱会把所有真实公网连接映射到 RFC 2544 benchmark 网段
`198.18.0.0/15`。只有能够确认该网段由宿主 egress 层独占时，才可显式设置
`allow_rfc2544_synthetic_egress = true`。默认值为 `false`，普通主机、服务器、CI 和企业网络
不得开启。开启后仍拒绝 loopback、RFC1918、link-local、userinfo、credential query 和域名
allowlist 违规，并逐跳复验 DNS；provenance 会记录
`rfc2544-synthetic-egress-*`，不会伪称已验证目标站真实 peer IP。

### Jina Search/Reader

```toml
[research]
provider = "jina"
jina_search_url = "https://s.jina.ai"
jina_reader_url = "https://r.jina.ai"
jina_api_key_environment = "JINA_API_KEY"
jina_credential_handle = "jina-api-key"
use_jina_reader_fallback = true
```

```bash
export JINA_API_KEY='...'
```

Search result 的 title/snippet 只用于选择 URL，不能进入 EvidenceGraph。只有真实 fetch 得到
正文并经 extractor 处理、保存 source URI、时间、raw/extracted hash、fetcher/extractor
版本后，才能成为 Evidence。Jina Reader 是明确记录的 fallback，不会伪装成源站原文。

Jina 凭证只能发送到精确的官方 HTTPS origin：Search 为 `https://s.jina.ai:443`，Reader 为
`https://r.jina.ai:443`。配置和 provider 构造器都会拒绝 userinfo、其他 host、非 443 端口、
额外 path/query/fragment；Jina 返回 redirect 时不会转发 `Authorization`。环境变量只是凭证
来源，当前 request 与 run 的 `PermissionScope.credential_handles` 还必须同时包含
`jina-api-key`（或配置的同名 handle），否则真实调用在联网前拒绝。

### Research 权限语义

ResearchToolchain 同时执行 request 和当前 run 的权限，两者取最小权限：

- `allowed_source_kinds` 当前必须严格等于 `["web"]`，因为生产 Research adapter 目前只实现真实 Web 检索、抓取与正文提取；MCP/CLI/API/SDK 是从 Web 证据中发现的 tool surface 类型，不是假装已经实现的 source transport；
- `network_domains = []` 明确定义为“任意公开 Web origin”，仍拒绝 private、loopback、
  link-local 和 reserved 地址；不是关闭 DNS/redirect 检查；
- 任一层给出非空 `network_domains` 后，每个 source URL 和每个 redirect hop 都必须同时满足
  两层 allowlist；
- SearXNG/Jina Search endpoint 是管理员配置的 provider capability，和搜索结果指向的 evidence
  source domain 分开；source allowlist 不会被误用于阻断私有 SearXNG 服务，也不会因允许
  SearXNG endpoint 而允许同域 source；
- 空 `tool_allowlist` 只启用框架内置的只读 search/fetch/reader；一旦显式填写，就需按实际
  路径列出 `research.search`、`research.fetch`，使用 Reader fallback 时还要列出
  `research.reader`。

普通 HTTP source 每个 hop 都做连接前和连接后的 DNS 稳定性检查，并在 httpx 暴露
`network_stream.server_addr` 时校验实际 peer 必须属于连接前解析集合。若运行 backend 不暴露
可靠 peer，只能记录 `dns-stability-only`，此时 DNS 集合发生任何变化都会 fail closed；这能
缩小但不能从密码学上消除两次解析之间的 DNS TOCTOU，因此研究 provenance Artifact 会明确
保存该 assurance 等级。HTTP 客户端不继承环境代理。

Jina Reader 的连接校验只能证明 Foundry 连接的是官方 Reader origin，不能观察 Jina 在服务端
抓取 source 时使用的最终 peer；因此 provenance 标为 `remote-reader-origin-only:*`，不能与
本地 `peer-address+dns-stability` 等价。需要严格本地逐跳证明的 release policy 应关闭 Reader
fallback。

进入 Artifact 和 Researcher workspace 前，raw/extracted 正文都会做 credential canary 与
高置信 secret 扫描。单 raw 文档上限 8 MiB、单 extracted 正文上限 2 MiB；单次研究最多
32 MiB raw、16 MiB extracted。Researcher 收到的是未截断的、通过上述限制的完整清洗正文及
provenance manifest，不再只有 600 字 observed summary。超限或含 secret 的文档被记录为
失败，不能成为 Evidence。`supplied_asset_refs` 尚无已授权 materializer，因此非空请求会由
Designer fail closed，而不会假装已读取资产。

## 分维预算

`generation_budget` 与 `discovery_budget` 是独立预算表，可覆盖以下字段：

```toml
[generation_budget]
llm_tokens = 10000000
agent_turns = 128
search_calls = 6
tool_calls = 512
build_seconds = 900
evaluation_episodes = 128
container_seconds = 3600
repair_attempts = 15
wall_seconds = 28800

[discovery_budget]
llm_tokens = 80000
agent_turns = 4
search_calls = 3
tool_calls = 12
wall_seconds = 900
```

未列出的维度为零，不会自动从 token、时间或金额等其他维度“借预算”。Discovery 使用独立
小预算，即使失败或超时也不能占用 Direct Generation 的首包预算。

这里的生产默认值刻意覆盖 Task Materialization v3 与真实 task reachability 的最坏情况
预留。Controller 会在任何 Judge episode 或 interactive Challenger 调用前取得 durable child
lease；配置过小会在调用前诚实返回 `budget_exhausted`，不会先执行再事后补账。

### Expansion Campaign

Expansion 是首包之后显式启动的独立搜索活动，不是 `generate` 的前置阶段：

```toml
[expansion]
policy = "evolutionary-archive" # random-search | wide-search | evolutionary-archive
default_source_ids = ["source:tool-ecosystem"]
maximum_intents_per_iteration = 2
maximum_iterations = 5
maximum_no_release_iterations = 3
maximum_infrastructure_error_iterations = 3
max_in_flight = 2
external_injection_rate = 0.25
version_reservation_ttl_seconds = 86400

[[expansion.sources]]
source_id = "source:tool-ecosystem"
engine = "evidence-backed-web"
version = "1"
kind = "tool_ecosystem"
maximum_hypotheses = 4
maximum_clues = 4
maximum_parents = 8
maximum_context_bytes = 524288

[expansion.sources.budget]
llm_tokens = 80000
agent_turns = 4
search_calls = 3
tool_calls = 12
wall_seconds = 900

[expansion.campaign_budget]
llm_tokens = 6000000
agent_turns = 640
search_calls = 30
tool_calls = 2560
build_seconds = 4500
evaluation_episodes = 640
container_seconds = 18000
repair_attempts = 15
wall_seconds = 36000

[expansion.candidate_budget]
llm_tokens = 1200000
agent_turns = 128
search_calls = 6
tool_calls = 512
build_seconds = 900
evaluation_episodes = 128
container_seconds = 3600
repair_attempts = 3
wall_seconds = 7200
```

`sources` 是可替换的发现器目录，`default_source_ids` 是 CLI 没有传 `--source` 时真正执行的子集；
两者分开后可以同时配置多种实验 Source，而不必让每次 Campaign 全部运行。`--source SOURCE_ID`
可重复并显式覆盖默认选择。当前生产 router 注册 `evidence-backed-web@1`，它支持
`requirement_gap`、`web_workflow`、`tool_ecosystem`、`repository`、`pool_neighborhood`、
`random_theme` 和 `capability_gap` 等 kind，但不接受未消费的 `parameters`；未知 engine/version
会在外部调用前 fail closed。完整的三 Source 示例见
[`config/agent-world.example.toml`](../config/agent-world.example.toml)。

要启用 feedback-guided discovery，可额外配置但不必放进默认集合：

```toml
[[expansion.sources]]
source_id = "source:capability-gap"
engine = "evidence-backed-web"
version = "1"
kind = "capability_gap"
maximum_hypotheses = 4
maximum_clues = 4
maximum_parents = 8
maximum_context_bytes = 524288

[expansion.sources.budget]
llm_tokens = 80000
agent_turns = 4
search_calls = 3
tool_calls = 12
wall_seconds = 900
```

只有显式 `--source source:capability-gap --feedback-revision ...` 时它才会运行；没有 feedback 的
CapabilityGap request 在 Agent 或网络调用前被拒绝。普通 Source 和普通 Campaign 始终不依赖它。

每个 Source 都有自己的真实 Researcher/Search 预算、最多 hypothesis/clue、最多可见 parent 和
canonical context byte 上限。`search_calls` 只计 search；`tool_calls` 计 search、fetch 和 Reader
fallback 的总次数，因此必须严格大于 `search_calls`。所有 anchor 都必须保留在 Source parent view
内；若 anchor 数已超过 `maximum_parents`，Campaign 不会偷偷丢弃 anchor，而是拒绝配置。

Campaign 在第一次 `Policy.ask` 前为选中 Source 持久化 request 与 lease，执行真实搜索/抓取，保存
terminal result，再冻结 clue snapshot 与 Policy context。`insufficient_evidence`、`input_rejected`、
Source budget 或 infrastructure failure 不会伪造 clue；若没有可用 clue，Policy 仍可从冻结 Pool/Inbox
采样。`needs_human` 会在第一次 ask 前停止。`capability_gap` Source 必须同时传入精确 frozen
CapabilityFeedback revision；feedback 只能改变研究优先级，不能充当 evidence。

Campaign budget 是 Source intake 与全部候选共享的全局硬上限；配置加载与 Campaign 启动都会验证
“本次选中 Source 的可加预算总和 + 至少一个完整 candidate lease”可负担。每个候选再取得完整的分维
lease，结束后按真实使用量结算。并发候选不能重复占用 token/search/build/evaluation 等可加资源；
wall time 是共享 deadline，不按并发数量相加。恢复时不能确定的进程内 Agent 消耗不会按零处理。
每个候选完成 Identity Gate 后、Builder/Judge 前必须从 Registry 预留唯一 package/version。
`maximum_iterations` 是停止上限，不承诺预算足以跑同样数量的完整候选；实际可执行数量由 Source
结算后的最紧预算维度决定，维度之间不能借余额。

## Judge 安装策略

clean build 固定在无网络 bubblewrap 中执行。候选源码以逐文件只读视图挂载，依赖环境先在
独立的可写目录生成，再由 framework 复制到 clean materialization 的 `.venv`；依赖构建过程
不能修改候选源码：

```text
uv sync --frozen --no-dev --offline --no-build --no-editable \
  --no-config --no-install-project --no-install-workspace --no-install-local
```

必须显式配置 `uv_cache_dir`，目录必须是真实、可读且可搜索的预填充 uv cache；它会以
只读目录挂入 build sandbox，候选 lock 中的全部依赖都必须已在该 cache 可用。系统不会用一个
临时空 cache 冒充生产就绪，也不会在 cache miss 时回退网络。Doctor 会先用诊断专属临时 cache
为最小项目实际执行 `uv lock --offline`，再把配置的生产 cache 以与 Judge 相同的只读方式挂入
bubblewrap，执行同一 dependency-only sync；lock 步骤不会反向要求只读生产 cache
可写。最后 Doctor 在独立的只读 runtime sandbox 中执行安装所得的 Python，并要求其精确为
3.12。该探针证明解释器、uv、cache 挂载和 bubblewrap 能协作；每个真实候选的具体依赖是否
齐全，仍由其 clean-build Gate 逐包证明。

当前没有域名受限的依赖 fetch broker，因此不存在在线 clean-build 发布成功路径，也不存在
`--share-net` 降级。cache miss 会诚实地使 clean-deployment Gate 失败；依赖必须在发布前由受信
流程预填充进 `uv_cache_dir`。根项目本身不被安装，而是从只读 workspace 直接执行；lock 中只允许
这一个根项目使用 `editable = "."` 或 `virtual = "."` 表达依赖闭包。其他依赖必须来自固定 HTTPS
PyPI registry、包含 hash/size 的 `files.pythonhosted.org` wheel；path、Git、direct URL、editable、
自定义 index、候选 build backend 和 sdist 构建都被拒绝。

无论 clean build 是否联网，候选 Runtime、task generator、public self-check、consumer adapter、
public/repair/sealed verifier 和并发探针始终使用另一份 `purpose = "runtime"` 的离线隔离策略：
只读 workspace、独立可写 state 目录、无宿主网络。不存在“隔离不可用就退回宿主机执行”的路径。

## Preflight

```bash
uv run agent-world --config /path/to/config.toml doctor
uv run agent-world --config /path/to/config.toml doctor --live-agent
uv run agent-world --config /path/to/config.toml doctor --live-research
uv run agent-world --config /path/to/config.toml doctor --production
```

默认 preflight 检查 state root、真实认证句柄、官方 Codex SDK、显式 Codex CLI 版本、uv、
bubblewrap namespace、profile 物化，并执行一次真实 clean-build readiness probe：生成最小 uv
工程和真实 lock、通过生产 `CleanCandidateBuilder` 安装、再通过生产 runtime isolation 执行精确
Python 3.12 检查。未配置或无法读取 `uv_cache_dir` 时会 fail closed。报告把
`local_execution_ready`、`configuration_ready`、两个 live 验证和 `production_ready` 分开；默认
Doctor 不会把“配置看起来完整”宣称为真实外部服务已验证。`--live-agent` 会真实消费一次 Codex SDK
structured-output turn，`--live-research` 会真实消费一次 search/fetch/extract 调用，二者都必须显式
开启。`--production` 同时执行两者，只有本地基座、配置和两个 live probe 全部通过时才会返回
`production_ready=true`。

## 生产装配与 CLI

`agent_world.app.build_application()` 是唯一生产 composition root。它一次性装配：

- 同一份 `ArtifactStore` 与 `EnvironmentRegistry`；
- 三种隔离 profile 和唯一的 `CodexSdkBackend`；
- 真实 Search/Fetch/Extract toolchain；
- Direct Designer、独立 Discovery lane 和真实 Campaign 使用的 Expansion Designer；
- Environment Builder、Verifier Compiler、clean-build/runtime 隔离 Judge；
- 拥有预算、返工路由和发布决策的 `FoundryController`。

模型环境句柄、Jina 环境句柄以及显式授权的 Codex `auth.json` 会在装配时解析。值只作为进程内
credential 和 Artifact/Registry secret canary 存活，不会进入对象公开描述、异常、事件、Artifact
或 envpkg。`auth.json` 必须是非 symlink 的普通 JSON 文件，在 POSIX 上不得对 group/world 开放；
读取使用文件描述符身份复核来拒绝替换竞态。

完整首包流程：

```bash
uv run agent-world --config /path/to/config.toml generate \
  --need '需要一个可训练的本地商家订单与退款协作环境'
```

可选参数：

- `--request-id ID` 为真实重试提供稳定请求身份；
- `--no-discovery` 只关闭独立 Discovery 预算车道，不会跳过 Direct Generation 的真实研究；
- Jina 配置存在时，CLI 会把配置的 credential handle 明确放进本次 request permission；空
  `network_domains` 仍遵循上文“任意公开 Web、拒绝私网”的定义。

Registry 读取不需要模型或 Research 凭证，因此历史包可以离线检查：

```bash
uv run agent-world --config /path/to/config.toml registry list --status released
uv run agent-world --config /path/to/config.toml registry inspect PACKAGE_ID VERSION
```

启动、检查和恢复 Expansion：

```bash
uv run agent-world --config /path/to/config.toml expand start \
  --campaign-id 'campaign:inventory-coverage-v1' \
  --anchor 'env:BOUNDARY_HASH@1.0.0' \
  --target tool_semantics \
  --target transition_constraints \
  --source 'source:tool-ecosystem' \
  --source 'source:random-theme' \
  --policy evolutionary-archive
uv run agent-world --config /path/to/config.toml expand inspect \
  'campaign:inventory-coverage-v1'
uv run agent-world --config /path/to/config.toml expand resume \
  'campaign:inventory-coverage-v1'
```

`--campaign-id` 必填，并且必须在任何 Source/Agent/Web 外部工作开始前选定；它是 durable
idempotency、single-writer lock 和 crash recovery identity，不是事后生成的日志标签。`--anchor` 可
重复，解析后绑定 Registry 的精确 released manifest；`--inbox-revision` 接受 generate 结果中
ExpansionInbox 的精确 Artifact revision。`--source` 可重复；省略时使用 `default_source_ids`。
Campaign 冻结 Pool、Inbox、SourceCatalog、Source requests/results、clue snapshot、OperatorCatalog、
Policy 参数、权限、预算、可选 feedback 和 release profile；Policy 只能 ask/tell，不能授权 parent、
修改 Judge 或发布。

可选训练/评测反馈先绑定精确 SuiteSnapshot，且只能写封闭的聚合统计：

```bash
uv run agent-world --config /path/to/config.toml feedback record SUITE_SNAPSHOT_ID \
  --signal '{"signal_type":"coverage_gap","capability_dimension":"refund_compensation","sample_count":24,"confidence":0.85,"gap":"low_success","severity":0.7}'

uv run agent-world --config /path/to/config.toml expand start \
  --campaign-id 'campaign:feedback-guided-v1' \
  --anchor 'env:BOUNDARY_HASH@1.0.0' \
  --target tool_semantics \
  --source 'source:capability-gap' \
  --feedback-revision 'sha256:FEEDBACK_ARTIFACT_REVISION'
```

第二条命令要求配置目录中确实存在 `source:capability-gap`。`feedback record` 返回的
`feedback_ref.revision_id` 才是 `--feedback-revision` 的值。输入 schema 不接受 raw task、trajectory、
instruction、EvaluatorGoal、Verifier IR、sealed case、expected answer 或 Oracle；Artifact 还会复验
SuiteSnapshot id/digest。Source 只能看到 suite digest 和 aggregate signals，看不到 feedback 的 audit
evidence 内容。所有业务结果是单行 JSON stdout；错误是单行 JSON stderr。`generate` 发布成功返回
0，真实执行但未发布返回 2，配置/基础设施失败返回 1，中断返回 130。
