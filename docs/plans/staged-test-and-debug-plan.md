# 分段测试 + Bad-case 调试执行计划（codex 直执版）

> 状态（2026-07-24）：待用户审批后交 codex 执行。
> 服从 `refactor-plan-calibration.md` 的北极星与证据纪律；本文只定义**测试与调试的执行顺序和验收**，不改产品合同。
> 本文的最高目标：让 codex 能**分段**定位并修复失败，而不是对整条 e2e 盲跳打转。

## 北极星红线（任何一步都不得违反）

1. 生成的环境是确定性、不撒谎、可执行的 RL 训练环境；状态转移由生成的**代码**拥有，绝不由 LLM 文本/mock/模板/固定回放充当成功路径。
2. **捕获的上游 commit 只能当"输入"注入，目标节点必须真跑出自己的结果**；绝不把捕获到的目标节点历史输出回放当作本次成功。违反即 DRIFT。
3. 不靠加 retry、扩张 prompt、放松 Gate、人工补 Artifact 来"推进"。放松验证让它过 = DRIFT。
4. 密钥/base URL/auth/sealed verifier/带凭证 transcript 绝不进任何 artifact/日志/trace/包。

## 为什么这样测（证据）

22 个真实 bad-case 的位置分布证明：管线**几乎每次都死在语义层这堵墙前**（BC-01：7 个 hotel run 全部死在 Build 之前；语义层簇 BC-13/14/17/44/47…），而 Build→Judge→Registry **几乎从未在真实上游输入上执行过**（只有 BC-07/08 勉强碰到）。
所以下游不是"有 bug 但测不出"，而是**从未被真正执行、是黑箱**。不分段，下游永远碰不到 → 必须先分段、后 e2e。

## 给 codex 的反打转硬规则（元层，最重要）

- **禁止整条 e2e 盲跳调试。** 未完成 T0/T1/T2 之前，不允许用"跑一次完整 generate 看它死哪"作为调试手段。
- **一次只在一个节点/一个段内工作。** scope 收窄到单节点 + 其冻结契约 + 单点复现。
- **每次修改前先分类**（见"Bad-case 分类路由表"）：code bug / 契约输入不全 / hole 欠定义 / 预算·基础设施——四选一，写进日志。分类错则后续全错。
- **进展仪表 + 停止条件**：跨调试迭代追踪未闭合 issue 的 frontier。若连续两次迭代 frontier 没有严格缩小，或出现 A→B→A 震荡 → **立即停手，写根因诊断，换打法**，不得再补增量补丁。
- **失败是合格结果**，前提是它有精确 owner + 可复现证据或明确的下一条判别证据；不得把失败重命名为"完成"。

## LLM 调用地基（执行前必须认清，避免散落 SDK 调用）

- **现状**：全项目 LLM 调用现在只有一条路径——`InvocationBackend` 是 Protocol（`invocation/contracts.py:389`），唯一实现 `CodexSdkBackend`（`invocation/codex_sdk.py:74`）→ `openai_codex.AsyncCodex` SDK + sha256-pin 的 `codex_bin`。裸 OpenAI SDK / `chat.completions` 旁路零命中。
- **T0.5 后**：变为**两个实现在同一 Protocol 后面**——`CodexSdkBackend`（agentic）+ 新 `DirectLlmBackend`（单发结构化）。**所有 LLM 调用仍走 `InvocationBackend`，不许散落裸 SDK 调用**（守 AGENTS.md）。任何调试都不得绕过 `.invoke()` 直打 HTTP——裸 curl 只验 gateway 连通，不代表项目能跑。
- **项目一致的模型可调用性验证 = `agent-world doctor`**（`--live-agent` 才真花一个 Codex turn，走真实 SDK 路径），不是 curl。前提：gitignored 私有 config 填 `model=grok-4.5` + 真实 `codex_bin` + env 变量名 `OPENAI_API_KEY`/`OPENAI_BASE_URL`（值在 bashrc，绝不进 tracked 文件）。
- 模型：首选 `grok-4.5`（网关实测路由到 free 档，e2e 注意限流/额度）；不可用才显式切 `gpt-5.4-mini`。

## 执行环境已验证状态（开跑前确认）

- **无需 `codex_bin`**：`agent-world doctor` 的 `codex_runtime` 用 SDK-bundled `codex-cli 0.144.4` 通过；私有 config 不填 `codex_bin`（省去版本对齐）。已验证 config：`.agent-world-live/doctor-grok45/config.toml`（gitignored，凭证仅 env 变量名）。
- **模型可调用性已验**：`doctor --live-agent` 用 `grok-4.5` 真实 turn 通过（走 `CodexSdkBackend`，项目一致路径）。
- **本机隔离（T2 前提）依赖内核开关，重启会失效**：Judge/Build 用 `/usr/bin/bwrap`（`judge/supervisor.py:343-385`）执行**不受信任的生成代码**，需要 user namespace 才能建沙盒。Ubuntu 默认 `kernel.apparmor_restrict_unprivileged_userns=1` 会挡住它，`judge_isolation`/`clean_build` 报 `IsolationUnavailable: bubblewrap ... cannot create the required isolation namespaces`。
  - 当前已临时放开为 `=0`，doctor 全绿（`local_execution_ready: true`）。**这是 `sysctl -w`，电脑重启后回到 `=1`**。
  - **若 T2 撞到 `IsolationUnavailable`：不是代码 bug，是重启后开关复位。** 处理：请用户重跑 `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`（或永久版 `/etc/sysctl.d/99-userns.conf`），再 `unshare --user --map-root-user echo userns-ok` 确认，然后继续。**绝不因隔离不可用就放松/跳过 Judge——那是北极星 drift。**

## 角色 ↔ skill ↔ 节点映射（提示词/skills 按角色重构，不是笼统"改提示词"）

严格三角色，无 ambient/fallback（`agent_profiles.py:42` `IsolatedAgentProfileProvider`）。每个 profile = 框架 `base_instructions` + `developer_instructions`(=对应 SKILL.md) + 按角色的 `reasoning_effort`（`:323-330`）。

| 角色 profile | skill 文件（提示词载体） | 覆盖节点 | 本计划相关 |
|---|---|---|---|
| `researcher` | `agent_assets/skills/research-world-evidence/SKILL.md` | Research/Discovery | T3 前缀，通常不是墙 |
| `environment-engineer` | `agent_assets/skills/engineer-agent-world/SKILL.md` | **语义层 Arch/ToolSemantics/Rules/Curriculum + Build 代码/修复** | **T1 墙 + T2 Build 的提示词修法都在这里** |
| `challenger` | `agent_assets/skills/challenge-agent-world/SKILL.md` | Judge/Verifier 数据 | T2 Judge/Verifier 的提示词修法在这里 |

**提示词/skills 是合法的一等修复手段**（不是只能代码硬编码）：当分类结论是"约束/上下文欠定义"（如 BC-17 batch 过大、上下文未冻结），修法可以是**重构对应角色的 SKILL.md**（集中、可控，优先于改散落 inline `instructions=`）。但——
- **红线不变**：提示词重构同样不得放松 Gate、不得抬 retry、不得用散文求模型"别乱走"来掩盖结构缺陷；结构性约束（typed-hole/冻结 catalog）优先于文字性约束。
- **时机**：提示词改动**必须在 T0 试车台上秒级验证收敛**，绝不允许"改一版 SKILL.md → 跑整条 e2e 看效果"——那是盲跳。没有 T0 之前不先盲改提示词。
- **按角色定位**：改 T1 语义层 → 只动 `engineer-agent-world`；改 Judge → 只动 `challenge-agent-world`。不跨角色混改。

## 阶段总览

- **T0**：建单节点试车台（**在原 scope 的 state_root 副本里就地重跑目标节点**）。这是分段测的唯一前提。
- **T1**：分段测「墙」——语义层节点（case 最多，修复重心）。
- **T2**：分段测「墙后」——Build→Judge→Registry（从未跑过，探明未知）。**T2 依赖一个捕获到的合法语义 commit 作输入；该 commit 几乎不存在（见 CLAIM A），故 T2 排在 T1 之后或以找到该 commit 为前提，不与 T1 并行。**
- **T3**：仅当 T1、T2 各自稳定变绿，才接起来跑真实 e2e。

## T0 — 单节点试车台（前提，先做）

**目的**：把"发射整枚火箭看它第几级爆炸"换成"单级试车"。让任一节点能在秒级、可反复地跑。

**机制（经 review 纠正——"注入闭包"行不通，改为"原 scope 就地重跑"）**：
- `resolve_inputs`（`work_scheduler.py:539-558`）**不吃注入的 consumer_refs**——它对每个 parent `read_head`、要求 `status=="committed"`、再 `require_active_commit`，只认 durable 已提交的 head。所以无法"喂"输入。
- `coordinate_key = sha256(含 scope_id 的 json)`（`work.py:192-207`）——换 scope_id 会让所有坐标 key 全变，故不能拷 head 到新 scope。
- `snapshot()`（`work_scheduler.py:202-243`）只在 parents 都 active 时才标 committed → 整条祖先闭包都须作为已提交 head/attempt/commit 存在；group/shard 目标还要 child commit。
- **结论**：test-node 必须**复制原 scope 的 state_root**（祖先 head/attempt/commit 全在、coordinate_key 匹配），只 supersede/清掉**目标坐标自身**的 head，让它按原 graph/manifest/runtime 重新 `dispatch_one`。

**积木（已确认存在）**：
- `work_store.py:182` `read_head(coordinate)`；`work_scheduler.py:345` `dispatch_one(...)`；`snapshot()`（:180）。
- supersede 目标 head：复用 `supersede_stale`（`work_scheduler.py:396-407`）/ `reactivate_historical_commit` 的反向——只对目标坐标。
- `direct_runner.py:649` `_leaf_executor` + `_bootstrap/_design/_final_executors` → 单 leaf 执行器构造。

**要做的**：新增 CLI `agent-world test-node <scope_id> <target_coordinate>`（与 `observe`/`run` 平级）：
- 行为：把 `<scope_id>` 的 state_root 复制到 gitignored `.agent-world-live/test-node-<ts>/`；在副本里只把 `<target_coordinate>` 的 head supersede 掉；`dispatch_one` 让该坐标重跑，真实 InvocationBackend；祖先 commit 原样保留当输入。
- 输出：目标节点 ValidationReport + scene + token/tool/process usage，**全部标 `diagnostic_only=true, releasable=false`，绝不喂 Registry**（守跨-scope-复用红线，校准 P1.3 / line 73）。

**红线校验（fail-closed）**：只 supersede 目标坐标自身的 head，祖先 head **只读当输入、绝不回放目标坐标的历史输出**当结果。若副本 scope 缺目标的完整祖先闭包（某 parent 非 committed）→ 报 `missing_ancestor_closure` 并停，绝不伪造可跑。group/shard 目标须连同其 child 坐标一起处理。

**验收（确定性，大部分不需真实 run）**：
- 单测：给定有完整祖先闭包的 fixture scope 副本，`test-node <coord>` 只 supersede 目标 head、调 `dispatch_one` 恰好一次、只针对该坐标。
- 单测：某 parent 非 committed → 抛 `missing_ancestor_closure`，不执行。
- 单测：目标输出标记 `diagnostic_only/releasable=false`，且不写入任何 Registry/发布路径。
- 冒烟：对一次真实语义层失败的 scope 副本跑 `test-node`，秒级拿到真实 ValidationReport（可失败，但必须"真跑出来"）。

**停止条件**：若无法在不回放目标输出的前提下就地重跑 → 停，写诊断：是祖先闭包不完整、还是 executor 构造缺依赖。不得为"能跑"放宽红线。

## T0.5 — 双 backend：agentic 走 codex，单发结构化走直连 LLM

**目的**：纯打分/评估/提取这类单发结构化调用，不该起 codex_bin 子进程走整套 agent 握手（繁琐、慢）。加一个轻量直连 backend，但仍在同一 Protocol 后面（不散落 SDK 调用）。

**做的**：
- 新增 `DirectLlmBackend`（实现 `InvocationBackend` Protocol），用官方 `openai` SDK `AsyncOpenAI` → 同 gateway（`OPENAI_BASE_URL`/`OPENAI_API_KEY`）→ `response_format` 走 `json_schema`（复用 `output_schema`）。
- **路由**：节点声明 `allowed_builtin_tools=()` 且无多轮需求 → `DirectLlmBackend`；否则 → `CodexSdkBackend`。
- 首批迁移候选（单发结构化）：`designer/one_shot.py:231`、`judge/compiler.py:483/1266`、`designer/service.py:5464/6208`。**agentic 的 `run_structured_agent` / reachability 多轮 solver / builder 代码生成保持 codex，不动。**
- telemetry/redaction/budget 在 Protocol 边界上，两 backend 共用，不改。

**分数/评估的场景化规则（不可动的北极星 + 看场景）**：
- **不可动**：**生成出来的环境自身**的状态转移 / reward / verifier 逻辑——永远是代码，永远不是 LLM 分数。与"打分场景"无关，任何时候不松。
- **能确定性判定的 → 硬编码，不用 LLM**：schema/handshake、可达性（真实执行）、property/公式化、数值阈值。代码能算却用 LLM = drift。
- **纯语义、无确定性等价物的 → LLM 分数是合法信号**（不只是 advisory）：如"设计是否忠实反映需求""证据相关性""描述质量"。但必须①标注为语义判断（AdvisoryCheck 类，不许伪装成确定性 Gate）②有界、可计量（挂 budget）。

**验收**：
- `DirectLlmBackend` 有单测：单发 `json_schema` 结构化输出、无工具、无子进程；与 `CodexSdkBackend` 满足同一 Protocol 契约。
- 路由单测：`allowed_builtin_tools=()` 节点走直连，agentic 节点走 codex。
- 迁移后的节点保持原有 ValidationReport 语义；无散落裸 SDK 调用（`grep` 证明 openai client 只在 `DirectLlmBackend` 内）。
- 任何 LLM 语义分数在因果链里标注为语义判断，且不单独拥有 release/state-transition 决定。

**停止条件**：若某"看似单发"的节点其实需要工具/多轮 → 不迁移，留在 codex，写明原因。不得为省事把 agentic 节点强塞直连。

## T1.0 — 实测暴露的第一堵墙：backend/transport 失败被误分类成"设计缺陷"（最先修，当前 41 次 test-node 都死在这）

> 状态（2026-07-25，本机 test-node 实测，非纸上推断）。证据目录：`.agent-world-live/test-node-20260725T060615Z-*/`（telemetry.sqlite + observability/scene.md）。

**现象**：最新一次 `test-node` 卡在坐标 `design.world_behavior.tool_semantics_batch` [Designer] attempt 2，`Reason: thrashing`、`Progress: no_progress`、`Repair authority: none`。gate = `agent_backend_direct_structured_output_invalid_json`，scene 渲染 `Repair target: design_worldspec` / `Next action: review_design_worldspec`。

**实测数据（telemetry）**：`invocation.tokens.output=16723`、`reasoning_output=9017`、`total=36387`，**远低于** `structured_turn_token_limit=65536`；span 跑 286.8s。→ **不是 token 超限**（与 codex-branch 那次 `turn_failed_provider_rejected` 的预算超限根因不同）。

**独立探针反证（同网关同 grok-4.5，直连 Responses `text.format=json_schema strict`）**：
- 小 schema（`{status:ok}`）→ `completed`，合法 JSON。
- 中 schema（6 工具、长描述）+ 紧预算 `max_output_tokens=300` → `completed`、`incomplete_details=None`、3530 字符、合法 JSON。
- → **网关/模型对 strict json_schema 是支持且稳定的；截断假设也不成立。** 偶发 `invalid_json` 是 transport 层规模相关的偶发故障，不是模型不会。

**根因链（已逐行核对）**：
1. `direct_llm.py:346-357`：grok-4.5 返回 `completed` + 非空 `output_text`，但 `json.loads` 失败 → `error.code="direct_structured_output_invalid_json"`、`succeeded=False`。**backend 层判定本身诚实、正确。**
2. `designer/one_shot.py:268-281`：`not result.succeeded` → 抛 `LeafExecutionFailure(code="agent_backend_direct_structured_output_invalid_json", category="the Agent backend returned a non-success terminal result")`。
3. 该 leaf failure 冒泡成同名 gate，scene 投影出 `repair_target=design_worldspec` / `review_design_worldspec`。
4. **但这是 backend/transport 失败，根本不是设计缺陷。** scene 却让 codex"去改 WorldSpec 设计" → codex 改设计 → 下轮同一 backend 仍偶发坏 JSON → 同一 gate → **thrashing 打转**。这就是"永远修不好"的活样本：**误分类（transport↔design）+ 误路由（repair_target）叠成死循环**，正对 Bad-case 路由表的"误分类"行。

**要做的（按证据，不放松任何 Gate）**：
- **A. 分类修正（核心）**：`agent_backend_direct_structured_output_invalid_json` 这类 **backend/transport 终止**绝不能映射成 `repair_target=design_worldspec`。它属于 infrastructure/transport lane，`repair_target` 应是 `needs_human` 或 backend-retry，**不得引导 codex 去改冻结设计**。定位 leaf failure code → scene `repair_target` 的映射表，把 backend/transport 码单独归类。
- **B. transport 偶发的有界重试（不是放松，是对齐语义）**：既然实测同条件多数成功、偶发失败，`direct_structured_output_invalid_json` 应是**有界 retryable**（backend 层单发重试 N 次），而非直接终态。但——**红线**：重试上限有界、计入 budget；重试仍失败才终态 `needs_human`；**绝不靠无限 retry 或放松 schema 校验蒙混**。
- **C. 可复现证据**：这条是 backend/transport 层，可用**确定性 regression** 复现——构造一个 `InvocationResult(status=COMPLETED, structured_output=None/坏JSON, error.code="direct_structured_output_invalid_json")` 喂 `one_shot.py` 的失败路径，断言：①不产生 `repair_target=design_worldspec`；②归入 transport/infra lane；③有界重试后才 `needs_human`。**不需真实 run 即可验主干**（真实 run 仅用于确认偶发率）。

> **交付状态（2026-07-25）：A + C 已完成。** 关键发现:运行时**早已**权威区分两条 lane——`_finish_exception`(`leaf_executor.py:850`) → `ValidationReport.status="error"`(基础设施/transport,leaf 未产出提案) vs `_finish_validation_failure`(`:661`) → `status="failed"`(真提案被语义拒绝);`work_runtime.py:2584` 据此选 `infrastructure_retry` / `local_correction`。缺口只在**投影层没把这个信号传上来**,于是 `scene.py:_repair_target` 只能靠 `pipeline_stage=="Designer"` 粗判 → transport 失败被指向冻结 WorldSpec。
> 修法(未猜 code 前缀、未加新判据):`SceneHead`/`CoordinateScene` 新增 `validation_status`(取 `report.status`);`RepairTarget` 增 `infrastructure_transport`、`NextActionHint` 增 `inspect_infrastructure`;`_repair_target` 在 Designer 分支**之前**判 `status=="error"`;`_next_action` 在 thrashing 分支**之前**判该 lane(否则 attempt≥2 会被吞成 `request_human_review`);`render.py` 输出明确"非设计缺陷、WorldSpec 冻结不可改"文案。
> **(B) 有界重试仍未做**——运行时已有 `allow_infrastructure_retry` 授权路径,B 涉及 backend 层重试语义,面更大,单独对齐后再动。

**验收**：
- 确定性 regression：backend transport-fail → scene `repair_target ≠ design_worldspec`，且不把冻结 WorldSpec 呈现为最可编辑对象（守北极星防漂移）。✅ `test_fold_routes_designer_transport_terminal_to_infrastructure_not_design` + 反向守护 `test_fold_keeps_genuine_designer_semantic_failure_on_design_lane`（真设计失败仍走 design lane，没把真缺陷弄瞎）。
- `test-node` 对该坐标重跑：不再 attempt 2 就 thrashing 死锁；transport 偶发被有界重试吸收，或诚实终于 `needs_human`（有精确 owner）。
- 观测层 scene 对同一失败给出**正确 lane 的 next_action**（不再 `review_design_worldspec`）。

**停止条件**：若发现 `invalid_json` 其实高频（非偶发）→ 那才可能是 schema/prompt 规模问题，转 T1 语义层按 batch 尺寸/上下文冻结处理；但**在坐实高频之前，不得先改设计**——先修分类与路由，避免继续打转。

## T1 — 分段测「墙」：语义层节点

**战场**：语义层是 case 最密处。已知复现簇（用作 T1 的 regression 种子）：
- **BC-44（误分类，最先修，纯确定性可测）✅ 已交付（2026-07-25 复核通过）**：完整 ToolSemantics provider rejection 被分类成 generic **retryable** infrastructure → 每个物理 batch 白跑一次相同重试；且失败的 Direct request 不得被当 release evidence 恢复。修法：已知安全终止码 `turn_failed_provider_rejected`（`_codex_worker.py:197/232`）到达 Scheduler 时必须是 **non-retryable**，即使 backend 在 `:712/729/752` 通用地设了 retryable flag。**加确定性 regression 即可验，不需真实 run。**
  - 现状：`designer/one_shot.py:66` `_NON_RETRYABLE_BACKEND_TERMINAL_CODES = {"turn_failed_provider_rejected"}`，`:280` 据此设 `retryable`。regression 已在库：`test_one_shot_marks_provider_contract_rejection_non_retryable` + `test_bc44_provider_rejection_cannot_authorize_a_scheduler_retry`（后者正是"到达 Scheduler 仍不得授权重试"这一层）。
  - **T0 harness 同步复核**：`agent-world test-node` CLI 已实装（`cli.py:97-128`、`control/test_node.py`），10 条测试覆盖"只重跑目标坐标/诊断产物不得进 Registry/祖先闭包缺失即 fail-closed/取消即终态"。T0 与 BC-44 合计 26 passed。
- **BC-47（与 BC-44 解绑，不是纯确定性）**：其 required_regression 明写"only a fresh request may assess the reduced representation"——所以 BC-47 的 compact-alias→冻结 Rule binding 解析**需要一次真实 run 验收**，不能跟 BC-44 一起当"无需真实 run"。放在 BC-44 之后、T1 有真实 run 能力时做。
- **BC-14（诊断丢因果）✅ 已交付（2026-07-25）**：整 Rule 编译要保留 tool/rule/clause/term 路径，canonical validator 发稳定 code，diagnostic 前缀保留 retryability/violated condition/expected category——不得塌成 `framework_diagnostic_incomplete`。
  - **实测根因（已复现）**：`designer/models.py` 的语义 validator 抛**裸 `ValueError`** → Pydantic 记为 `value_error` → `control/validation.py:287-300` 塌成 `framework_diagnostic_incomplete`，`actionable_for_agent=False`，真实 violated condition 被通用文案替换 → Agent 拿不到可修identity。（`contracts/world.py` 早已用 `PydanticCustomError` 的正确写法，`models.py` 只迁移了一半：修前 11 处 typed / 47 处裸 ValueError。）
  - **修法（补完既有约定，未发明新机制）**：`models.py` 全部 47 处裸 `ValueError` → `PydanticCustomError` + 稳定域前缀 code；`validation.py` 新增 `_DESIGNER_SEMANTIC_CONTRACTS` 单一真源表派生 `_SAFE_VIOLATED_CONDITIONS`/`_SAFE_EXPECTED_CATEGORIES`（含 per-role/per-label 动态 code）。**Agent 输入值绝不进 code/message**（world-closure 的 unknown/unreachable id 已改为不回显，仅靠 code+path 定位）。
  - **验收证据**：`test_bc14_designer_semantic_validators_keep_a_repairable_identity`（4 参数化 case）断言 stable code + 真实 violated_condition + expected_category + `actionable_for_agent=True` + 绝不含 `framework_diagnostic_incomplete`；原有"裸 ValueError 仍必须 non-actionable"的守护测试保持通过（未放松验证）。
- **BC-17（有界进展后仍终止 + batch 过大）✅ 复核已满足（2026-07-25，代码核实非推断）**：两次修正后进展奖励仍终止；靠**物理 batch 变小 + 冻结上下文**让新 batch 收敛，**不抬 retry ceiling**。
  - **batch 物理尺寸**：`designer/models.py:61-62` 已是 `MAX_TOOLS_PER_SEMANTICS_BATCH = 2`、`MAX_SEMANTICS_BATCHES = 4`（`:1625-1627` 注明新 plan 机械按两工具上限发出，更宽的 decoder 仅用于诊断模式读捕获的祖先闭包）。
  - **4 态 lattice 已实现**：`control/work.py:classify_progress`（:1461）返回 `resolved/strict_progress/unchanged/oscillating/regressed/unknown`；**"推进"这一态已覆盖**——`:1528-1531` 当 `frontier_ordinal` 上升且新旧 blocker 不相交时判 `strict_progress`（正是 BC-17 的 shape-frontier 10 → semantic-frontier 30 不该误停的场景），`:1519-1527` 覆盖同 frontier 下暴露下一批兄弟义务，历史态集合判 `oscillating` 挡 A→B→A。
  - **未抬 retry**：奖励走 `work_repair.py:168-173` 的 `strict_progress_bonus_corrections`，且必须上一次 outcome 为 `progressed` 才发放（`repair_progress_bonus_denied`），仍受 `maximum_total_repair_attempts` 与 `repair_no_progress_terminal` 约束。
  - **旁证**：`work_repair.py:175` 的 `infrastructure_retry_requires_error_report` 说明运行时的基础设施 lane 本来就以 `report.status=="error"` 为权威判据——与 T1.0-A 在投影层补上的 `validation_status` 完全同源，不是新发明的判据。

**执行顺序**：先 BC-44（纯确定性、堵误分类地基）→ BC-14（诊断保真）→ BC-17（batch 物理尺寸 + 冻结上下文）→ BC-47（需真实 run，最后）。

**每个 case 的动作**：用 T0 的 `test-node` 对语义层坐标反复跑；按分类路由表定位 owner；修法二选一由分类决定——(a) **改结构/分类/诊断代码**，或 (b) **重构 `engineer-agent-world/SKILL.md`**（当分类为"约束/上下文欠定义"时）。两者都必须在 test-node 上秒级验证收敛；都不抬 retry、不放松 Gate、不用散文掩盖结构缺陷。

**验收**：
- 每个 BC 有一条 **failing→passing 的确定性 regression**（无 regression 只能记 hypothesis）。
- 语义层节点在 `test-node` 下能从真实上游输入**稳定跑出合法语义 commit**（真跑，非回放）。
- 进展用 **4 态 lattice** 判定，不是"严格收缩"（校准 line 71 明确 BC-17 的 10→30 是真进展，严格收缩会误停）：
  - **收缩（shrink）**：未闭合 issue 数下降 → 真进展。
  - **推进（advance）**：issue 数上升但暴露的是更精确的新问题（如 BC-17 shape-frontier 10→semantic-frontier 30）→ 真进展。
  - **回退（regression）**：已解决的问题复现 → 非进展，停。
  - **A→B→A 震荡**：同一 issue 在两稿间来回 → 非进展，停。

**停止条件**：判定为 regression 或 A→B→A → 停，判定是"业务语义跨 hole 耦合、非单点可修"还是"欠定义需结构化 scaffold"，写诊断再决定，不得继续补丁。另设 **per-test-node token/turn 上限**（挂 RepairLedger/RepairPolicy）：单节点单次调试超限即停，防语义节点烧 50k–98k（BC-02/BC-17）。

## T2 — 分段测「墙后」：Build → Judge → Registry（排在 T1 之后，或以找到合法语义 commit 为前提）

**前置（review 纠正）**：T2 需要一个**捕获到的完整合法语义 commit**作输入，而 CLAIM A 证明这几乎不存在（只有 BC-07 勉强到过 Build，其合法性还未证）。所以 **T2 不与 T1 并行**：要么先在历史 `.agent-world-live/*` 里定位并验证一个完整合法语义 commit（找到即可基于它跑 T2），要么等 T1 让语义层能稳定产出合法 commit 后再做。**第一步动作 = 定位/验证该 commit；找不到就明确 T2 阻塞在 T1 之后。**

**理由**：这些节点几乎从未在真实上游输入下执行过，是黑箱。用 T0 就地重跑机制（复制含**合法语义 commit** 的 scope 副本、只 supersede 下游目标坐标），让下游真跑，第一次探明它们能不能通。

**已知种子**：
- **BC-07**：Builder 跑 ~896s 无首写。验收：真实 Builder 暴露 first-progress/first-write，到达**有界终止**（prompt 成因暂列 hypothesis）。
- **BC-08**：Integration 与 final Judge 对同一 Candidate 重复确定性/public 检查。验收：digest-bound Integration evidence 可复用，final 只做**额外独立**检查（reachability/property/sealed/fresh deployment）。

**动作**：`test-node` 依次就地重跑 Build、Judge、Registry（scope 副本含合法上游 commit，只 supersede 各自目标坐标）；记录各自能否到达有界终止、真实 usage、是否有新的未知失败。

**验收**：
- Build 有 first-write SLA 且有界终止；Judge/Integration 独立性用 exact evidence key 表达；Registry 能对未知 seed/task 做 RPC Reset/Step 冷启动。
- 每个下游节点至少有一次"真跑出结果"的证据（成功或诚实有界失败）。

**停止条件**：下游出现无 owner 的失败 → 终止为 framework/infrastructure diagnosis，不得靠加 turn/放松 Gate 掩盖。

## T3 — 真实 e2e（仅在 T1、T2 各自变绿后）

新请求「用户预订宾馆」经真实 Search/Fetch/Extract、真实模型（首选 `grok-4.5`，key/base URL 从环境变量 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 读，均在 bashrc；额度/兼容不可用才显式切 `gpt-5.4-mini`）、真实 Builder/Judge 子进程 → 到达原子 Registry released，保留完整 Artifact/Span/usage 闭包。
e2e 若炸：立即用分段结论判定是**段内回归**还是**段间接口**问题——因为 T1/T2 已各自证过，这时不再是盲跳。

## Bad-case 分类路由表（每次失败先查这张表）

| 分类 | 判别特征 | owner / 修法 | 明确禁止 |
|---|---|---|---|
| 诊断/输入表示丢失 | validator 错误塌成 generic root issue、丢 path/code/category（BC-03/14） | 保稳定 code、保路径、保 retryability | 把 raw validator 错误直接喂模型 |
| 误分类（provider↔infra↔semantic） | provider rejection 当 retryable infra；或 infra terminal 当语义失败（BC-44/45/47） | 修分类映射，安全终止码 non-retryable | 由 telemetry 外观推断越权 retry |
| 控制/拓扑/预算 | 多处各自持 retry/budget；重叠控制环（BC-06/09/17） | 单一 Scheduler/ledger/budget authority；缩物理 batch | 抬 retry ceiling、扩 prompt |
| hole 欠定义 vs 业务耦合 | frontier 两次不缩 / A→B→A | 可证明冻结的机械字段 → 移入 catalog 代码派生；耦合业务语义 → 保持单原子 proposal | 把耦合语义强拆成"独立 hole" |
| 约束/上下文欠定义（提示词层） | 模型输出漂移/超预算/漏约束，但契约与代码正确（BC-17 类） | 重构**对应角色**的 SKILL.md（语义层=`engineer-agent-world`，Judge=`challenge-agent-world`）；结构性约束优先；test-node 验证收敛 | 跨角色混改、用散文求"别乱走"、借机放松 Gate/抬 retry |
| 真实执行/成本 | Builder 无首写、Integration 重复检查（BC-07/08） | first-write SLA、exact-key evidence 复用 | 把未 live 量化的节省当已实现 |

## 每次真实运行的最小报告

request id、Git revision、plan/config/profile digest、model、各 stage Artifact refs、actual/unknown/reserved usage、每次 RepairAction、frontier transitions、Registry/consumer 结果、停止原因。
禁记：密钥、base URL、原始 prompt/transcript、sealed case、EvaluatorGoal、expected state。

## 交付顺序小结（codex 照此推进）

1. T0 harness（就地重跑机制 + 4 条确定性单测）→ 用户可见的"单节点可跑"证据。
2. T1-BC44 误分类（纯确定性 regression，最先，地基）。
3. T1-BC14 → T1-BC17 → T1-BC47（BC47 需真实 run，最后）；语义层稳定产出合法 commit。
4. T2：定位/验证一个合法语义 commit → 就地重跑 Build/Judge/Registry 探明（排在 T1 后，不并行）。
5. T1、T2 均绿 → T3 真实 e2e。
6. 全程遵守反打转硬规则 + 4 态 lattice + per-node token 上限；每阶段写最小报告；push 与 git commit 仅在用户明确同意后。

## 当前真实交付前沿（2026-07-25，逐条代码/测试核实，非推断）

| 项 | 状态 | 证据 |
|---|---|---|
| T0 test-node harness | ✅ 已交付 | `cli.py:97-128` + `control/test_node.py`；`test_test_node.py` 10 条（含 fail-closed / diagnostic-only 不进 Registry） |
| T0.5 双 backend | ✅ 已交付 | `invocation/direct_llm.py:43` `DirectLlmBackend` + `invocation/routing.py:82` 按 `allowed_builtin_tools` 路由 |
| **T1.0-A/C 误分类+误路由** | ✅ **本轮交付** | `validation_status` 贯通 projector→scene；新增 `infrastructure_transport` lane + `inspect_infrastructure`；2 条 fold regression（正向+反向守护） |
| T1.0-B 有界重试 | ⛔ 未做（有意留待单独对齐） | 运行时已有 `allow_infrastructure_retry` / `work_repair.py:174-176` 授权路径，改动面大 |
| BC-44 provider rejection | ✅ 已在库 | `one_shot.py:66/280` + `test_bc44_provider_rejection_cannot_authorize_a_scheduler_retry` |
| **BC-14 诊断保真** | ✅ **本轮交付** | `models.py` 47 处裸 ValueError → typed `PydanticCustomError`；`validation.py` `_DESIGNER_SEMANTIC_CONTRACTS` 派生双映射；4 条参数化 regression |
| BC-17 batch + lattice | ✅ 复核已满足 | `models.py:61-62`（2 工具/批）；`work.py:1461` `classify_progress` 含"推进"态 `:1528-1531`、`oscillating` 挡 A→B→A |
| 可观测 hook 进 Claude Code | ✅ **本轮交付** | `.claude/hooks/observability_hint.py` + 接入 SessionStart / UserPromptSubmit；正反两路已验（有失败 job 吐 scene 指针，否则静默） |
| BC-47 compact-alias | ⛔ 未做 | 其 required_regression 明写需一次**真实 run**，排在最后 |
| T2 下游探明 | ⛔ 阻塞 | 需一个**捕获到的合法语义 commit** 作输入（CLAIM A：几乎不存在），须先由 T1 稳定产出 |

## T1.0-D — 真实 run 暴露的第二堵墙：诊断克隆自我毒化（已修，这才是"41 次全失败"的直接原因）

> 状态（2026-07-25）：真实 `test-node` 跑出来的，不是纸上推断。证据目录 `.agent-world-live/test-node-20260725T085900Z-e3fb8fb340db/`。

**现象**：`test-node` 在**调用模型之前**就死：`WorkResumeError: terminal Work evaluation does not block readiness`（`work_scheduler.py:296`，由 `snapshot()` 抛出）。

**根因链（逐层核到 artifact 内容）**：
1. `work_scheduler.snapshot()` 有不变量：任何 terminal head 的 evaluation 必须 `readiness_effect ∈ {blocks, invalidates}`。
2. 但 `FeedbackEvaluation` 的校验器（`work.py:1053`）**强制**：`diagnostic_only` 为真时 `readiness_effect` 必须是 `observes`（诊断裁决无权阻塞它克隆自的图）。产出点 `work_runtime.py:1840`。
3. 于是**诊断克隆里只要有一个节点终止（如 budget exhaustion），`snapshot()` 就再也建不起来 → 该 scope 里任何坐标都无法 dispatch**。克隆把自己毒化了。
4. 这解释了为什么此前 41 次 test-node 全部失败、证据目录里从来看不到"目标节点真跑出结果"——**它们根本没跑到模型**。

**修法（窄修，只在已验证的诊断态放开）**：`work_scheduler._diagnostic_terminal_blocks()` —— 当 `evaluation.diagnostic_only and not releasable` 且 `runtime.diagnostic_only` 且 `has_test_node_diagnostic_marker(heads.root)` 时，把该 terminal 视为本地 blocked。守卫条件**刻意照抄** `allow_diagnostic_ancestors`(`:169-177`) 的既有安全模式；正常发布 runtime 走不到该分支，严格不变量原样保留。

**验收（确定性 + 真实）**：
- `test_diagnostic_observes_terminal_does_not_poison_its_own_clone`：标记克隆里 `snapshot()` 可建、该坐标为 `blocked`。
- `test_unmarked_state_root_keeps_the_strict_terminal_readiness_invariant`：未标记 → 仍抛 `WorkResumeError`（放开范围不外溢）。

## T1.0 真实 run 验收结果（2026-07-25，`test-node-20260725T085900Z-e3fb8fb340db`）

**目标坐标 `tool-batch-2` 真跑并 committed** —— 41 连败后第一次。`ValidationReport.status=passed`、`issues=[]`、`agent_turns=1`、`llm_tokens=22110`。红线全守：`diagnostic_only=True`、`releasable=False`、commit 同样标记、`registry/index.json` 的 `releases: []`（未发布任何东西）、根目录有 `.test-node-diagnostic` 标记。

**scene.md 实测输出（T1.0-A 的直接验收）**：
```
Repair target: infrastructure/transport terminal, not a design defect. ... (editing them is DRIFT)
Next action: inspect_infrastructure
```
不再是 `Repair target: design_worldspec` / `Next action: review_design_worldspec`。**且它分类的是另一个 code（`agent_backend_direct_provider_unavailable`）**——说明修的是 lane 机制，不是只针对 `invalid_json` 一个码。

**四个分片的 lane 分流（证明有判别力，不是一刀切）**：

| shard | head | `validation_status` | `repair_target` |
|---|---|---|---|
| batch-1 / batch-2 | committed | passed | None |
| batch-4 | failed | **error** | `infrastructure_transport` |
| batch-3 | failed | **failed** | `design_worldspec` |

batch-3 是真语义失败（`schema_union_tag_invalid`，路径深至 `tools[0].state_transition.transition[0].clauses[10].equal.right.arithmetic.left`），仍正确留在设计 lane —— transport 修复**没有**把真设计缺陷弄瞎，与反向守护测试一致。顺带这也是 BC-14 诊断保真在真实数据里的实证（tool/rule/clause/term 路径完整）。

## T1.0-E — 同族的第二个误路由：提案自身语义缺陷被当成冻结设计缺陷（已修）

真实 run 暴露：batch-3/batch-4 的语义失败（`reliability_timeout_error_unknown`、`access_case_coverage` 等）本是**Agent 自己刚产出的提案内部自相矛盾**（引用了自己 `errors` 段没声明的错误码），但 `scene.py` 的 `pipeline_stage == "Designer" and head.issues → design_worldspec` 仍把它指向冻结 WorldSpec，`Next action: review_design_worldspec`。**这就是原打转机制换了一类失败重演。**

**判据（artifact 里的权威信号，非猜测）**——三种 evidence 精确对应三条 lane：

| evidence type | report | 含义 | lane |
|---|---|---|---|
| `control.leaf_failure_evidence` | `error` | leaf 未产出提案 | `infrastructure_transport` |
| `control.leaf_validation_evidence` | `failed` | 提案跑出来了，**自身**语义被拒 | **`proposal_semantics`（新）** |
| `control.parent_repair_route` 存在 | `failed` | leaf 明确把修复交上游 | `design_worldspec` |

`parent_repair_route` 仅在 leaf 显式声明 `parent_repair_target` 时提交（`leaf_executor.py:690`，Judge 在 `judge/leaf.py:494` 等处用），故"它不存在"等价于"在本坐标可修"。

**修法**：`SceneHead.routes_repair_to_parent`（projector 从 `report.evidence_refs` 求得）；`RepairTarget` 增 `proposal_semantics`、`NextActionHint` 增 `revise_proposal`；Designer 分支据该标志二分。

**验收**：`test_fold_routes_self_inconsistent_proposal_to_the_proposal_lane` + 反向守护改写为 `routes_repair_to_parent=True` 才走 design lane。**真实数据重投影验证**：`085900Z` → `error→infrastructure_transport` / `failed→proposal_semantics`；`091606Z` → 两个 `failed` 全 `proposal_semantics`（`next_action: revise_proposal`）。**现在没有任何捕获到的失败再指向冻结 WorldSpec**——这是对的，它们确实都不是设计缺陷。

## 语义失败的 owner 分类（提示词层，不是代码层）

按"先分类再修"的纪律核了两边：

- **代码是对的，不动**：`reliability_timeout_error_unknown` 要求 `timeout_error_code` ∈ 该工具自己 `errors` 段声明的码（`service.py:9523`）；`access_case_coverage` 要求"覆盖全部 frozen actor 的权限条件必须 `positive_and_negative`"（`:9332`）。约束确定性可判、诊断已 actionable + 完整路径。**确定性可判的约束就该留在代码里（北极星），不得为了让它通过而放松。**
- **提示词欠定义，这才是 owner**：`engineer-agent-world/SKILL.md` 里 `timeout_error_code` / `rollback_trigger_codes` / `conflict_error_code` / `retryable_error_codes` / `case_sensitivity` / `positive_and_negative` **命中全为 0**。模型不是不听话，是**从没被告知**。

**修法**：SKILL.md 新增两节 `Tool-semantics reliability closure`、`Tool-semantics access closure`，照既有约定写成"闭合契约 + 返回前机械自检"，不写散文式请求。顺带修掉 `test_effective_capabilities.py` 一条**陈旧断言**（期望 `"Never emit a nested \`key\`…"`，实际文本含 `key_binding_id` 子句）——改断言匹配真实文本，未削弱任何指引；该测试此前在本分支一直失败，现已全绿。

## 提示词修复的实测收敛（2026-07-25，按 plan 纪律用 test-node 单节点秒验，未跑 e2e）

**batch-4：7 条语义 issue → 0，committed。** 只改 SKILL.md（新增 reliability/access 两节闭合契约 + 返回前机械自检），**未动任何代码、未放松任何 Gate**。1 turn / 23781 tokens。红线守住（`diagnostic_only=True`、`releasable=False`）。这坐实了该类失败的 owner 确实在提示词层，不在代码层。

**四分片累积状态：`tool-batch-1/2/4` 已 committed，仅剩 `tool-batch-3`。** 补齐它即拿到完整合法语义 commit → 解锁一直阻塞的 T2。

**batch-3 的 owner 同样在提示词层（已核，非推断）**：其两条 issue 对应的契约在 SKILL.md 命中为 0——
- `schema_union_tag_invalid @ .../arithmetic/left`：`RuleArithmetic` 按其自身 docstring 是**刻意非递归**的（`contracts/world.py:156-168`），`left`/`right` 只能是 `RuleAtom`（constant / value_ref / lookup），不得嵌套另一个 arithmetic。SKILL.md 里 `arithmetic operand` 命中 0。
- `schema_too_short @ .../state_transition/transition`：`transition` 是 `min_length=1`（`models.py:1058`）。SKILL.md 里 `state_transition` 命中 0。
已在 `Tool-semantics Rule clause closure` 节补上这两条（非递归算术 + transition 非空）。

**transport 偶发率累积样本（供 T1.0-B 决策）**：已观测到 **3 次** `agent_backend_direct_provider_unavailable`（batch-4 第一次、batch-3 两次其一 `llm_tokens=0`，模型根本没应答），**0 次** `invalid_json` 复现。即 transport 抖动是 `provider_unavailable` 为主，不是当初推测的 `invalid_json` 为主。每次抖动都被正确分流到 `infrastructure_transport` lane（scene.md 实测），不再误导改冻结设计——**这正是 T1.0-A/E 的价值：抖动不再制造设计漂移压力**。是否做 T1.0-B 有界重试，可据此权衡（当前每次抖动的代价只是重跑一个节点，且已不会污染设计）。

**下一步建议顺序**：①`invalid_json` 偶发率现在可量化了（本次是 `provider_unavailable`，未复现 `invalid_json`）——多跑几次 batch-3/batch-4 收集偶发率，据此决定 T1.0-B 有界重试的必要性与上限；②batch-3 的语义失败已有精确 owner，可作为 T1 语义层第一个真实修复目标；③BC-47 / T2 仍按原顺序排后。

## T2 首次真实 e2e 探明（2026-07-25，`.agent-world-staged/t2-probe*`）

首次真实 `generate`（need = 简单 to-do list，config = doctor-grok45 派生、state_root 落 gitignored `.agent-world-staged`）。反馈环健康推进：Research 3 节点 + `world_architecture` + `shared_tool_semantics` + `world_behavior` 两分片（含 batch-1 一次 `local_correction` 自修成功收敛）全 committed，全程 0 传输抖动。**这实证了本轮修复（三-lane 分类 + 诊断克隆去毒化 + SKILL.md 补全）确实让语义层在真实环里自收敛，不再像旧 main 卡死打转。**

**硬结论 1 — 缺口 A 从推测升级为实锤（第 6 次 provider 事件，首次"挂起型"）**：`world_rules` 节点发起对 grok-4.5 的结构化调用后，进程 `ep_poll` 挂起、CPU 锁在 50s、**27 分钟零字节回包**（attempt 目录写完 profile/config 后彻底静默）。这不是快速 `provider_unavailable` 回错，而是 provider **挂起不回**——单次 LLM 调用**无 per-turn 软超时**，只能干等到 45min 全局 timeout 才触发唯一 1 次 infra 重试。**这正是"卡住/绕圈子"的物理来源。** ⇒ 缺口 A 必须做，且不止"加退避"：**必须给单次 LLM 调用加一个远小于 45min 的 per-turn 软超时 + 指数退避**，否则 provider 挂起会让反馈环干等大半小时。保留"单 backend、无自动模型 fallback"不变量（`routing.py:23` 故意设计 + [[model-quota-fallback]] 人工切换规矩）。

**硬结论 2 — 孤儿 running-head 竞态缺陷（记 owner，暂不改，避免污染 T2 探明）**：手动 kill 挂死的 generate 后，同键 resume 连续两次 `scheduler_direct_execution_error (TelemetryError)`。根因：kill 落在"operation 已清 `active_operation_ref=None` 但 head 未转终态"的窗口，留下 `status=running` 且 `active_operation_ref=None` 的孤儿 head；而 `work_runtime.py:379-380` 的 `reconcile_abandoned_operation` 对 `active_operation_ref is None` 直接 `return head` 不终态化 ⇒ 该 head 永久卡 running，每次 resume 都叠一个 `direct.generate` error root（telemetry 观测到 6 个）。**owner = 代码（恢复逻辑的边界遗漏）**，但属 kill 打断的罕见竞态，非反馈环打转核心；列为独立修复项，不插入当前 T2 探明。规避：污染的 scope 弃用，改用全新 request-id + 全新 state_root 干净重跑（前缀节点仅几分钟，代价小）。
