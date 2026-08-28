# S2 Recovery Execution Contract

## Initial Contract (frozen)
Goal: implement the accepted S2 plan in CP1→CP8 order, beginning with complete CP1 contracts.
Invariant 1: only an admitted EnvironmentRelease v2 and its PreparedSession may produce trusted identities, facts or evidence.
Invariant 2: framework verdicts derive from archived physical execution; caller-supplied success strings never authorize a TaskPack.
Invariant 3: clean break—no v1 compatibility, dual reader, fallback path, domain branch or mock completion claim.
Not doing now: no compiler, witness, admission, corpus, Graph/DSL/service or new product node in CP1.
Gold reference: existing S1 locked cold-release/ValidatedEnvironment behavior plus the later real SQLite and filesystem/Git release gates in `implement.md` CP8.

## 追加

- 选择：CP1 合同采用最终 PRD/design 字段矩阵，并要求 `public_tool` 同时绑定 tool name 与 output-schema pointer。
- 备选：直接恢复 `eb47186` scaffold；拒绝，因为它截断了 composition bound、`any_one`、typed report source 和证据绑定。
- 翻案证据：只有新的权威文档决定或真实 CP2/CP3 边界证明该矩阵不可实现，才允许修改；新文件不存在使 mutation 工具无法预先变异，先保留真实 ImportError RED，首次 GREEN 后必须取得逐文件 mutation license 才可提交。
- 选择：Claude 首轮 BLOCK 的 goal-less report、ordering prefix、runtime Literal 与 load-bearing AgentChoice 四类问题全部在 CP1 修正，并删除三份冗余公共编码。
- 备选：把结构闭合推迟到 compiler/runner；拒绝，因为会再次让不可信对象先于生产者成为公共合同。
- 翻案证据：聚焦 18 条测试、全部对应 mutation license、Claude 复核 ALLOW，以及 locked sync/Ruff/format/Mypy/full Pytest 全绿；CP2 只实现这些冻结协议，不得新增平行形状。
- 选择：CP2 先闭合独立 v2 字节合同，再实现 locked preparation 和两个 child runtime；v1 生成路径在 CP4 切除，但 `prepare_release` 永远只接收 v2。
- 备选：一次同时修改 v1 publication、prepare、runner 和 semantics wire；拒绝，因为无法定位格式、安装或进程隔离的首个偏离。
- 翻案证据：Claude CP2 boundary ALLOW；第一垂直测试只证明 v2 descriptor/payload/project digests、完整闭包、v1/tamper 拒绝，不声称可运行环境。
- 选择：CP2 child runner 使用生成项目自己的 venv Python 与 stdlib-only script；Host 执行 schema/codec/origin/tree-manifest 判定，生成代码 stdout 被重定向到 stderr。
- 备选：把 Host framework 安装进两个 runtime 或使用 Host importlib；拒绝，因为会引入依赖复制、ambient import 与跨 release cache alias。
- 翻案证据：12 条真实进程 focused tests、13 条物理 mutation licenses、全库 314 tests 与 Claude BLOCK→ALLOW；CP3 必须消费同一个 PreparedSession，不能新增 loader。
- 选择：CP3A 先在 fresh typed model turn 中冻结 complete Requirement disposition 与 capability/workflow/condition/composition 关系，candidate view 在 digest 固定前不存在。
- 备选：让 Semantics Author 读取 candidate 后自行决定 taskability；拒绝，因为 actor 与 verifier 会共享同一错误来源并可静默遗漏 Requirement。
- 翻案证据：CP3A 的 exact coverage/unknown-reference/Taskable completeness 负例与 candidate-blind provider-input 测试；通过前不运行 Codex Author。
- 实证：7 条聚焦测试、8 张 mutation license、全库质量门和独立 Claude `ALLOW_CP3A` 已通过；真实 Luna strict-JSON 预检从 ocean S1 工件的 4 条已接受关系生成 4/4 disposition、3 个 capability，并由 Host 冻结为 `80f791af8c8ce6135d4cc35a4e75300e7d57e2b65eee0ab494a156440cc1a238`。这只闭合 semantic-freeze core，尚不声称 CP3A artifact staging、CP3B Author 或 CP3C Qualification 完成。
- 选择：CP3A 直接接入 `generate_environment -> run_qualification`，复用现有 Host journal、`_stage_view` 和 Qualification workspace；删除了提前实现的 CP4 cold replay，不建立 `PublicSurface` 子系统。
- 备选：保持 standalone freeze 或新建 staging/loader 层；拒绝，因为前者无生产消费者，后者重复现有物理权威。
- 实证：完整真实 ocean Candidate/Host journal/20 条 accepted relations 一次 Luna turn 生成 20/20 disposition、9 capabilities、2 composition rules；Host 写出 7 ToolSpecs、58 public facts 和四个 0444 输入，expected digest `0790b8ee473b1aa2e9ab1191b635bf812463405e1784dab178a496eefe655b1e`。CP3A 完成；不声称 CP3B/CP3C/CP4 完成。
- 选择：CP3B 将语义判断限定在 Codex 源码/测试/依赖声明；Framework 固定 factory、初始化 uv、执行 source/lock/sync/import/build/tests/catalog 全门，并删除模型 final response 字段。
- 备选：让 Codex 写 manifest/digest/verdict 或让 Framework生成领域 decoder/evaluator；拒绝，前者是假权威，后者把语义硬编码进框架。
- 实证：首轮真实输出虽过旧 7/7 gate，但源码审计发现 query 无 answer contract、StartCase 仅改 ID，已判假绿并废弃。增强合同后，真实 ocean fresh Codex thread `01a04899-d1d9-7221-91a7-82e1e3ae48b8` 在同线程修正并通过 7/7 Framework checks；project digest `51a0454856c16b15d3185ceb10e8d1e7325d89967e30b623ea4562d2ce811f4a`，expected digest `f988810f82200f07476f12d098d0ae45dff65a63e01c71680cd1ce20ffb3d32b`，11 张 mutation license 与全库门通过。CP3B 完成；CP3C 尚未开始。
- 选择：CP3C 删除新增的 Codex Scenario Qualifier；Framework 从同一 qualified StartCase 建立 reset-only before/after 实例，Host-owned Responses Tool Agent 只在 after 上调用普通 actor tools，Framework 用 Host journal、独立 native evidence 和 generated TaskSemantics 判定并把 `SemanticQualificationReport` 接入 release gate。
- 备选：保留 `semantic_probe.py` Codex workspace、让 direct LLM 输出 `$ref` ScenarioPlan、或新增 pair/setup mini-protocol；拒绝，因为分别违反“Codex 只写持久环境/语义代码”、复活已删除的 value-expression DSL、以及掩盖 reset-only StartCase 不充分。
- 翻案证据：只有 SQLite、Git 或 frozen held-out capability 在合法 reset-only StartCase 上无法由 normal public tool episode 演示，且问题不能归因到 StartCase/capability 合同，才允许重新讨论额外协议；旧三脚本 Qualifier 必须另做 causal audit，不在 CP3C 顺带删除。
- 选择：产品 Codex 子进程除 dedicated cwd/fresh `CODEX_HOME` 外必须使用 fresh empty `HOME`，禁止继承用户 `.agents`/plugins/AGENTS；`codex debug prompt-input` 与 rollout locator 是机械 context-boundary gate。当前 CLI 固定 `.system` Skills 只能作为 pinned harness 常量记录。
- 选择：CP3C 的 native truth 保留现有 Builder-independent Qualifier lineage，但改为 qualification-only、按 Host-sealed materialization request 调用的 release-local oracle；“两个 Codex 角色”限定为两个持久 release-runtime 作者，oracle bytes 只进入受 digest 约束的审计证据，不进入 Actor/Consumer surface。
- 备选：让 Environment Builder 同时写 actor 与 native attestor、让 Framework 解释 SQLite/Git、或把 legacy `native_probe.py` 的 `chain/repeat-a` 目录名伪装给 CP3C；拒绝，因为分别恢复自证共因、领域硬编码/State IR、以及兼容剧场。
- 翻案证据：真实 ocean CP3C 证明 legacy probe 与 hash-named materialization ABI 不兼容，且当前 helper 只并列 hash 两份互不对账的证据；新 oracle 必须对同一 request/materialization 输出独立 outcome axes，Host 逐字段与 TaskSemantics 对账并杀死可执行 inspector/evaluator mutants。
- 选择：legacy Actor Qualification 对全部 Requirement 保留正向 public/native evidence，但 source-mutating negatives 只覆盖 candidate-blind ExpectedTaskSemantics 判定的 Taskable Requirements；supporting invariants/refusals 不再为数量而各复制一份 source mutant，CP3C 继续承担 per-capability no-op/answer/process/target/native reconciliation。
- 备选：删除 legacy negatives 或继续对全部 19 Requirement 逐项 mutation；拒绝，前者在 semantics source-mutant gate 完成前留下信任缺口，后者已由真实 REQ-003/006/016 五轮停滞证明高冗余且把不相关 trace 聚合成假证据。
- 实证：稳定 commit `7b9620f` 的真实 ocean run 生成了完整 schema 与 `submitted_pending_review` reset regime，但 legacy Qualifier 因三项不判别 mutation 正确 fail-closed；独立回放确认 Candidate baseline 未失败，下一 lineage 必须 fresh re-author，不再恢复已耗尽五轮的旧 thread。
- 选择：删除 Qualifier 自报的 `covers` 权威；Host journal 显式记录 `open`，禁止 closed/stale wrapper 复用，并仅把 ordered instance/open/reset scope 与生命周期调用当作 topology 事实。业务重建、隔离、持久化与 no-mutation 仍由独立 native evidence/CP3C reconciliation 证明。
- 备选：从全局 journal 猜七类语义布尔、给 journal 增加公开 handle ABI、或用 EvidenceRows 过滤 Semantics Author 输入；拒绝，因为分别是假证明、过度接口化和把 Qualifier 证据相关地泄给 Semantics Author。
- 实证：归档 live seq 33/42 首因是 Candidate factory 未 reattach；fresh-open 与 stale-handle、重复同参调用、scope mismatch、local `$ref` start、`internal_error` refusal、短 ID value reuse 均有 RED/GREEN 与 mutation license；全库质量门通过，独立 causal/cross-layer review 对本 slice ALLOW。CP3C 仍必须把 binding visibility 改为 materialization-local reset+episode trace，不能用全局 public facts 或 injected target 自证。
- 选择：Qualification/Package 不再用 `negative_evidence_count == positive_count`；Host 保存并冷重放精确 `negative_requirement_ids`，要求其为全部正向 Requirement 的唯一非空子集，从而支持只对 frozen Taskable Requirements 做物理负例而不丢审计身份。
- 选择：CP3C binding visibility 改为 materialization-local 两阶段门。episode 前要求每个 public descriptor leaf 来自当前 schema-qualified reset，检查 non-literal binding 唯一性与 exact reset pointer，并从 Agent target 删除 concrete `public_tool` facet values；episode 后只用当前 ordered trace 的 exact successful ToolObservation 验证全部 enumerated bindings，并拒绝 argument-echo/planning laundering。全局 `PUBLIC_SURFACE.public_probe_facts` 只保留 authoring/schema/StartCase 用途，不再证明具体 binding value。
- 备选：过滤 PUBLIC_SURFACE、把完整 target 当作公开证据、或让 native oracle 判 publicness；拒绝，因为分别会相关泄漏/丢合法 StartCase、循环自证，以及让 protected reader 冒充 Actor 可见性。
- 翻案证据：只有真实跨域 materialization 证明 exact reset/public-tool pointer 与 task-literal declassification 无法表达合法公开 operand，才可重新讨论 provenance 合同；不得退回全局值并集或新增通用表达式 DSL。
- 选择：Actor Qualification 的 Host-origin Candidate finding 恢复 exact Builder thread/home，并共享初建以来的总 turn budget；repair 必须产生未见过的新 digest。ExpectedTaskSemantics 与 candidate-blind PredicateCarrier 复用原冻结字节，但 Candidate view、Qualifier probes/thread/home、journals/evidence、Semantics/oracle/CP3C/package 全部新建。
- 备选：整条 Need 重跑、把 raw Qualification details 发给 Builder、复用旧 Qualifier probes，或为 repair 新增 workflow engine；拒绝，因为分别浪费 Research、泄露 hidden verifier、消费 stale Candidate-derived evidence，以及扩大产品节点。
- 实证：exact resume、persistent home、safe finding origin、immutable inputs/current digest、总预算、A→B→A cycle、fresh Qualification root/home、predicate/expected-semantics复用与 raw-detail sentinel 均有 RED/GREEN/mutation；未通过 fresh Actor Qualification 前不运行 Semantics Author/assembly。
- 选择：此前“产品 Codex full-access”决定被真实 sibling-read 反例 supersede。Builder、Qualifier、Semantics Author 改用 Codex 内置 permission profile：deny run parent，精确 reopen 自己的 workspace write；不是自建 sandbox/controller。无模型 `codex sandbox` 实测 Candidate 可写自身文件而读取 sibling Qualification 得到 `Permission denied/No such file`。
- 选择：probe 提供的 invalid reset start 保持 Qualifier-owned `EnvironmentContractError/exit21`；只有 Candidate runtime/load 与 Host-proven fresh reattachment failure颁发 repair finding。finding 只保留 error type/code 和 public arguments，删除 candidate-controlled message/path，SDK resume 异常归一为 typed infrastructure。
- 选择：Actor Qualification 的公开执行拆成三个私有进程角色：Host coordinator 独占 schema/dispatch/journal，read-only public-probe child 只持有 Session JSONL RPC，Candidate child 只写 exact instance root。probe 与 Candidate 不共享 Python stack、run-root 写权限或 journal FD；旧 `--probe`/`--probe-stdin` CLI 兼容入口删除。
- 选择：baseline 与 controlled negative 都从随机 opaque execution copy 运行，Host `execution-map.json` 才绑定 run ID；不得把 `baseline`/`negative` 写进 Candidate 可见路径。真实 Codex sandbox RED 证明旧共享写权限可直接伪造 instance，GREEN 杀死绝对路径写入、probe 读取、原 Candidate/外部 `/tmp` 写入并保留第三方依赖与 negative source-copy 执行；独立 real-process protocol test 杀死 journal 注入。
- 选择：Candidate actor permission 缩到 exact named instance，parent instance root deny，双 live handle 的 sibling 写入物理失败。Session RPC 只验证 envelope/seq/handle，`reset([])` 与 invalid invoke types 必须进入 Host `ValidatedEnvironment` 的既有合同归因，不能被 wire parser 误报 Infrastructure。
