# Agent-Facing Observability Layer — 设计 + 实现计划

> 状态（2026-07-23）：设计方案 + 分阶段实现计划，待用户审批后执行。
> 本文与 `refactor-plan.md` / `refactor-plan-calibration.md` 同级，服从其北极星与
> 证据纪律。`refactor-plan-calibration.md` 对稳定性不变量的证据评级具有优先权。
>
> **修订 R1（2026-07-23，独立 review 后）**：初版有四处需在动手前修正，均已并入本文：
> 1. **分区键 `run_id` → `scope_id`（阻塞性）**：`run_id` 是每次执行（含 resume）重生的 UUID
>    （`controller.py:902/943`），而 `scope_id = job_id` 是请求内容的确定性哈希、跨 resume 稳定，
>    且正是 head 存储自己的分区键（`work_store.py:869`）。按 `run_id` 建目录会让现场在 resume
>    边界碎裂。Tier A 一律按 `scope_id` 分区，`run_id` 只作现场内的 epoch 标记。
> 2. **撤回"永不过期"**：投影钩子覆盖不了 `supersede_stale`/`reactivate_historical_commit`
>    （绕过 `_finish_attempt_span` 直接改 head revision）与 `except` 吞异常两类老化源。改为
>    **读时 watermark 校验 + 自愈重建**（见"失败语义"节）。
> 3. **有界改为 schema 硬约束**：不仅 cap 单坐标内 issue，还要 cap 坐标数量等所有 agent 面集合，
>    带 `overflow_count`。窄图才天然有界，宽 e2e（痛点2）会在图宽度维度爆。
> 4. **可发现性走已有 hooks，不靠 skill**：codex 不加载 `.claude/skills/`；用仓库已有的
>    `.codex/hooks/session-start.py` / `inject-workflow-state.py` 每轮注入 + `AGENTS.md` 一行。
>
> **修订 R2（2026-07-23，第二轮独立 adversarial review 对当前 HEAD 验证后）**：R2 把方案从
> "会诊断"推到"能行动"，并堵住一个漏密钥点。五处修正均已并入本文对应节：
> 1. **`candidate_file` 不从 `subject_refs` 推导（阻塞性，换地基）**：`ArtifactRef`
>    （`contracts/base.py:73`）**无 path 字段**；且失败路径上 `subject_refs=()`（`leaf_executor.py:748`
>    写死空），源码是单个 tar blob（`build.source_workspace_snapshot`，`builder/service.py:1716`）。
>    改为从 `BuildRecord.files`（`builder/models.py:649`，`PackageFile.path`+`role`）+ 失败坐标
>    role→`entry_path`（`CandidateRuntimeDeclaration.entry_path`，`builder/models.py:279`）推导。
> 2. **每条动态 Tier A 字符串过 canary（安全，堵漏）**：`violated_condition` 在部分构造点转发
>    `gate.summary[:512]`（`judge/leaf.py:623`），而 `gate.summary` 拼了 stderr 坐标
>    （`_candidate_failure_summary`，`service.py:1805`）。"framework-authored ≠ secret-free"：
>    每条进 Tier A 的动态串写前过 `known_secret_canaries`（`app.py:414`），命中降级为 hash。
> 3. **Phase 1 按 `isinstance` 分支，别假设人人有 exit_code**：只有 `RuntimeProcessCrashed` 带
>    `{exit_code,stderr}`（`supervisor.py:1346`）；`RuntimeRequestTimeout` 只有 `timeout_seconds`
>    （`:1264`）；`_RuntimeContractFailure` 是 `ValueError` 子类（`service.py:165/173`）无子进程。
>    `launch_argv` 不在异常上，从 `candidate.runtime.argv`（`service.py:3247`）取；stderr 切 16KiB tail。
> 4. **shared fold 签名钉死 `(heads, tier_b_events)`**：live 快照（`WorkReadinessSnapshot` /
>    `WorkScheduleSnapshot`）冷启动 CLI 重建不出，若喂进共享 fold 两腿必漂。急切腿须先把 live
>    对象降解成同一冷输入再调 fold。
> 5. **bypass 集合只含 `reactivate_historical_commit`**：`supersede_stale` 在当前 HEAD **调了**
>    `_finish_attempt_span`（`work_runtime.py:1187`），R1 说它绕过是错的；真正绕过的只有
>    `reactivate_historical_commit`（`:185`，`:243` 直接 CAS 无 finish hook）。watermark 结论不变。
>
> **修订 R3（2026-07-23，第三轮 review——专查"视图够不够 agent 行动"后）**：R2 的 candidate_file
> 修法只对了一半，且暴露一个"禁改≠禁读"的洞。两处阻塞性修正：
> 1. **`candidate_file` 从失败 gate id 推导，不从坐标 role（阻塞性，纠正 R2）**：`WorkCoordinate`
>    （`work.py:189`）**无 role 字段**，失败坐标 `component="judge"/"integration"`（`work_graph.py:1548/1581`）
>    不拥有 candidate 文件；且 judge 一坐标跑 ~6 个 gate、各指不同文件。判别符是 `ValidationIssue.code`
>    = `f"{stage}_gate_{gate.gate_id}_{status}"`（`leaf.py:621`）。改为从 `top_issues[].code` 解析
>    gate_id → 封闭表 `gate_id→role→entry_path`（role→path 仅 `runtime`/`task_materializer`/
>    `public_verifier` 三者 1:1，`builder/models.py:613-615`）→ `BuildRecord.files`（`:649`）。
>    **跨多文件的 gate（`supply_chain`/`static_assurance`/`clean_deployment`）：`candidate_file=None`
>    + `repair_target` 给多文件/`needs_human` 提示，绝不猜路径**（猜错比不给更误导）。
> 2. **加只读 `observe contract`（阻塞性，堵"禁改≠禁读"）**：修 `runtime.py` 必须能读它要符合的
>    冻结 WorldSpec tool surface（`service.py:220-226`）。"禁改 WorldSpec" 是写规则，不等于不可读。
>    加 `observe contract <scope_id> <coord>` 只读渲染冻结契约 surface + verifier 期望，标"只读参考/禁改"。
> 3. **（次要）generic finding 路径的 `violated_condition` 可能空泛**（`gate.summary` 转发，`leaf.py:623`）：
>    `static_assurance`/`supply_chain` 类不假装单文件可行动，路由 `needs_human`/多文件。
> 4. **（次要）DRIFT 渲染加强**：`repair_target==generated_candidate_code` 时，让 `candidate_file` 做
>    "为什么"那句的**语法主语**（"candidate/runtime.py failed gate X: ..."），gate 措辞降为子细节——
>    比 🚫 emoji 更强,零成本。
>
> **划界（R3 review 确认）**：补上 R3 修正 1/2 后,**项目命名由来的主线类(子进程崩溃 + runtime
> 契约不符)"诊断→行动"闭环成立**;task_materializer/verifier 类需修正 1 落实;supply_chain 类
> 多文件、诚实走 needs_human。Phase 1 的 isinstance 分支、`observe candidate` 的 get_blob+tar、
> canary 加固均已对真实代码验证成立。

## Context — 为什么做这个

当前项目从自然语言需求到 Registry 发布的 e2e **始终跑不通**，而 codex 之类的 AI 试图
修复时**一直在打转**。根因不只是某个 bug，而是 **repo 的执行环境对 agent 不友好**：

1. **上下文太长**，模型记不住全量状态；
2. **所有节点一起 e2e**，无法单独观察某个节点卡在哪；
3. **可观测性差**——AI 拿到的信息（`operation failed (ExceptionType)`）不支持它"浮现"
   真正的问题。

决定性证据：一次失败 run 的候选环境**单独裸跑 handshake 29ms 正常**，但管线却报
`runtime exited without a response`。原因是子进程的 exit_code/stderr 在
`agent_world/judge/supervisor.py` 已被捕获，却在 `agent_world/judge/service.py:1804-1817`
**被丢弃**——只记了 `failure_class` 和 message。这就是"无现场可看"的典型盲区。

**目标**：把可观测性做成一个**与其他组件同等地位的、面向 agent 的执行环境层**——让 repo
每一轮对 codex 都可读、可定位、可行动（看懂现状 → 收缩问题，而不是打转），从而让 e2e 跑通。
可观测性是手段，让 agent 能力得以发挥是目的。

## 核心设计模型（Temporal 式，两层 trace）

按**消费者**分两层 trace，不按"要不要保护"分：

- **Tier A = 面向 agent 的"现场"/index**：精选、有界、高信噪比，是**投影不是原始日志**。
  只放有助于理解**现状 + 下一步行动**的内容。**这是当前缺失、本计划新增的核心。**
- **Tier B = 面向程序的 log**：完整 append-only 事件流，作为**唯一真相源**，供重放/指标/
  事后分析。啰嗦无妨，消费者是程序不是 LLM 上下文。**复用现有 `TelemetryStore`（SQLite）。**

Temporal 模型：append-only 事件 journal（Tier B）是真相源 = "CPU 现场保留"；一个
reducer/projector 把它折叠成"当前失败现场"视图（Tier A index）。每个 WorkAttempt = 一个进程，
其 `NodeContinuationRecord` + journal 事件 = 保存的 PCB/寄存器。直接映射到已有稳定性不变量：
**S2**（每次重试 frontier 是否严格收缩）、**S4**（是否在同一坐标同 fingerprint 无进展打转）。

### index（文件）vs CLI（代码干活）的边界

- **index = 文件**，写入时算好、读时（经 watermark 校验后）零计算、codex 自己找。只放
  **每次失败必看且能廉价保持最新**的有界状态（卡在哪个坐标、为什么、本轮 vs 上轮 frontier 差异）。
  投影是 WorkScheduler 状态转移的**副产品（急切腿，best-effort）**，但**不作新鲜度保证**——
  新鲜度由读时的 watermark 校验兜底（见"失败语义"节）。类比 repo 里预建好的符号索引。
- **CLI = 按需算 + 收集/重建**：跨 run 比较、按条件过滤、重放重建、frontier diff，以及
  **读时从 Tier B + heads 重新折叠出 scene（`observe scene` 本身就是 reducer/收集器）**。
  这些组合爆炸或需重放，不塞进文件。
- 规则：**必看且能廉价新鲜 → 物化成 index 文件（急切）；定向/历史/跨 run/需重放/校验重建 →
  CLI 现算（惰性、权威）。**

### Secrets 硬边界（不变）

`.agent-world-live` 的 auth/密钥/sealed verifier/带凭证的 provider transcript **绝不进任何一层**。
LLM 输入输出**内容**只可进一个**默认关闭、gitignore、经 redaction 的本地 debug 层**；发布路径
永远干净。所有进入 Tier A/B 的 stderr 有界（16 KiB tail）且过 canary 校验。

## 失败语义：持久化 vs 投影（这一节是整个设计的命门）

用户核心疑问：代码执行被错误打断，会不会导致 index 没更新、给 agent 的视图缺失或陈旧？
答案是**会打断"投影"，但打断不了"真相"**——关键在于把两者的失败语义彻底分开。

**真相搭在 run 自己的推进上，跳不过、崩不坏。** 每次 WorkAttempt 状态转移 = 一次 head 的
CAS 写（`work_store.py` 的 `fsync` + `os.replace`，单文件原子）。这不是一个"额外的记录步骤"
（可能被跳过），而是**推进 run 本身**。所以：只要 run 往前走了一步，那步的事实就已落盘；
崩在半路也不写坏（原子——要么提交要么没提交，无半条）。Tier B（TelemetryStore events，
只增不删）+ heads 就是这份不可跳过的真相。

**agent 看的 scene（index）是投影、是可弃缓存，允许没更新。** 因为它随时能从上面的真相
**重新折叠**出来。于是形成两条腿：

- **急切腿（执行时，系统做，best-effort，允许失败）**：投影器挂在 `_finish_attempt_span`
  钩子上顺手写 scene 文件，让常见情况下 agent Read 是零计算。
- **惰性腿（读时，CLI 做，权威）**：`observe scene` 读各 head、比对 scene 里的 watermark，
  发现陈旧/缺失就地重建。**这条腿是兜底和真相，急切腿只是它的性能优化。**

**"agent 事后自己收集" vs "系统执行时完成" —— 都不是，是第三种：**
- 持久事实 = **系统执行时完成，且不可跳过**（搭 CAS）。
- 视图组装 = **读时由确定性代码（CLI）完成，不是 agent 手动收集**。
- **明确避免让 agent 事后自己去收集/更新视图**——那会把"谁负责更新、会不会忘"的腐烂问题
  原样搬回来（这正是用户最初担心的）。视图重建必须是读操作触发的代码，不是 agent 的记忆负担。

**watermark（读时校验，取代初版的"永不过期"）**：scene 里存一个 **per-coordinate** 的
`{coordinate_key → (revision, status, attempt_ref.revision_id)}` 映射 + `graph_digest`
（epoch 身份，`work_epoch.py`）+ `projected_from_run_id` + `projected_at`。注意 `revision`
是 **per-coordinate** 的（`work_store.py:77`），没有全局单调计数器，所以 watermark 必须按坐标。
`observe scene` 读时用 `WorkControlStore.read_head` 重读每个 head（各一个小文件，便宜）比对
`(revision, status)`，任一不同 → 判定陈旧 → 自动 rebuild。这一招同时盖住三类老化源：
① 急切腿被 `except` 吞掉；② `supersede_stale`/`reactivate_historical_commit` 绕过钩子改
revision；③ CAS 提交后、投影前崩溃的窗口。**不要**把投影事务性耦合进 CAS（会破坏
"可观测性绝不让 WorkAttempt 失败"且拖慢热路径，且仍盖不住 out-of-band 的 supersede）。

**最坏崩溃反而是现场保留最该发光的时刻**：进程在 attempt 正跑时被杀、终态 CAS 未提交 →
head 停在 `running`。`observe scene` 从该 head 重建出诚实现场"坐标 X，attempt running，
进程已死"，叠加 Phase 1 的子进程现场（exit_code/stderr/argv）就是"卡在坐标 X，子进程
handshake 阶段 exit 1"。这正是 CPU 上下文切换式的现场保留。**细节**：区分"真在跑"与
"进程已死"需拿 `TelemetryStore` 的 `active_work` 存活投影交叉验证，否则会把死进程误报为运行中。

## 代码落点（已实地核实，含行号）

**单一咽喉存在**：每个 WorkAttempt 终态转移都经过 `agent_world/control/work_runtime.py` 的
`WorkControlRuntime`，且每个终态分支都已配对 `heads.compare_and_swap(...)` + `_finish_attempt_span(...)`：
- `begin` @ 1094（`_start_attempt_span` @1113，CAS→running @1149）
- `evaluate` @ 1377（commit CAS @1653 + finish @1658；error `_fail_head` @1665 + finish @1671；
  failed/retry `_authorize_next_or_fail` @1677 + finish @1689）
- `_authorize_next_or_fail` @ 2504（S2/S4 所在：repair ordinal @2553，单调性在
  `work_repair.py:253-267` `classify_progress` 强制）
- `_finish_attempt_span` @ **2949** —— 每个终态分支都会调，纯副产品，**投影器挂这里**。

**投影器复用的现有"现场"原语**（勿重造）：
- `WorkReadinessSnapshot`（`work_readiness.py:40`）：status / missing_coordinates / blocking_evaluation_refs
- `WorkScheduleSnapshot` / `ScheduledWork`（`work_scheduler.py:102,136`）：per-coordinate state / waiting_on
- `WorkControlHead`（`work_store.py:68`）：status / input_fingerprint / attempt_ref（一坐标一文件）
- `ValidationReport`（`work.py:893`）+ `ValidationIssue`（`work.py:855`，含 `normalized_identity`）
  —— **这就是 S2/S4 的未闭合问题集类型**
- `NodeContinuationRecord`（`continuation_store.py:38`）：每 attempt 私有态，**secret-adjacent，
  只按 id 引用，绝不内联 `previous_candidate`**

**Tier B 复用**：`TelemetryStore`（`telemetry.py:197`，写 `state_root/telemetry/telemetry.sqlite`）。
写 API：`record_event` @437、`start_span` @259、`record_invocation` @458。**勿重造存储。**

## 组件形态

新一级子包 `agent_world/observability/`（与 control/ judge/ registry/ 同级）：

```
agent_world/observability/
  __init__.py          # 导出 SceneProjector / 路径根 / scene schema
  scene.py             # Tier A schema（V2Contract）：RunSceneIndex / CoordinateScene / FrontierDiff / SubprocessScene
  projector.py         # SceneProjector：纯副产品折叠。project_attempt(...)
  paths.py             # ObservabilityRoot：所有 state_root 相对路径集中一处
  render.py            # JSON→Markdown 确定性伴生渲染（.md 紧邻 .json）
  subprocess_scene.py  # 子进程 exit/stderr/argv 归一化 → Tier B event + Tier A SubprocessScene
  debug_transcript.py  # 默认关闭、gitignore、redaction 的 LLM I/O 层（Tier A-deep）
  query.py             # CLI 读侧计算：frontier diff / 跨 run 比较 / 重放
```

### Tier A index 文件布局（`state_root/observability/`）

**按 `scope_id`（稳定 job 身份）分区，不按 `run_id`**：

```
<scope_id>/
  scene.json / scene.md          # RunSceneIndex —— codex 每轮最先 Read 的文件（跨 resume 稳定）
  coordinates/<coord>.json/.md   # CoordinateScene —— 单节点当前失败现场
  frontier/<coord>.jsonl         # append-only 每 attempt 一行（digest+count+样本，非全集）
  subprocess/<coord>.json        # 最新 SubprocessScene（exit_code / stderr tail / launch argv / phase）
index.json                       # 跨 job 指针：scope_id → status / updated_at / stuck_coordinate
```

按 `scope_id` 分区的收益：resume（新 `run_id`、同 `scope_id`）与 `--request-id` 重跑都
**续写同一 job 目录**，跨 resume 的调试连续性得以保留，thrashing 检测跨重跑也成立；与 head
存储自身分区一致。`run_id` 降级为 scene 内的 epoch 标记。

**视图是一棵有界的树，不是一个 md（决策 A，skills 式渐进暴露）**。codex 的真实读取轨迹
决定这个结构，三层各司其职、逐层按需展开：

- **地图层 `scene.md`**：永远最先读的**唯一**文件。有界、全景、不装细节，每行带指针。一屏内让 codex
  形成假设(在造什么、走到哪步死的、卡哪个坐标、为什么、该往哪改)，并指向下一步该读什么。
- **地形层 `coordinates/<coord>.md`**：按需 Read，一坐标一文件。宽 e2e(几十坐标同时失败)也不撑爆
  上下文——codex 只读地图指向的那**一个**。
- **CLI 层 `observe <cmd>`**：算/历史/跨 run，敲命令、不占上下文。大多数修复走不到这层。

**契约是"失败先读 scene.md"，不是一本手册**。永远只有这一行进 agent 上下文；其余每步下一读
什么，都由上一层的**指针**给出(`Read coordinates/runtime.md` / `observe subprocess ...`)——
codex 不背路径，视图喂给它。这直接映射 skills 的"永远只加载一行 name+description，body 命中才展开"。

`scene.md`(地图层)以**坐标为主轴、管线阶段为标签**(决策 B：与 heads/scope_id/watermark 分区
天然对齐、无映射层)，目标形态一屏可读、每行可带 codex 去下一处：

```
状态: FAILED at Judge 阶段 (第 3 次 attempt)
卡在: 坐标 runtime [阶段 Judge] · 原因: thrashing(连续 2 轮同 issue 无进展)
为什么: gate contract_match 失败 — "runtime handshake does not match frozen WorldSpec"(期望 4 tools, 实得 3)
该改什么: ✏️ candidate/runtime.py failed gate runtime_protocol(期望 4 tools, 实得 3, 缺 book_room)
          🚫 别改 WorldSpec / gate(已冻结,改=DRIFT)
现场: 子进程正常退出,非崩溃 → 契约不符,不是进程死
下一步: · Read coordinates/runtime.md  · observe contract <scope_id> runtime(看 book_room 该长啥样)
        · observe candidate <scope_id> runtime(看现在的实现)
其他失败坐标: 0
```

`RunSceneIndex` 关键字段：`scope_id`、`overall_status`、`stuck_coordinate`、
`stuck_reason`（thrashing / no_repair_authority / subprocess_crash / budget_exhausted / blocked_by_parent / needs_human）、
`missing_coordinates`（cap + `overflow_count`）、`frontier_size`、`frontier_delta`（负=收缩=健康 S2）、
`next_action_hint`（**封闭枚举模板，watermark 校验失败时抑制**，见 CLI 节）、
`coordinate_pointers`（cap 到 top-K 最阻塞 + `additional_stuck_count`）、
**`watermark`**（per-coordinate `{revision,status,attempt_ref_revision}` 映射 + `graph_digest` +
`projected_from_run_id` + `projected_at`，供读时校验）。

`CoordinateScene` 关键字段：`head_status`、`attempt_ordinal`、`failure_code`、`frontier_ordinal`、
`pipeline_stage`（Research/Designer/Builder/Integration/Judge/Registry，由坐标 component 映射，
决策 B 的"阶段标签"）、`unresolved_issue_ids`（**cap + `overflow_count`**，全集在 Tier B）、
`unresolved_issue_digest`、`previous_issue_digest`、
`frontier_progress`（strict_progress / resolved / no_progress / unknown）、`repair_authority`、
**`candidate_file`**（决策 C 补丁 2 + R3 修正 1：该改哪个生成文件的相对路径，从**失败 gate id**推导——
`top_issues[].code` 里的 gate_id（`leaf.py:621`）→ 封闭表 `gate_id→role→entry_path`（`builder/models.py:613-615`
仅 runtime/task_materializer/public_verifier 三者 1:1）→ `BuildRecord.files`（`:649`）；**不从坐标 role**
（坐标 `component=judge/integration` 无 role、不拥有文件）**也不从 `subject_refs`**。跨多文件 gate
（supply_chain/static_assurance/clean_deployment）置 `candidate_file=None`，**绝不猜路径**）、
**`contract_pointer`**（R3 修正 2：指向 `observe contract <scope_id> <coord>`——该坐标要符合的冻结
WorldSpec surface/verifier 期望的只读入口，标"只读参考/禁改"）、
**`repair_target`**（封闭枚举 `generated_candidate_code | design_worldspec | needs_human`，
由 `pipeline_stage` + 失败 gate 推导：Designer→worldspec，Builder/Judge 单文件 gate→candidate code，
**多文件 gate(supply_chain/static_assurance/clean_deployment)→needs_human 或多文件提示**；
**北极星防漂移字段**，渲染时 `generated_candidate_code` 情形让 `candidate_file` 做"为什么"句的语法主语、
把 WorldSpec/gate 标"禁改"——比 emoji 更强，R3 修正 4）、
**`top_issues`（≤8，每条内联 `{code, path, violated_condition, expected_category, severity}`，
决策 C 补丁 1，不再只存 hash）**、`subprocess_pointer`、`input_fingerprint`、
`attempt_ref_id`（只 id，不内联 continuation 内容）。

**决策 C 的可行动性(把"会诊断"变"能行动")**：`top_issues` 内联 `violated_condition`（哪里错的人话，
`work.py:860`）+ `candidate_file`（改哪个文件）+ `repair_target`（该改代码还是别碰契约）三者，
让 codex 读一屏即知道下一步动手点，不必回 Tier B 反复 CLI 才拿到可编辑目标。投影时用
`ValidationIssue.actionable`（`work.py:875`）优先能动手的 issue。

**每条内联动态串过 canary（决策 R2 修正 2，安全硬约束）**：`violated_condition`/`expected_category`
在部分构造点转发 `gate.summary`（拼了 stderr 坐标），写入 Tier A 前必须过 `known_secret_canaries`
（`app.py:414`），命中则该字段降级为 `normalized_identity` hash。**framework-authored ≠ secret-free**。

**有界是 schema 硬约束（在 `scene.py` 强制，不是投影器的约定）**：所有 agent 面集合
（issue、坐标、指针）都必须 cap 并带 `overflow_count`/`additional_*_count`，否则宽 e2e
（很多节点同时失败，痛点2）会在图宽度维度撑爆 agent 读的面。

`.md` 伴生文件是同一 JSON 的确定性渲染（stuck 坐标、frontier delta 带 ↓/↑/= 字形、top issues、
要跟进的 `Read` 路径），无新数据，永不与 JSON 分叉。

### 投影器的定位：急切 best-effort，不作新鲜度保证

1. 只从 runtime 转移路径调用（`_finish_attempt_span` 在 head CAS 之后），无轮询、无独立守护进程。
2. 只读**持久化的 heads/artifacts** 作真相源，不读内存态。scene 每次转移**覆盖重写**（非 append）。
3. **失败隔离**：整个 `project_attempt` 包 `except Exception` 吞掉并尽力 `record_event`
   一条 `observability_projection_failed` 到 Tier B。可观测性**绝不能让 WorkAttempt 失败**。
4. 只写 artifact id / 坐标 key / issue 身份哈希 / status 枚举 / 有界安全字段，不写 secret。
5. **它不保证新鲜**：覆盖每次都发生，但覆盖不了 `reactivate_historical_commit`（`work_runtime.py:185`，
   在 `:243` 直接 CAS 改 head revision、无 `_finish_attempt_span`，**这是唯一真正绕过本钩子的路径**——
   注意 `supersede_stale` 在当前 HEAD **是调了** `_finish_attempt_span`(`:1187`)，R1 说它绕过是错的)
   与被 `except` 吞掉的情况。新鲜度一律由读时 watermark 校验兜底（见"失败语义"节）。
   写 scene 时必须一并写入当前 watermark，供读侧比对。
6. **纯 fold 签名钉死 `fold(heads, tier_b_events) -> Scene`（决策 R2 修正 4）**：急切腿(projector 在
   runtime 内、手握 live 的 `WorkReadinessSnapshot`/`WorkScheduleSnapshot`)与惰性腿(CLI 冷启动、
   只有持久 heads+SQLite)**必须共用同一个纯 fold**，否则两腿输出对不上是最难查的 bug。约束：fold 只吃
   冷启动可重建的输入(`read_head` 每坐标一小文件 + Tier B events)；projector 必须先把 live 对象
   **降解成同一冷输入**再调 fold，绝不把 live 快照直接喂进去。

## `observe` CLI（面向 agent，JSON 输出）

在 `cli.py:66` 加 `observe` 子解析器，`_dispatch`（@354）加分支，全部经 `_write_json`（@643）
输出紧凑 JSON 供 `jq`。在 `main()`（@316）加专用 `except ObservabilityError`，**避免被
`operation_failed`（@349）抹成不透明**。

所有命令按 `scope_id` 寻址（`run_id` 只在需要指定某次执行时作可选过滤）。`--latest` 默认解析
到最近活跃的 job。

读 + 读时校验（首要路径；命中缓存则零计算，watermark 陈旧则就地重建）：
- `observe scene [<scope_id>|--latest]` → 校验 watermark，命中直接输出 `scene.json`，
  陈旧/缺失则从 Tier B + heads 重建后输出（首要"现在错在哪"）。**这就是"收集器/reducer"。**
- `observe coordinate <scope_id> <coord>` → CoordinateScene（同样读时校验）
- `observe subprocess <scope_id> <coord>` → SubprocessScene（崩溃现场）
- `observe candidate <scope_id> <coord>` → **只读读出该坐标对应的生成源码**（决策 C 补丁 3）：
  从 `BuildRecord.source_snapshot_ref`（`builder/models.py:647`）`get_blob`（`artifact_store.py:271`）
  →**内存解 tar**→按 `PackageFile.path`（**由失败 gate id→role→`entry_path` 定位**，R3 修正 1）取该文件
  →canary 校验→输出。让 codex 看到失败断言旁边的实际代码。**不是** ArtifactRef 直接 deref(ref 无 path、
  源码是 tar blob)。
- `observe contract <scope_id> <coord>` → **只读渲染该坐标要符合的冻结契约**（R3 修正 2）：WorldSpec
  tool surface（`service.py:220-226`：namespace/name/input_schema/output_schema）+ verifier 期望，
  明确标"只读参考/禁改"。修 `runtime.py` 必须能读它要 conform 的目标 shape,否则只能猜 schema、re-fail。
- `observe rebuild [<scope_id>|--latest]` → 强制从 Tier B 全量重折叠（跳过缓存），显式收集入口。

按需算（`query.py`，读 Tier B SQLite + frontier jsonl）：
- `observe frontier-diff <scope_id> <coord> [--from N --to M]` → 两 attempt 未闭合 issue 集的
  增/删/留 + frontier_ordinal 移动（单节点 S2 显微镜）
- `observe compare --scope A --scope B` → 跨 job 首个分叉坐标 + status 差异
- `observe replay <scope_id> <coord>` → 从 Tier B 事件重建某坐标 attempt 序列（只 id/status/frontier）

**`next_action_hint` 安全规则**：hint 必须是**封闭枚举**——每个 `stuck_reason` 映射到一条
模板命令（模板与枚举同处代码，不自由生成、不会老化）。**watermark 校验失败时抑制具体 hint**，
替换为"scene 陈旧，请 `observe rebuild`"。绝不从未校验的投影发出坐标级 hint，否则会以机器
权威把 codex 带进死胡同。

## 可发现性：agent 怎么知道有 `observe`、怎么用（非老化、覆盖两种 agent）

分层渐进暴露，让 agent 几乎不用记东西，且引导本身不会老化：

1. **零知识入口走仓库已有的注入 hook（最关键）**：`.codex/hooks/session-start.py` 与
   `inject-workflow-state.py` 已在每次会话开始/每轮 prompt 注入 `<current-state>` 块，且跨平台
   （claude/codex 都覆盖）。在其中"direct job head 处于 failed/interrupted"时加一行：字面
   `observe scene <scope_id>` + "先读 scene.md"。**每轮重新生成 → 不老化；两个 agent 都收到。**
2. **`scene.md` 在固定稳定路径**（`state_root/observability/<scope_id>/scene.md`）——"要读的那一个
   文件"是契约，不是手册。
3. **`next_action_hint`** 在 scene.md 内，按上节封闭枚举规则给出下一条命令。
4. **`AGENTS.md` 加一行**（两个 agent 都读的共享契约）："任何失败 run，行动前先读 `observe scene`。"
5. `observe --help` 兜底。

**明确纠正初版**：不要用 `.claude/skills/` 做 codex 的可发现性载体——**codex 不加载
`.claude/skills/`**（它用 `.codex/agents/*.toml`），skill 只覆盖 claude 一半，漏掉真正驱动
节点工作的 codex。载荷放在 hooks + `AGENTS.md`。

**为什么是 CLI/文件而非 MCP**：文件（codex 有 Read）作默认读面、零依赖、固定路径无需发现协议；
CLI 承担需要 Tier B 计算的操作。MCP 是最干净的 in-loop 接口但引入 server/协议依赖，且新鲜度
保证在读路径上与传输无关——先上低依赖的 files+CLI，若 codex 实测 shell-out 有摩擦再引 MCP。

## 保留与增长（retention / GC）

区分两种增长，结论不同：

- **agent 读的面 = 不增长**：`scene.json` 覆盖重写、所有集合 schema cap。**前提是上面"有界作
  schema 硬约束"落实**，否则宽 e2e 会撑爆。frontier jsonl 每行存 digest+count+样本（非全集），
  行数被 repair 预算封顶（`repair_attempt_charge` `le=1`，`work.py`），单坐标自然有界。
- **磁盘上跨 job 的量 = 会增长**：一个 `scope_id` 一个目录。落在已 gitignore 的 `state_root`
  审计区，**不进 agent 上下文**。策略：**按 `scope_id` mtime keep-last-N（TTL 为辅）**，配置进
  `ObservabilityConfig`（`config.py`，与 `commit_batch_size` 同处）。**安全**：Tier A 非权威，
  删了 `observe rebuild` 仍能从 Tier B 重建。
- **暴露的负债（须点名，不在本计划范围内解决）**：**Tier B（TelemetryStore SQLite）今天完全无
  回收，只增不减**；`artifact_store.py` 亦无 prune/vacuum。若将来 GC 了 Tier B，则 `rebuild`/
  `replay` 只能返回部分历史。本计划只保证 Tier A GC 不破坏 rebuild；Tier B 的长期增长治理另开。

**关于"视图归档文件夹"（决策 D，回应用户）**：**不单独归档每次转移的 scene**——可重建历史已由
Tier B（SQLite）+ `frontier/*.jsonl` 覆盖，再物化一份历史 scene 是与 Tier B 重复劳动，且把增长
问题搬回来、破坏"有界"。真正的缺口是"诊断→可编辑目标的桥"（决策 C），不是归档。**终态取证快照
`snapshots/<epoch|terminal>-<ts>.json`（immutable、只在终态+resume epoch 边界冻结、数量 O(epoch)
天然有界、独立于 keep-last-N 的更宽松 GC）降级为可选后续**，不进主线；需要时再加，且它 immutable
不需 watermark（是"当时"真相不是"现在"视图）。

## 分阶段实现（最快 e2e 调试收益优先）

**Phase 1 — 子进程现场捕获 + 修 `service.py` 丢弃点（信号最高、改动最小）。**
- 修 `judge/service.py:1804-1817` 及 `_protocol_gate` 孪生（`1895-1908`）：构造 record 时
  **按异常类型 `isinstance` 分支**（决策 R2 修正 3，别假设人人有 exit_code）——
  - `exit_code`/`stderr` **只在** `isinstance(exc, RuntimeProcessCrashed)`（`supervisor.py:1346` 带
    `{exit_code,stderr}`），stderr 显式切 **16KiB tail**（`exc.details["stderr"]` 原始可达 256KiB）；
  - `launch_argv` 从 **`candidate.runtime.argv`**（`service.py:3247`，env 已 scrub）——**不从异常**
    （`supervisor.py:1151` 的 `_validated_launch` 在 `async with` 作用域内、except 里已失效）；
  - `RuntimeRequestTimeout` 记 `timeout_seconds`（`supervisor.py:1264`）、`_RuntimeContractFailure`
    （`ValueError` 子类、无子进程）记 `mismatch_paths`，各记各的、不硬塞 exit_code。
  - **所有持久化文本过 canary**（`app.py:414`）后才写。
- 加 `subprocess_scene.py`，在 supervisor 崩溃点（`_crashed_error` @1346，request() @1253-1279）
  emit 一条 `runtime_subprocess_scene` 到 Tier B。
- **单此一步即解决"裸跑正常、管线说 exited without a response"的盲区。**
- 验证：扩 `tests/agent_world/test_runtime_process_integration.py` +
  `test_codex_worker_lifecycle.py`，用一个 handshake 阶段非零退出的 runtime，断言 integration
  evidence artifact 现含 exit_code/stderr/launch_argv；并断言 timeout/contract-fail 分支**不**误报
  exit_code。真实命令：`uv run python -m agent_world.cli run inspect <request_id> --metrics`。

**Phase 2 — `ObservabilityRoot` + schema（有界+watermark）+ 投影器骨架（Tier A 文件）。**
- `paths.py`（按 `scope_id` 分区）/ `scene.py`（集合 cap + `overflow_count` + watermark 字段 +
  **决策 C**：`top_issues` 内联 `{code,path,violated_condition,expected_category,severity}`、
  `CoordinateScene` 加 `candidate_file`/`repair_target`/`pipeline_stage`，**有界作 schema 校验**）/
  `projector.py`（含**共享纯 fold** `fold(heads, tier_b_events) -> Scene`，决策 R2 修正 4：
  签名钉死冷输入，projector 先降解 live 对象再调它）。
- `candidate_file` 从**失败 gate id**（`top_issues[].code` 里的 gate_id，`leaf.py:621`）→ 封闭表
  `gate_id→role→entry_path`（`builder/models.py:613-615`）→ `BuildRecord.files`（`:649`）推导，
  **不从坐标 role（坐标无 role）也不从 `subject_refs`（失败路径为 `()`）**，R3 修正 1 + R2 修正 1；
  多文件 gate 置 `None`。`repair_target` 由 `pipeline_stage`+gate 查表(多文件→needs_human)；
  每条内联动态串过 canary（`app.py:414`）命中降级为 hash。
- 把 `SceneProjector | None` 注入 `WorkControlRuntime.__init__`（@112，与 telemetry 并列），从
  `_finish_attempt_span`（@2949）调用，写 scene 时一并写 watermark。
  **注意**：投影器调用须 gate 在 `self.projector is not None`，**不能**在 `if self.telemetry is None`
  提前 return（@2957）之后，否则无 telemetry 的 dev/test run 就没有现场。
- 验证：新 `tests/agent_world/test_observability_projector.py`，驱动
  begin→evaluate(fail)→repair→evaluate(fail again)，断言 `scene.json` 显示 stuck 坐标、
  `frontier_delta`、重复同一 frontier 时 `stuck_reason="thrashing"`；断言 `top_issues` 含
  `violated_condition` 文本、`repair_target` 指向 candidate code(非 gate)；断言宽图（多坐标失败）时
  集合被 cap 且 `overflow_count` 正确；断言植入 canary 的 `violated_condition` 被降级为 hash。跑
  `test_work_runtime` / `test_work_scheduler` / `test_work_readiness` 确认副产品无回归。

**Phase 3 — `observe` CLI（读时 watermark 校验 + 重建 + 决策 C 补丁 3 的源码读出）。**
- 加 `observe scene|coordinate|subprocess|candidate|contract|rebuild` + `main()` 的 `ObservabilityError`；
  惰性腿复用 Phase 2 的**同一个纯 fold**做读时重建；watermark 校验（重读 heads 比对
  `(revision,status)`，陈旧则重建）+ 封闭枚举 `next_action_hint`（watermark 失败时抑制）。
- `observe candidate`：`get_blob(source_snapshot_ref)`→内存解 tar→按 `PackageFile.path`（gate id→role→
  entry_path 定位）取→canary→输出（只读；ref 无 path、源码是 tar blob，故非直接 deref）。
- `observe contract`：只读渲染冻结 WorldSpec tool surface（`service.py:220-226`）+ verifier 期望，
  标"只读参考/禁改"——给 agent"要 conform 的目标 shape",不然改 runtime.py 只能猜 schema。
- 可发现性：在 `.codex/hooks/session-start.py` / `inject-workflow-state.py` 的 `<current-state>`
  失败分支加一行 `observe scene <scope_id>` 指针；`AGENTS.md` 加一行。**不用 `.claude/skills/`**。
- 验证：扩 `tests/agent_world/test_app_cli.py`，跑一个到已知失败的小 generation，
  `observe scene --latest` 断言 JSON 形状 + 退出码；`observe candidate` 断言读出生成源码；
  构造一个 watermark 陈旧场景断言自动重建。
  **此处 codex 真正能开始调控**：读 `scene.md` → 读被指向的那一个坐标文件 → 看 `candidate_file` 源码。

**Phase 4 — 按需查询（`query.py`）：frontier-diff / compare / replay + retention。**
- 复用 Tier B SQLite + `frontier/*.jsonl`；实现按 `scope_id` keep-last-N 的 Tier A GC
  （配置进 `ObservabilityConfig`）。
- 验证：合成 frontier jsonl 的集合差单测；`test_telemetry.py` 式 trace fixture 测 compare；
  GC 后断言 `observe rebuild` 仍能从 Tier B 重建（证明 Tier A 非权威）。

**Phase 5（可选后续，不进主线）— 默认关闭的本地 debug transcript 层 + gitignore。**
> 与决策 D 的 `snapshots/` 取证快照同属"需要时再加"的可选层：主线到 Phase 4 即完成"诊断→行动"闭环，
> 本阶段与 snapshots 均非 e2e 跑通的必要件，故降级。
- `debug_transcript.py`，canary 校验、opt-in（如 `AGENT_WORLD_DEBUG_TRANSCRIPTS=1`），
  写 `state_root/observability/<scope_id>/_debug/`。`.gitignore` 加 `observability/**/_debug/`。
  复用现有 redaction / `known_secret_canaries`（`app.py:414`）；含 canary 则拒写。
- 验证：flag 关闭时 `_debug/` 不存在；开启时植入 canary 字符串被拒；`git status --ignored`
  确认 debug 树被忽略。

每个 Phase 后跑 `uv run pytest tests/agent_world -q`。

## 模型与真实代码的摩擦点（及适配）

1. **Tier B 是 SQLite 不是纯 JSONL journal。** 语义上仍满足 append-only 真相源
   （events 表只增不删）。适配：SQLite 留作 Tier B 权威；投影器的 `frontier/<coord>.jsonl` 是
   针对 S2/S4 信号的小型 append-only 文件镜像，`observe replay` 按需从 SQLite 重建。不替换 SQLite。
2. **frontier 是 per-coordinate 而非单一全局对象。** 无单一 `Frontier` 类型；由
   `ValidationReport.issues[].normalized_identity`（per attempt）+ 图级
   `missing_coordinates`/`blocking_evaluation_refs` 组成。适配：投影器组合两粒度——节点内
   issue-identity 集（S2/S4）+ 图级 missing/blocked 坐标集（"哪个节点卡了"）。
3. **`_finish_attempt_span` 在 telemetry 为 None 时提前 return。** 适配：投影器调用 gate 在
   projector 非空，与 telemetry 解耦。
4. **continuation 与 stderr 的 secret 邻接。** Tier A 绝不内联 `previous_candidate`（只按 id 引用），
   所有 stderr 有界（16 KiB tail）+ canary 校验后才写。
5. **`main()` 把未知异常抹成 `operation_failed`（cli.py:349）。** 适配：定义
   `ObservabilityError(code, message)`（安全非 secret 消息），在 `main()` 给专用 `except`
   （仿 `LocalConsumerError` @346）。
6. **`run_id` 是每执行重生的 UUID、`scope_id` 才稳定（阻塞性）。** `run_id=uuid`（`controller.py:902/943`），
   resume 记 `previous_run_id`（`:783`）；`scope_id=job_id=_stable_id(...)`（`:818/4205`）跨 resume
   稳定且是 head 分区键（`work_store.py:869`）。适配：Tier A 一律按 `scope_id` 分区。**注意 campaign
   路径的 `run_id` 反而是 campaign-scoped 稳定的（`controller.py:1431`）——按 `scope_id` 分区可让
   direct 与 campaign 两路一致。**
7. **`revision` 是 per-coordinate、无全局单调计数器（`work_store.py:77`）。** 适配：watermark 必须
   按坐标存 `{revision,status}` 映射，读时逐 head 比对，不能寄望一个全局 revision。
8. **Tier B（SQLite）与 artifact_store 今天均无 retention。** 适配：本计划的 GC 只覆盖 Tier A；
   Tier B 只增不减是已知负债，另开治理，且 GC Tier B 会使 rebuild/replay 只得部分历史。
9. **`candidate_file` 的判别符是失败 gate id、不是坐标 role（决策 R2 修正 1 + R3 修正 1，阻塞性）。**
   `subject_refs=()`（`leaf_executor.py:748`）、`ArtifactRef` 无 path（`contracts/base.py:73`）已排除
   subject_refs 路线；进一步,`WorkCoordinate`（`work.py:189`）**无 role 字段**,失败坐标
   `component=judge/integration`（`work_graph.py:1548/1581`）不拥有文件,且 judge 一坐标跑 ~6 gate 各指
   不同文件。适配:从 `ValidationIssue.code`=`f"{stage}_gate_{gate_id}_{status}"`（`leaf.py:621`）解析
   gate_id → 封闭表 `gate_id→role→entry_path`（`builder/models.py:613-615` 仅 3 role 1:1）→
   `BuildRecord.files`（`:649`）；多文件 gate（supply_chain/static_assurance/clean_deployment）置
   `None`+needs_human,**绝不猜路径**。`observe candidate` 用 `source_snapshot_ref`（`:647`）`get_blob`+
   内存解 tar 读内容。
12. **"禁改 WorldSpec"≠"不可读 WorldSpec"（R3 修正 2，阻塞性）。** 修 `runtime.py` 必须能读它要 conform
    的冻结 WorldSpec surface（`service.py:220-226`）。适配:加只读 `observe contract`,渲染 surface+verifier
    期望标"只读参考/禁改";不给它 agent 只能猜 schema、re-fail。
10. **动态诊断串邻接 secret（决策 R2 修正 2）。** `violated_condition` 在部分构造点转发
    `gate.summary`（`judge/leaf.py:623`），后者拼了 stderr 坐标。适配：每条进 Tier A 的动态串写前过
    `known_secret_canaries`（`app.py:414`），命中降级为 hash——不因"framework-authored"就免检。
11. **shared fold 的冷/热输入不对称（决策 R2 修正 4）。** projector 手握 live `WorkReadinessSnapshot`/
    `WorkScheduleSnapshot`，CLI 冷启动重建不出。适配：纯 fold 签名钉死 `(heads, tier_b_events)`，
    projector 先降解 live 对象为该输入再调，两腿共用一份逻辑。

## 关键文件

- `agent_world/control/work_runtime.py`（注入投影器；@2949 挂钩；转移 @1094/1377/1653/2504/2704；
  唯一绕过 hook 的 `reactivate_historical_commit` @185/243；`supersede_stale` 其实调了 hook @1187）
- `agent_world/judge/supervisor.py`（子进程捕获 @1346 / 1253-1279；`RuntimeRequestTimeout` details @1264）
- `agent_world/judge/service.py`（修丢弃点 @1804-1817 及 `_protocol_gate` 孪生 @1895-1908；
  `_candidate_failure_summary` @235；`candidate.runtime.argv` 来源 @3247；`_RuntimeContractFailure`/
  `_CandidateTaskFailure`(ValueError) @165/173）
- `agent_world/judge/leaf.py`（**candidate_file 判别符**：`ValidationIssue.code` 含 gate_id @621；
  generic finding 转发 `gate.summary` @623/647）
- `agent_world/builder/models.py`（`candidate_file` 推导：role→`entry_path` 仅 3 role @613-615；
  `BuildRecord.files` @649；`source_snapshot_ref` @647；role 枚举 8 种 @38）
- `agent_world/artifact_store.py`（`observe candidate` 用 `get_blob` @271；`_blob_path` @1367）
- `agent_world/control/work_graph.py`（judge/integration 坐标不拥有 candidate 文件 @1548/1581）
- `agent_world/control/leaf_executor.py`（失败路径 `subject_refs=()` @748——故 candidate_file 换地基）
- `agent_world/contracts/base.py`（`ArtifactRef` @73，**无 path 字段**）
- `agent_world/judge/service.py` `observe contract` 数据源（冻结 WorldSpec tool surface @220-226）
- `agent_world/cli.py`（`observe` 子解析器 @66；`_dispatch` @354；`ObservabilityError` @316）
- `agent_world/control/telemetry.py`（Tier B 复用：`record_event` @437；`active_work` 存活投影供崩溃校验）
- `agent_world/controller.py`（`scope_id`/`job_id` 来源 @818/4205；`run_id` @902/943；供分区键改造）
- `.codex/hooks/session-start.py` / `inject-workflow-state.py`（可发现性：`<current-state>` 注入指针）
- 新包 `agent_world/observability/`（scene / projector / paths / query / subprocess_scene / debug_transcript / render）

## 端到端验证

1. 各 Phase 后 `uv run pytest tests/agent_world -q` 全绿。
2. 真实失败 run：`uv run agent-world --config <cfg> generate --need '用户预订宾馆' --request-id <id>`
   跑到失败后，`uv run agent-world observe scene --latest` 应直接给出 stuck 坐标 + stuck_reason +
   next_action_hint；若是集成崩溃，`observe subprocess <scope_id> <coord>` 给出 exit_code/stderr/argv。
3. 打转验证：连续两轮同坐标同 fingerprint 失败后，`scene.json` 的 `stuck_reason` 应为
   `thrashing`、`frontier_delta >= 0`，证明 S4 可被 codex 一眼看到。
4. resume 连续性：`generate --request-id X` 失败 → `resume X`，两次现场应续写**同一** `scope_id`
   目录，`observe scene X` 跨 resume 连续可读。
5. 老化自愈：手工令 scene 陈旧（改一个 head 的 revision 后不跑投影），`observe scene` 应检测
   watermark 不符并自动重建出正确现场。
6. **可行动性（决策 C + R3 的核心验收）**：runtime 契约不符失败后，`observe scene --latest` 一屏内
   即给出 `violated_condition` 人话 + `candidate_file`（由 gate id 定位到 `candidate/runtime.py`，非坐标
   role）+ `repair_target`；`observe candidate <scope_id> <coord>` 读出该文件源码；`observe contract`
   读出要 conform 的冻结 WorldSpec surface。判据:codex 不敲 replay/frontier-diff 即知改哪个文件+要符合
   什么 shape——"诊断→行动"闭环成立。**并断言**:多文件 gate(如 supply_chain)失败时 `candidate_file=None`
   且 `repair_target=needs_human`,**不猜路径**。
7. **北极星防漂移**：contract-mismatch 失败时 `repair_target == generated_candidate_code`，`scene.md`
   明确把 WorldSpec/gate 标为"禁改（改=DRIFT）"；断言 scene 不把 gate 呈现为最可编辑对象。
8. **secret 不外泄**：在 `violated_condition` 源(如 `gate.summary`)植入 canary 字符串，断言 Tier A
   的该字段被降级为 hash、不出现明文；`git status --ignored` 确认 `_debug/`(若启用)被忽略。
