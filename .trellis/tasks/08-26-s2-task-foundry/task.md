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
- 实证：真实 ocean fresh Codex thread `01a04888-a0ae-7d31-b307-a16d6317c26f` 一次 author turn 通过 7/7 Framework checks；project digest `11ed3820d816cb1eb720f2fc62ed503dd1f983ffd9aecf2d0fa549c58acb82f1`，9 张 mutation license 与全库门通过。CP3B 完成；CP3C 尚未开始。
