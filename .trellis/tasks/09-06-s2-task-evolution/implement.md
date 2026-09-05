# S2 任务递进采样：完整实施与验收指令

> 本任务只有一个最终交付。下面是内部依赖顺序，不是分期版本，不要求用户逐个批准。  
> 当前为 planning；本次准备计划不启动 worker、不改算法、不运行付费实验。

## 1. 启动已有任务

获得实现指令后，在确认过的仓库根目录执行：

```bash
TASK=.trellis/tasks/09-06-s2-task-evolution
python3 .trellis/scripts/task.py validate "$TASK"
python3 .trellis/scripts/task.py start "$TASK"
python3 .trellis/scripts/task.py current --source
```

先按 `AGENTS.md` 和 `.trellis/workflow.md` 读上下文，复用这个任务。不要重建同名任务；如果实际 CLI 行为与文档不同，查看当前 `--help`/源码并记录，不假装命令运行了。

按 `implement.jsonl → prd.md → design.md → implement.md` 加载完整材料；不要因上下文截断只读前半篇。使用仓库 channel implement/check workflow；主会话负责集成，worker done 不是整个任务完成。当前文档替代旧版大范围规划，不能从 Git 历史再把删除项加回来。

## 2. 基线保护和真实输入

确认 `s3-sft-trajectories` 当前 HEAD、dirty paths 与 `17a87ab` 的差异。用户本机目录为 `/home/kelong/pycodes/foundry-s3-sft-trajectories`，必须实际确认；保护所有未知修改和历史运行数据，不使用 reset --hard/clean 来获得干净工作区。

读取实际 S1/S2 manifest 和发布包，核对 Release/TaskPack 身份。报告里的路径只是线索。使用现有 prepare/reader 验证依赖和文件，选一个真实旧任务经既有 S3 与冷读形成基线日志，不重新生成环境替代。

在会改变 reader 的修改前保存所需根任务的公开 instruction、Host reset 配置、Release 引用和验证过的源 ID。此快照不含供提案器使用的隐藏答案/Goal/参考 trace。必要时保留只读基线 checkout 读取旧数据，不创建长期 legacy 运行平台。

记录基线测试结果、模型路由、实际 system prompt/预算。凭据缺失、代理不可达、锁定运行时无法准备分别报告；不切换模型、不升级依赖、不用 fixture 补齐真实验收。

## 3. 一次交付中的实施顺序

### A. 接上固定意图与原有流水线

在当前函数上增加 fixed-intent 请求，保持采样执行后输出 TaskDraft/AnswerProjection。不要另写工具 loop、done 终止协议或 Extractor 子系统。独立执行上下文不含父信息，Host 比较实际题目与冻结题目。

分开共同有效性校验与 coverage target 校验。fixed-intent 不伪造 target，也不强制使用未完成覆盖的查询接口。先用真实例子检查新 request → materialize → filter → seal → load → S3 → cold read；该内部回归不作为最终停止点。

### B. 完成明确的验证与策略适配

实现 design 第 5 节：辅助读取不作为默认路线约束；纯结果修改用小的 FinalStateGoal 和原有完整终态/答案/source 检查；明确过程要求不能靠结果节点绕过。保留全部修改的审查与反例。

将 source+Goal 的组合检查抽成共用函数，S2/probe/S3 一致，S3 增加的 post-reopen 检查不丢。默认/效率 prompt 通过 Host 注入并校验实际摘要，禁止删除摘要检查。

列出真正变化的持久化契约及消费者，只升级这些契约；绝不盲升全部格式，也不能静默让旧 ID 使用新判定。受影响的所有 reader、请求身份、批处理和 S3 adapter 必须接通后继续。

### C. 完整算法与运行入口

同一提案器实现 O1/O2/O3，串入已经接通的固定意图链路。实现两次效率探测、诊断反馈、精确去重/相似桶审查、根谱系、有限递进队列、固定日程与失败记账。

复用当前 Release-level 并发与原子写入。完成 job 跳过；正常模型失败不重试；中断未完成实例保留后从新实例恢复，不能恢复成伪 fresh。

实现 design 第 9 节的 run/resume、verify 和 compare 薄入口。run 包含输入检查，配置不含密钥，真实产物、输出和模式都绑定摘要。不要给用户留下只有库函数、不能完整运行的模块集合。

### D. 全部真实验收与对照

三个真实环境、固定根/轮次/提案预算运行，记录三种算子的每个结果。发布包磁盘重载后进入官方 S3，成功、失败、null 都保留，全部密封产物做本地/迁移冷读。

运行 direct_coverage、intent_direct、evolution、evolution_no_feedback。最后使用未参与选择的独立 probe。按 design 的固定样本规则做代表父子案例的局部干预，不建逐题自动世界生成平台。

发现自己引入的代码/格式错误就修复并重跑受影响测试；不要在一个算子、canary 或部分表格后停止。真实采样未达预设验收数时保留所有结果、分析原因，不无限追加采样或降低 Good Task 门槛。

## 4. 行为测试矩阵

下列项应映射到真实测试函数，可合并文件，不需要为每条建立独立框架。现有全部回归保留；新协议内容不得只靠字符串包含测试证明。

| ID | 必测行为 |
|---|---|
| T01 | 固定题目实际传入会话；返回缩题/改条件时拒绝，原 coverage 模式仍可运行 |
| T02 | 执行者输入泄漏检测：父摘要、隐藏 ID、Scout trace、expected、长度目标均不得进入 |
| T03 | 现有 Draft 终止协议可推导答案 schema，无独立 Extractor；schema 不含答案常量 |
| T04 | 未完成需求/未解释修改/多加答案字段不能因 trace 非空就通过 |
| T05 | 旧来源保护保留；未公开 ID、同值不同实体、未支持派生值有准确错误归因 |
| T06 | list 和 inspect 等价取证后达到同一结果均通过；不能需要参考辅助查询 |
| T07 | FinalStateGoal 在未变化、错误终态、错答案时失败；另一条公开写路径达到同一正确终点通过 |
| T08 | 不能从不含全部修改/混有无关修改的 Draft 自动编译 FinalStateGoal |
| T09 | 明确需要审批等过程但无可靠证据的候选不发布；已支持过程的绕过反例失败 |
| T10 | 生成 ID/历史顺序不同的正确解触发表示/验证争议，不硬编码参考选择或掩码 |
| T11 | S2/probe/S3 对同一健康 capture 的来源和任务判定一致；post-reopen 故障为 null |
| T12 | 默认和高效 prompt 真实生效并各自绑定摘要；摘要不一致拒绝、driver 不复用 |
| T13 | 原有 five valid runs/2 passes 边界；不提前停止、不加第六次，不把 provider 故障当语义失败 |
| T14 | O1 可行前置扩展、前置已满足、缺合法起点和先破坏再恢复四种情况准确区分 |
| T15 | O2 唯一定位、分页不完整、名称改写无增量和父信息泄漏的正反例 |
| T16 | O3 合法关联结果、无关拼接、实际条件分支与未执行分支的边界 |
| T17 | 公开 reset schema 校验和两次 reset 重建；所有 Witness/replay/filter/S3 独立实例 |
| T18 | 参考 10 次、合法高效 4 次时按 4 分档且仍成功；无成功 probe 长度为 null |
| T19 | 不同协议预算最小值不能混算；真实调用与 reset/Host 验证开销区分 |
| T20 | 短解原因改变下一提案，不泄漏给 Acting；无增长任务不奖励为长任务 |
| T21 | direct-ID 与 discovery 不被旧结构键硬合并；改写/换 ID 不增加独立家族数 |
| T22 | 根/父关系闭合，后代分组继承；已识别跨根重复记录或隔离 |
| T23 | 轮次、提案数、每根前沿有限；有效性不由长度阈值决定 |
| T24 | 冻结调度与 worker 到达顺序无关；共享 prepared/state-events 不污染实例 |
| T25 | 完成 job resume 不重复，模型失败不再跑；中断新实例恢复且旧证据保留 |
| T26 | 改配置/验证版本不能继续写同一 campaign；原子写和失败后汇总重建可用 |
| T27 | 去掉反馈的消融不偷用效率结果进行选择；所有模式共用判定与最终 probe |
| T28 | 每个 TaskPack 落盘后重新加载，真实进入 S3；probe/admission 不冒充 S3 训练记录 |
| T29 | 受影响格式严格 writer/reader/身份回归；未改变格式不盲升；旧产物不改标签 |
| T30 | 全部新密封包本地/迁移 cold read，相同公开投影/reward，篡改与缺依赖能检测 |
| T31 | 代表删步不得回填被删读才返回的 ID；审计失败不自动称必要步骤 |
| T32 | 缺真实文件/凭据/服务明确失败，无 mock 成果；正常 policy failure 仍可完成记账 |
| T33 | REPORT 从产物重算任务/根/算子/长度/成本；无完成条件时不得输出成功验收 |

模型输出 fixture 用于确定性单测，不能作为真实环境成果。对算法有效性需要新模型实际提案、实际工具、正式发布与独立求解。

## 5. 实际运行命令与报告

先记录当前配置下的原有检查：

```bash
uv sync --frozen --group dev
uv run ruff check src tests scripts
uv run mypy src
uv run pytest
python3 .trellis/scripts/task.py validate .trellis/tasks/09-06-s2-task-evolution
```

命令以实际 pyproject 和当前 CLI 为准；原有质量问题单独记录，不用跳过检查掩盖新错误。真实运行通过新入口，最终报告写实测路径，不保留 CONFIG/ROOT 占位符冒充已执行。

交付的 REPORT.md 和机器可读报告至少包含：

```text
implementation_commit / baseline_commit
input_release_ids / task_ids / corpus_id / episode_batch_ids
actual_commands / test_results / changed_contracts
R01..R10 -> code/test/live_evidence 映射
all_stage_counts / rejection_causes / infrastructure_failures
per_release/root/operator/round distribution
L_best_all / independent L_best_probe / success counts / cost
equivalent-route disputes / concrete growth examples
local_and_relocated_read_results
implementation_complete
live_integration_passed
evaluation_completed
effect_status: improved | inconclusive | not_improved
unresolved_defects / external_blockers
```

具体版本变更报告可以是该 REPORT 的表，不要求再造格式管理产品。验收数与效果目标以 PRD 为准；纯脚本退出 0、mock 通过、一个人工样例都不等于真实完整交付。

## 6. 独立检查与过度设计红线

check worker 读取当前任务而非旧版设计，核查：真实固定意图输入、必要验证修复、共享判定、最小改动面、格式传播、真实 S3 消费和报告是否与产物一致。

下面情况必须纠正：为了采样算法新增通用实体映射/关系 DSL、七个长期 Agent 配置、全套版本升级、双版本生产体系、新数据库/服务；或者以精简为由只改 Prompt、关状态校验、放开隐藏参数、只做部分算子或省略真实验收。

内部可以分多个 commit 和有边界 worker，主会话自行集成、测试、修复并完成全部 R01–R10，不在每个检查点要求用户批准下一版。遇到范围外的真实业务缺口，记录反例并明确结果，不擅自重做 S1。

只有完整代码与所需真实验收均有证据，才依 Trellis 完成/归档。外部阻塞与效果不确定要诚实报告，不补假数据、不无限重试、不承诺未验证收益。
