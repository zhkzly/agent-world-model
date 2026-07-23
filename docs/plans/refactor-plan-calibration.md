# 2026-07-23 计划校准：以证据驱动的全路径重构

## 状态与优先级

这是 docs/plans 两份新计划的校准层，不删除其原始论点。它同时约束当前 Trellis task
feedback-control-plane-topology-refactor：

1. docs/agent-world-environment-generation.zh.md 的产品与信任合同优先；
2. 当前 task 的 prd.md、design.md、implement.md 定义可验收工作；
3. 本文只校正新计划的证据等级、顺序与完成标准；
4. refactor-plan.md 与 execute-once-root-cause-and-plan.md 保留为输入，不是发布或改码授权。

校准时的提交基线是 4394e1b，但工作树含用户的未提交计划改动。每个实施 Gate 开始前都必须
重新记录 git status --short、计划文件 digest 与当前 HEAD；不得用本文行号、历史 run 或未提交
文件名称推断当前代码仍相同。

## 这次重构要消除的失败模式

核心问题是先前的 AI 反复修改、反复执行，却始终不能把当前项目从自然语言请求跑到真实发布。
因此每次修改必须回答“它消除了哪个让下一轮必然或高度可能重复失败的系统性限制”，而不是只回答
“它让当前错误消失了吗”。候选限制只能归入下列可验证类别：

- Agent 输入/输出表示把机械事实或安全诊断丢失，导致一次授权修复不可行动；
- 多个 retry、预算、Finding 或 release authority 让一次失败变成重叠控制循环；
- WorkGraph 的定义、输入闭包、物理 executor 或恢复结算不完整，导致 ready work 永远不能向下游推进；
- 预算、profile、权限、隔离或 provider failure 被误分类为模型语义失败，或反过来；
- Integration/Release 的真实执行重复或缺失，却没有用 exact evidence key 表达独立性。

每一类都需要一个可复现 regression 和至少一次 current-head 的真实判别证据。无法定位 owner 的
限制必须终止为 framework/infrastructure diagnosis；不得靠增加 Agent turns、扩张 prompt、改低
Gate 或人工补 Artifact 继续推进。这样“不能跑通”本身才会不断缩小为有限、可修复或诚实阻断的边界。

## 不可退让的完成定义

重构不是把一个酒店 case 推到 Registry，也不是用 mock 证明控制面。最终需要：

1. 新请求“用户预订宾馆”经真实 Search/Fetch/Extract、真实 gpt-5.3-codex-spark
   InvocationBackend、真实 Builder/Judge 子进程，到达原子 Registry released；保留完整
   Artifact/Span/usage 闭包、未知量和 Reset + invoke 证据。
2. 一个独立真实 negative/rework acceptance 从 actionable ValidationReport 经唯一
   RepairAction -> WorkRepairLedgerEntry -> WorkAttempt 发生有界修复或诚实终止；不得手改
   Design/Candidate，也不得增加 retry ceiling。
3. Expand 不再使用 ExpansionDesignDraft、run_structured_agent 的局部语义重试或第二条控制面；
   一个带真实 ToolSurface、ToolSemantics 或 TransitionConstraint 变化的候选走同一 WorkGraph
   至 Registry，另一个候选可诚实 rejected 或 needs_human。这才关闭 FR-1、BC-10 和 BC-11。
4. 发布包以干净目录由 framework consumer 重启，并运行未知 seed/task 的 RPC Reset/Step；它不挂载
   Candidate source、EvaluatorGoal、Rule IR 或 release metadata。

因此 E1 是 Direct 的重要里程碑，不是这项“所有生产路径 clean-break 重构”任务的完成条件；
F1 和其端到端证据是归档前的必需工作。

## 版本控制与证据纪律

- 一次提交只包含一个因果 Gate 的代码、回归、任务日志和必要规范；不以“一个 session 一个 Gate”为由
  让半成品长期漂浮，也不把无关格式化混入。
- 编辑前后运行 git status --short、git diff --check、目标 diff 和测试；不使用 git add -A，
  不覆盖现有未提交改动，不改写历史 bad-case Artifact。
- 每个 Gate log 必须写：当前 HEAD、输入 plan digest、bad-case ID、事实/假设分类、失败时的
  stop condition、验证命令和真实 Artifact refs。没有 failing-then-passing regression 的结论只可记为
  hypothesis。
- .agent-world-live、key、auth、base URL、sealed case 和 provider transcript 均不提交、不进
  Artifact/日志/包。证据只保存 model、profile/config digest、环境变量名称、计数、哈希和安全诊断。

## 对两份新计划的批判性结论

| 原计划论断 | 证据评级 | 校准 |
|---|---|---|
| 保留真实 Runtime、独立 Judge、无 mock/fixture 成功路径 | 已由源合同确认 | 保留为不变量。 |
| BC-29--40 都说明“全语义层一次成型 IR”是同一根因 | 不成立 | BC-30/32/34/35/39 是生命周期、拓扑、预算或观测问题；BC-40 是 Architecture Pydantic 诊断问题。按 owner 分治，不能用一个 IR 重写掩盖它们。 |
| 每个 typed hole 天然独立，修一洞不会破另一洞 | 不成立 | WorldRules/Curriculum 有跨工具、状态和任务语义的全局闭包。只可把已冻结且可确定性派生的机械事实移入 catalog；耦合业务语义仍是一个原子 proposal/validation frontier。 |
| 严格进展等于未闭合问题数量下降 | 不成立 | BC-17 从 frontier 10 到 30 暴露更多精确问题，仍是有限的真实进展。继续使用 normalized issue set、frontier、lineage 的 lattice，并阻断 unchanged、regressed、A-to-B-to-A。 |
| WorldRules 是首个可以全面 scaffold 化的垂直切片 | 未证明且与现行合同冲突 | 源合同只承认 ToolSemantics 的 context 已完全冻结；WorldRules/Curriculum 不得伪装为机械 binding。先在 current HEAD 用 BC-40 证明 Architecture 的安全 Pydantic 诊断，再对可证明冻结的 catalog 做小范围实验。 |
| need fingerprint 可决定 request_id，并允许跨 scope 自动复用 Research/Architecture | 禁止 | EnvironmentJob、request、permission、acceptance/freshness closure 是身份的一部分。仅 exact job/request/acceptance WorkCommit 可恢复；跨 request/campaign 需显式 adoption/freshness policy。 |
| Integration 后 ReleaseAssurance 真执行只一次 | 部分成立 | 可复用的只是 exact digest/profile/toolchain/freshness key 的 static/public Integration evidence。Release 仍须独立执行 reachability/property/sealed 与 fresh deployment。 |
| 删除旧 repair、decision 和 Expansion 路径 | 方向正确，时机未证 | 先由 current-head call graph 证明 Direct/Expand 都不再引用，再删除并以 absence check、Direct E2E、Expand E2E 验收；文件名或“看似死代码”不是删除许可。 |
| execute-once 的裸 runtime handshake 说明环境已可用 | 仅历史局部事实 | 它只排除该旧 Candidate 的一个裸启动问题；没有覆盖隔离 profile、Supervisor 命令、materialization、Judge、package 或 Registry。 |

## Bad-case 分析与授权边界

| 族 | 证据 | 已支持的动作 | 明确不支持的动作 |
|---|---|---|---|
| 诊断/输入表示 | BC-02/03、29、31、33、36--38、40 | 保存安全 code/path/condition/category；只将已冻结的 pointer/id/selector 事实交由 code；压缩同构 repair brief | 加 retry、放松 semantic compiler、把所有语义改成独立 hole、把 raw validator 错误交给模型 |
| 控制/拓扑/恢复 | BC-06/09--11、18--26、30、32、34、35、39 | 一个 Scheduler/ledger/budget authority；pre-dispatch provenance；typed missing executor；terminal lease settlement；观测从 durable facts 投影 | 由 telemetry 外观推断越权 retry，或因一个 provider timeout 重写 semantic policy |
| 真实执行/成本 | BC-07、08、12 | Builder first-write SLA；exact-key evidence reuse；隔离限制显式 infrastructure terminal | 根据一个 sandbox child-watcher 现象改生产 cancellation；把尚未 live 量化的 BC-08 说成已节省成本 |

所有 P0 控制面改动至少需要两个独立 case，或一个 case 加重现同一因果机制的确定性 regression。
单个 live run 只能授权本地、fail-closed 修复或增加观测。每项新 scaffold、缓存或删除改动必须主动列出
反例：catalog 是否遗漏 ref 或权限事实、业务规则是否跨 hole 耦合、adoption 是否跨越
request/acceptance 边界、缓存是否会替代 fresh execution。

## 校准后的执行顺序

### P0 — 可复现基线与 Spark profile preflight

1. 固化当前 Git/plan digest 与 bad-case admission table；运行 uv sync、lint、mypy、完整 deterministic
   suite，并区分项目失败和执行沙箱限制。
2. 用用户本地、ignored 的 Spark config 做 doctor --production：明确 gpt-5.3-codex-spark、
   API-key handle OPENAI_API_KEY，以及从 OPENAI_BASE_URL 物化的 credential-free base URL。
   现有历史配置使用 ChatGPT auth，不能静默拿来替代此 profile。
3. 只记录 profile/config digest、model 与变量名；preflight 未通过时停止，绝不 fallback 到 mock、
   ChatGPT ambient auth 或另一个未记录模型。

### P1 — 先验证 current HEAD 的最小可判别假设

1. 以新 request（不改历史 Artifact）从 Research 到 WorldArchitecture 运行真实 Spark profile，验证
   BC-40 的 allowlisted Pydantic diagnostics：已知 source contract 应可触发 actionable report/有限
   repair/WorkCommit；未知 raw validator 必须 framework_diagnostic_incomplete 且不花 repair turn。
2. 若它没有通过，修复只限已证明 owner 的 source-model/diagnostic boundary，并以 deterministic
   regression 加一条 fresh live evidence 验收。不得跳到“重写所有语义 IR”。
3. 若它通过，下一个 live stage使用其 exact committed closure；诊断只可从完整合法 start Artifact
   运行，且 diagnostic_only=true、releasable=false。

### P2 — 基于已通过的 gate 做小而可证伪的收敛改进

按现有 J1/J2/J3、S1/S2、C1/C2、B3/E0 gate 逐项重新验明 current-head 状态，而不是相信交接文档
已经完成。每项只处理它的 named BC/owner：

- 对任何 catalog/hole 提案，先证明输入全部来自 immutable upstream closure、每个机械字段可代码派生、
  compiler/Judge ABI 未变、全局业务闭包仍被验证；
- 对 progress，测试 shrink、frontier advance、regression 与 A-to-B-to-A 四种结果；
- 对 Builder/Judge，先修可行动 crash/first-write/Integration evidence，再以真实 Diagnostic lane
  验证，不让 diagnostic 进入 release closure；
- 对删除，先做 rg、call graph 和 regression 的活跃性证明，再删除一次 authority，而不是双写适配。

### P3 — Direct 全闭环，不跳过昂贵后缀

同一新 Direct job 在 exact commit closure 上依次产生 Design、Candidate、Integration、Verifier、
ReleaseAssurance、TelemetryReleaseSummary、Package 和 RegistryPublication。Build/Integration 可复用已
通过的精确依赖，但 Verifier 缺失只 block release，不能抹去 Build/Integration；ReleaseAssurance 只复用
匹配的 Integration evidence，并额外做真实 fresh deployment/reachability/property/sealed。随后运行
未知 seed/task 的 framework consumer cold-start Reset/Step。成功才满足 E1。

### P4 — Expand 统一与最终全路径验收

在 E1 后将 ExpansionSeed 接入同一 WorkGraph/leaf registry/RepairLedger/BudgetLedger，删除
ExpansionDesignDraft 与其 component-local run_structured_agent retry loop。先以 topology/repair
regression 证明 Direct 和 Expand 只在 seed 不同，再做 P4 的两个真实 campaign outcome。只有 Direct、
negative rework、Expand 和 consumer evidence 均满足本文完成定义，才可 archive 该 task。

## 每次真实运行的最小报告

报告必须列出 request/campaign id、Git revision、plan/config/profile digest、model、各 stage Artifact refs、
actual/unknown/reserved token/tool/process usage、每次 RepairAction、frontier transitions、保留/失效
sibling、Registry/consumer 结果和停止原因。禁止记录密钥、base URL、原始 prompt/transcript、sealed case、
EvaluatorGoal 或 expected state。失败是合格结果，前提是它有精确 owner、可复现实证或明确的下一条
判别证据；不能把它重命名为“完成”。
