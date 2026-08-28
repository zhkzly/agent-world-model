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
