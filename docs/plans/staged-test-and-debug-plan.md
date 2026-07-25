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

## T1 — 分段测「墙」：语义层节点

**战场**：语义层是 case 最密处。已知复现簇（用作 T1 的 regression 种子）：
- **BC-44（误分类，最先修，纯确定性可测）**：完整 ToolSemantics provider rejection 被分类成 generic **retryable** infrastructure → 每个物理 batch 白跑一次相同重试；且失败的 Direct request 不得被当 release evidence 恢复。修法：已知安全终止码 `turn_failed_provider_rejected`（`_codex_worker.py:197/232`）到达 Scheduler 时必须是 **non-retryable**，即使 backend 在 `:712/729/752` 通用地设了 retryable flag。**加确定性 regression 即可验，不需真实 run。**
- **BC-47（与 BC-44 解绑，不是纯确定性）**：其 required_regression 明写"only a fresh request may assess the reduced representation"——所以 BC-47 的 compact-alias→冻结 Rule binding 解析**需要一次真实 run 验收**，不能跟 BC-44 一起当"无需真实 run"。放在 BC-44 之后、T1 有真实 run 能力时做。
- **BC-14（诊断丢因果）**：整 Rule 编译要保留 tool/rule/clause/term 路径，canonical validator 发稳定 code，diagnostic 前缀保留 retryability/violated condition/expected category——不得塌成 `framework_diagnostic_incomplete`。
- **BC-17（有界进展后仍终止 + batch 过大）**：两次修正后进展奖励仍终止；靠**物理 batch 变小 + 冻结上下文**让新 batch 收敛，**不抬 retry ceiling**。（这也正对上次 run 撞 65k token 上限的根因。）

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
