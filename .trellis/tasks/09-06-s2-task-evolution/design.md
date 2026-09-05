# S2 递进采样设计：复用现有流水线的完整算法

> 2026-09-06；planning。依据 `s3-sft-trajectories@17a87ab` 的现有代码。  
> 本文替代先前通用状态映射/全面格式迁移方案。一次完整交付，但不扩建无直接必要的基础设施。  
> 下述新增类型、参数和命令均为待实现规格，不是已存在的 API。

## 0. 固定设计决定

| 保留并完成 | 明确删除的前置负担 |
|---|---|
| 三种业务扩展、固定意图、独立 fresh 执行、有限递进 | 全局 Tool Graph、任务生成模型训练、通用规划平台 |
| 现有 TaskDraft/AnswerProjection 输出方式 | Witness 新终止协议和强制独立 Extractor |
| 纯结果修改任务的最小终态 Goal 修复 | 自动实体映射、可编程断言、任意时点/多解 DSL |
| 高效求解、原因反馈、代表案例干预实验 | 每个任务必须跑完整删步与 2×2 场景生成系统 |
| 现有实例隔离、批处理、失败记录与冷读 | 新服务、队列、注册中心、会话中间状态恢复 |
| 必要的契约升级和消费者同步 | 预先规定全部 Task/Episode/TrainingView 必须升级 |

实施不要恢复已删除的强制要求；也不能把精简解释为不修已知假阴性或不跑真实验收。

## 1. 工作机制

```text
真实 Release + 既有公开根任务
→ 选择父任务和一个业务扩展方式
→ 提案器给出完整子任务及增量说明
→ Host 冻结 instruction、合法 reset 输入与输出要求
→ 独立采样会话 fresh 执行，返回既有 TaskDraft/AnswerProjection
→ Host 来源校验、完整修改归因、任务与证据对齐审查
→ 现有 materialize_candidate：真实 fresh replay
→ 五次现有独立准入，至少两次通过
→ 两次新高效策略探测；发现短解/误判/无增长原因
→ 去重、记录父子关系、能力/长度/依赖分档
→ 正式 TaskPack，读取落盘包，记录 assessment
→ 有真实增量的后代进入下一轮有限队列
→ 冻结 corpus，由现有 S3 采集 rollout、重开验证、冷读
→ 冻结后的独立比较报告
```

执行者始终高效完成，生成器才负责增加合理业务工作。任何地方都不能把更多调用直接变成 reward 或任务成功条件。

## 2. 复用边界与少量新数据

复用 `prepare_release_v3_internal`、`sample_task_draft`、`materialize_candidate`、`filter_candidate`、`seal_task_pack/load_task_pack`、`run_task_episode`、`write_episode_bundle/read_episode_bundle`。新增提案和分析代码，不复制已有工具分派、schema 投影或原生环境加载器。

新数据只需三组，优先放在独立 campaign 记录，不给每个概念建一个包：

### 2.1 FrozenIntent（固定采样请求）

```text
format, request_id
release_id
reset_start: object | null
instruction: string
requirements[]: {text, intent_span, evidence_role}
answer_fields[]: {name, public_meaning}
```

Host 用 canonical JSON 重算 ID；`requirements` 的文字必须在 instruction 中有对应含义，不能隐藏追加条件。它是审查说明，不是可编程断言。固定答案字段只有名称/语义，没有 expected 值。

`reset_start` 是 Host 输入，不能将整个配置泄露给模型。求解所需信息必须在 instruction、reset observation 或公开工具中可得。

### 2.2 EvolutionRecord（提案、谱系与终态）

```text
job_id, root_id, parent_task_id, round, operator
intent_id, task_pack_id | null
delta: {retained_goal, added_work, public_resolution, changed_start}
terminal, reason_codes, evidence_refs, costs
```

这是一个追加/原子写入的普通记录；不创建 Registry。`delta` 只给提案器和评估，不给子任务执行者。

### 2.3 ComplexityAssessment（任务外分析）

```text
task_id, protocol_id, model/prompt/budget identities
success_counts, all_known_route_lengths, independent_probe_lengths
L_best_all, L_best_probe
growth: capability, dependency, length
dependency_evidence[], shortcut_diagnosis, audit_refs
```

无成功独立 probe 时 `L_best_probe=null`。assessment 更新不改变 Task 真值。保留原始引用，摘要不能取代完整 capture。

## 3. 提案和执行：两种职责，不搭多 Agent 系统

### 3.1 提案器

输入：父任务公开 instruction、公开业务 brief/工具定义、已有公开探索摘要、选定算子、允许起点的公开描述、前次短解原因。不要传整包 TaskPack、隐藏 Goal、原生快照或参考答案。

输出：完整子题目、保留/新增工作、对象定位方式、从允许列表选择的起点、最小答案字段要求。一个结构化模型调用即可；已有公开信息不够时，可复用当前公开采样能力在可丢弃实例进行有预算探索，不强制每题都加一次独立 Scout 流程。

提案可以使用父任务公开 ID 来寻找新描述，但新执行会话不得看到这些父任务信息。不得生成每题代码或一个由工具名拼出的强制步骤列表。

### 3.2 固定题目采样

在现有采样入口增加明确的 fixed-intent 请求类型。可使用 `SamplingTarget | FrozenIntent` 的小型 tagged union：二者都提供 `target_id/request_id`，原有 target 继续服务直接采样对照；新请求不伪造 `required_goal_shape` 或强制 focus tool。

现有 `TaskDraft.sampling_target_id` 绑定实际请求摘要；如保留字段名，在文档中说明它代表采样请求身份。不要填假 target 只为绕过验证。

将 `_validate_sampled_draft` 分开为共同的内在校验和仅对 coverage 请求生效的目标覆盖校验；fixed-intent 请求允许自然形成可支持的 Atom/All/If/ForEach，不能随机挑形状后逼模型凑结构。

固定采样会话只收到子题目、fresh reset observation、ToolSpecs 和通用 Draft/AnswerProjection 语法。禁止传父摘要、增量理由、探索 trace、正确 ID、隐藏期望或最低调用数；`prior_accepted_summaries` 在该会话为空。完整业务 brief 留在提案端，避免给执行者追加题目之外的要求。

执行后沿用现有终止结构返回 TaskDraft 和 AnswerProjection。Host 要求 instruction 与冻结文本逐字一致，并核对实际输入摘要。不另造 `done` 协议，也不强制增加 Extractor 服务。现有有限格式修复可保留，但不能改题、重复执行已完成修改或在预算外追加新行动。

### 3.3 意图—证据审查

先保留机械保护：参数来源、真实调用序号、答案 pointer/schema、fresh replay、所有修改都能归入任务的真实工作，不删除 `unexplained_sampling_mutation` 的保护意图。

再用一次独立、只读的质量审查列出：每项需求的真实公开证据、是否只做了部分目标、是否混入无关修改、答案是否多加字段、对象是否明确、哪些读只是发现手段。审查可采用配置中的同一模型新上下文，不需要多模型平台；它不能执行工具、改题、生成 reward 或覆盖确定性失败。

审查有歧义时隔离候选；不是返回默认 true。对照和新算法使用相同审查标准并记成本。代表正反例需要独立检查，不宣称模型审查已经形式化证明自然语言语义。

要求变更必须作为新提案计入预算并从 fresh 重新执行。语义不变的编码修复才可复用该次证据。不能失败后缩成“查询一个字段”冒充完整扩展成功。

## 4. 三种扩展算子

### O1 prerequisite：把已有准备变成需要完成的业务阶段

从父任务的终点出发，查找当前默认世界、父任务合法 reset 或配置白名单中存在的早期对象。让子任务自己完成必要前置阶段，再达到相同业务终点。

示例是“已分派请求的预约”扩为“定位未分派请求、完成合规分派并预约”；具体规则必须由实际 Release 支持。提案选择的是早期业务情境，不能先解除分派/破坏状态再修复来凑长度。

参数化 reset 仅接受实际发布的 start schema 与已验证输入；每个新起点做两次 fresh reset 一致性检查，并正常 replay。不做自动 reset 配置生成器；没有更早合法状态就记录 `start_unavailable`。

### O2 discovery：把内部 ID 换为用户能够提供的唯一业务描述

保留真实用户可知的条件，通过公开实体关系或筛选找目标。需要完整范围与唯一性证据；分页不完整不能用 protected state 替 Agent 断定唯一。

同义名称替换未增加信息工作时，记无增长。一个合法查询已足够定位时接受，不删工具、不加分页、不强迫逐级查询。执行者从零获取目标 ID，不继承父任务上下文。

### O3 outcome_extension：从局部动作扩到相关业务结果

只增加同一意图中的相关终点，如取消及满足公开条件的退款。条件、对象、字段和合法操作均来自真实环境；不拼接无关查询或把工具自身稳定拒绝当成新增成功结果。

允许当前 Goal 能可靠表达的条件实例。一个冻结起点下只验证实际分支，不能把未执行分支称为已验证。新增结果无法可靠验收则记录 `representation_unsupported`，不另建通用条件语言。

### 共同规则

三个算子只是一个提案器的三种模式，共用后续全部函数。新任务必须保留连贯用户目的且增加信息、状态或业务结果要求；不是单纯文本变长。

父子对象/起点改变要记录，不能把所有长度差归因于算子。多对象重复属于宽度，不自动叫依赖深度。算子未成功、无增量和模型失败分开统计。

## 5. 验证修复：使用现有终态，不建设通用语义映射

### 5.1 精确终点支持域

本任务围绕唯一对象、稳定整体 `read_state` 投影和最小复制型答案。继续精确校验 reset、before、after、答案 schema/值；不加忽略 metadata 的宽泛掩码，也不根据参考 diff 自动许可副作用。

确定性 replay 只证明相同操作可重现，不证明所有合法解终态相同。发现合法解具有不同生成 ID、历史顺序或其他语义等价表示时，记录 `verifier_disputed/representation_unsupported` 并排除该候选；不能通过强制参考 ID、查询工具或执行顺序让它“变合法”。

这是范围限制，不是解决了任意多解。真实 Release 中若没有足够合适任务，应报告效果未达到或具体环境/表示缺口，不能靠排除全部候选宣称成功。

### 5.2 取证调用与业务目标分离

普通 list/inspect 等用于确定对象或获取参数的调用保留在真实 trace 和来源证据中，不因执行过或为了工具覆盖就成为强制 Goal。直接查询任务另按其本来语义处理；本次新增的扩展成果以含真实业务修改的任务为主，不要求顺带重写全部纯查询评测。

不能只删除任意查询 Atom 而忽略它是否是用户明确要求的信息结果。输出必须有公开事实支持；删去取证方式约束不等于允许猜答案。

### 5.3 最小的纯结果节点

仅去掉读 Atom 不能解决等价写路径。因此本任务明确允许并实现一个小的 `FinalStateGoal` 叶节点，不引入实体 selector/关系查询/通用断言 AST。

其唯一语义是：该任务是经过审查的纯结果状态修改任务，`expected_before != expected_after`，实际 after 必须等于已冻结的 expected_after。外层仍同时执行原有 reset/before/答案/source 检查。节点不是无条件通过；不得关闭任何状态比较。

Draft 仍先引用实际完成的修改步骤。Host 在完整 replay、逐项需求覆盖和副作用审查通过后，才将普通结果目标编译成一个 FinalStateGoal。原始步骤作为构造证据保留，不成为未来路线要求。

这样，`list → A → B` 与 `inspect → C` 若在公开信息下达到同一个合法冻结终点，应均可通过，不为它们建立工具名别名白名单。若 C 合法地缩短整个流程，接受并降低长度分档。

明确要求审批、检查或其他过程的任务不能无条件编译为 FinalStateGoal。只有环境原生前置检查/已有可靠持久历史或当前已支持的过程验证能够落实该要求时，才发布；必要过程必须有反例测试。无法验收的中途禁止项或过程要求是范围外候选，不用终态相同冒充合规。

最终状态中的错误副作用仍可能被参考执行带入，故编译前必须核对用户要求和已有环境语义证据；模型审查并不取代错误对象、遗漏结果、无关修改等独立反例。

### 5.4 公开来源与共享判定

复用 `derive_argument_origins` 和现有答案投影，不实现任意推导语言。同值能被复制不等于已证明因果依赖；依赖分析须另外检查实体、字段、时间和实际消费。需要未支持计算或自由生成内容的候选明确记录表示边界。

提取一个小的共同 completion-validation helper，组合现有公开来源检查和 `evaluate_goal`，给 S2 filter、效率探测和 S3 共同调用，避免来源合格与 Goal 通过分叉。S3 额外保留 post-reopen 可信性要求和 `1/0/null` 优先级。

共享 helper 的结果和原因必须能由密封产物复核，不能只在内存里加检查却让 cold reader 忘掉。语义/source/evaluator 修改使用明确的验证版本；对受影响旧候选重新验证，不原地改旧 reward。具体持久字段和必要版本传播在实现差异表中逐个说明，不预设整个产物系统都变。

## 6. 高效策略、短解和反馈

### 6.1 只接入实际需要的策略差异

现有 Host 固定检查全局 PUBLIC_AGENT_PROMPT_DIGEST。改为由 Host 显式选定默认/高效 prompt，实际文本摘要必须与 PolicySpec 相同，并写入已有 public capture。默认调用保持默认 prompt；driver 不得私自替换。

复用现有模型 route、driver 和 turn 预算，不建立七个 PolicyProfile 子系统。高效提示只要求不遗漏条件、公开取参、合理使用批量/直接工具并减少无关操作；不能包含参考路径、目标长度或正确 ID。

当前 sampler 与 public policy 的 retry 设置不相同。沿用/调整时分别记录 SDK 传输重试和外层实例重试，设明确有限上限，不把它们混成新的语义求解次数；无需重做全部 provider 基础设施。

### 6.2 探测协议

生产阶段：保留五次完整 admission，另跑两次高效求解。五次准入不能为节省成本提前在两次成功时停止，也不能额外跑第六次补成功。两次效率探测的正常失败如实保留，不当作不可压缩证明。

`L_best_all` 是全部已确认公开合法成功路线的最少真实分派 tool calls；`L_best_probe` 是某个冻结独立探测批次的最少值。没有该批次成功则为 null。记录模型、实际 prompt 摘要、turn/token 设置、次数、成功次数和完整 trace 引用。

工具调用统计包含真实业务拒绝，未分派协议错误另列；reset、protected read、replay/审核内部操作不算求解工具数。模型失败后的反复查询不能当成任务自身难度。

真实最短长度 `L* <= L_best_all`。只能报告最短已知，不能报告已证明最少 N 步。效率预算不同的最小值不能公平对比。

### 6.3 简单、可解释的反馈

记录以下原因并影响同一父任务的下一次扩展方向：

| 观察 | 下一次动作 |
|---|---|
| 新增前置条件在起点已满足 | 改选已有合法起点或停止该 O1 方向 |
| 一次合法查询覆盖了发现需求 | 记 O2 无长度增长，不禁该查询；转向其他真实依赖 |
| 子任务仍可一步达到终点 | 保留有效短任务，换新增工作而不是要求多调用 |
| 未完成冻结目标 | 保留真实失败，禁止缩题；新提案消耗新的预算 |
| 正确更短路线被 evaluator 拒绝 | 隔离争议、形成最小反例；不能作为依赖增长 |
| 缺少公开字段、合法起点或工具能力 | 按实际证据记来源/起点/环境缺口；未解出不自动等于缺能力 |
| 高效求解失败 | 仅记未找到更短解，不自动奖励其“困难” |

反馈只给提案器，子任务执行者与 S3 不见父/参考信息。反馈是原因摘要，不是附上隐藏答案的下一题提示。

## 7. 去重与递进队列

### 7.1 不建设万能语义聚类器

保留现有 task/pack 身份；在 campaign 层维护精确实例键和谱系。已有 `_structure_id` 只作候选重复线索，不能在 filter 前直接删掉所有相同结构的 fixed-intent 候选。

精确重复：同 Release/reset、相同冻结 instruction 和相同任务证据契约拒绝重复发布。语义重复：相同结构桶内比较公开目标、对象定位方式和新增工作，使用小的结构摘要与必要的只读配对判断；纯改写/换 ID 归同家族，不宣称自动证明完整语义等价。

O2 与 direct-ID 即使 final effect 一样，也应保留可核验的不同定位要求。反之，长描述但无实际新增信息负担，不能仅因摘要不同算新能力。

根、父、轮次、算子记录在 sidecar；子任务继承根分组。已识别跨根重复合并/隔离报告，不能只按谱系假定完全无泄漏。此任务不训练模型，不要求建设全局 train/test 分配引擎；产物必须足以供后来按家族隔离。

### 7.2 有限队列而非学习调度器

默认最多 12 根、3 轮、每父每轮 2 个提案、每根下一轮最多 1 个后代，总提案上限 72。三个算子轮转覆盖；使用 seed 和 job_id 确定顺序，必要时均匀补根，不无限重试。

仅有效、连贯、非重复且有证据新增工作的子任务可进递进队列。capability_growth、dependency_growth、length_growth 分开记录；有业务增量但工具数未增可保留任务，但不计作增长的长任务。

排序用固定规则：有证据的增量、家族/环境覆盖、目标长度档位缺口、成本。同分稳定排序；不直接按调用越多分越高。首个可运行完整算法不依赖 EMA 成本调度或强化学习。

每轮固定输入与 job 清单。复用原有 Release-level 并发方式，实例内因果串行；每个 worker 独立 prepared/context。完成顺序不决定下一轮选择，模型随机性不等于可完全复现同文本。

### 7.3 恢复与预算

复用原子写与 terminal record。已完成 job 跳过；中断实例不可复用为 fresh，保留证据后从新的实例恢复该未完成尝试，基础设施重试有限。正常模型失败是已完成语义尝试，不能 resume 再跑。

配置和输入摘要冻结。修改模型、prompt、预算或语义规则开启新 campaign，不继续写旧目录。不恢复模型会话内部推理/checkpoint，不新建状态服务。

记录所有提案、构造失败、审查、replay、五次准入、两次效率探测和 S3 的成本。总提案/运行次数硬上限；token 上限若只能在请求结束后观测，披露最后请求造成的超额，不能声称绝对精确预算相等。

## 8. 正式发布、格式与 S3

新增进化/评估元数据放在 task 外 sidecar，引用真实 TaskPack ID；不要把长度、父任务摘要或审核轨迹塞进 PublicTaskView/TrainingEpisodeView。

沿用正式 seal/load，产物密封后必须从磁盘重新加载再交给 S3。保留每个配置 rollout，包括 0 和 null，不追加到每题都成功。高效探测和 admission 不冒充独立 S3 训练 Episode。

仅因新增 FinalStateGoal 或共同来源判定而真正改变语义/字段的契约，需要明确版本并同步全部受影响 readers。先写差异表：旧新数据结构、语义、身份预映像、生产者、消费者、冷读测试。没有变化的 outer envelope、Episode 或训练视图不强制升级；若确实受影响必须完整修复，不能以少改为由漏掉。

最小 FinalStateGoal 是共享 evaluator 的新增能力，不是另开一条新奖励路径。旧已密封任务不能在原 ID 下换解释；旧运行产物留在旧基线验证。需要从旧 reader 提取公开根任务时，一次性生成经过身份验证的种子快照即可，不建设长期双版本导出平台或隐式兼容 fallback。

来源/Goal 的新增含义在运行及产物中必须可识别。模型策略配置变化与验证语义变化分别记录，不能借 prompt ID 掩盖 verifier 版本。

Cold verify 重算实际格式/摘要/公共投影及 verdict 一致性。把声明依赖复制到新根，使用新缓存做读取；不依赖原内存对象或运行目录。不要承诺冷读会重新调用模型，也不要把字节冷读等同于重做语义审查。

## 9. CLI 和输入

新增一个薄入口 `scripts/run_s2_task_evolution.py`，以配置/模式复用同一 pipeline，不新增服务。要实现的命令是：

```bash
uv run python scripts/run_s2_task_evolution.py run --config CONFIG.json
uv run python scripts/run_s2_task_evolution.py run --config CONFIG.json --resume
uv run python scripts/run_s2_task_evolution.py verify --campaign-root ROOT --relocation-root NEW_ROOT
uv run python scripts/run_s2_task_evolution.py compare --config COMPARE.json
```

这些命令是待实现接口。run 开始时做输入检查并输出 resolved-config/input-manifest，缺项在付费大批运行前明确失败；无需单独建设 doctor 产品。

配置最少包含：

```text
source_commit, seed, mode
s1_campaign_root, seed_corpus_or_snapshot, release_ids, seed_task_ids
output_root, model_route, generation/admission/probe turn budgets
max_roots, max_rounds, proposals_per_parent, max_proposals
release_workers, infrastructure_retry_limit
standard_prompt_id, efficient_prompt_id
s3_rollouts_per_task, independent_evaluation_protocol
```

账户凭据来自现有环境配置，不落盘、不提交 Git。localhost 服务属于执行机器，不能假设本容器能访问用户代理。Report 中写出的路径只是线索，必须检查实际文件与 manifest 身份；不读取不相关用户目录。

推荐默认按上述 72 提案有限搜索、S3 每任务 2 次、效率探测每候选 2 次。route/timeout/turn budgets 从实际可用服务和既有配置明确冻结；不猜新模型、不升级依赖来掩盖报错。

简单产物目录：

```text
campaign/
  config.json, input-manifest.json, run-contract.json
  rounds/<round>/schedule.json
  attempts/<job>/proposal.json, intent.json, review.json, terminal.json
  attempts/<job>/...既有 sampling/replay/filter/TaskPack 产物...
  assessments/<task>.json
  lineage.json, corpus-manifest.json
  s3/...既有 Episode 成对产物...
  verification.json, evaluation.json, REPORT.md
```

没有单独的 ReleaseBinding registry、多层 StateBinding 包或与需求无关的格式清单服务。该目录可调整命名以复用现有脚本，但交付时写明实际格式和运行命令。

## 10. 评估：代码跑通与任务变好分别验证

### 10.1 同一支持域的三个基线与一个消融

| mode | 方法 |
|---|---|
| direct_coverage | 现有形状/工具覆盖导向提出候选 |
| intent_direct | 提出完整业务目标，固定题目执行，但不使用父子递进 |
| evolution | 三种算子、有限递进及短解反馈 |
| evolution_no_feedback | 同一递进策略，短解结果只记账，不用于前沿选择或下一题反馈 |

它们共用当前审查、来源、终态、准入、支持范围和报告。mode 只影响生成/选择，不可使用不同真值或通过标准。固定后单独跑所有组同等预算的最终高效探测；no_feedback 不能在生产阶段偷用效率结果改变选择。

既报告等提案数，也报告总 token/模型请求/真实调用成本。若效率审计是新增成本必须纳入。不使用历史旧 verifier 的 69 任务成绩直接充当本次同条件基线。

### 10.2 每个任务必要的检查

真实 replay、五次准入、两次效率探测、完整要求/副作用审查、重复/谱系记录。短但有效保留；与长度分档不匹配不改 reward。

### 10.3 代表案例的深入分析，不变成逐题生产引擎

从预先声明的样本规则选取至多 6 组父子任务，覆盖不同环境与算子；每组最多 3 次删步/替换或合法匹配起点实验。保留没成功分析的案例，不只挑漂亮样例。

固定路线删步与新 Agent 重规划分开记录。移除发现动作后，不允许沿用仅该动作返回的旧 ID；来源无法重新绑定只说明此见证依赖未解析，不是全局无短解。

有合法匹配起点时，对比直接 ID/公开发现或准备完成/需自建条件。无相应 reset 就如实报告，不写自动 2×2 世界生成器。E1 是真实来源/状态证据，E2 是有效局部干预支持；两者都不是所有可能路线的必要性证明。依赖图仅作本任务局部分析，不进入 Goal 或 Acting context。

### 10.4 最终指标与允许结论

输出阶段通过/失败数、至少按 Release/根/算子/轮次分布、独立家族数、参考到高效路线压缩量、L_best_all/L_best_probe 与成功次数、来源/验证争议、有效中长任务产率和每任务/家族成本。

任务加权而非 rollout 加权；同根作为相关样本处理。失败较长可能源于重复试错，不能当复杂任务证据。随机性和小样本不确定性如实记录。

只有新增任务跨环境、真实增量经审查、正确短解开放且相对 intent_direct 有有效质量/成本改善时，才可说该方法缓解了采样偏简单。没有 S4 训练，不能报告模型提升。效果不确定不是让代码占位或验收造假的理由。

## 11. 具体改动清单与止损边界

优先仅新增 `task_evolution.py`（请求/提案/队列）和 `task_complexity.py`（探测/分析）及薄脚本，普通记录靠现有 JSON 工具。职责确实过大时可按实际责任分文件，但不为名字齐全建大量空模块。

| 现有位置 | 本次必要工作 |
|---|---|
| task_proposal.py / task_draft.py | fixed-intent 请求、固定文本校验、复用终止格式、共同校验与 coverage 偏好分开 |
| task_candidate.py | 复用 replay，保留全部修改证据；审查后编译纯结果 Goal；去重不误删发现扩展 |
| task_goal.py | 小的 FinalStateGoal、严格 reader、原有节点回归；不引入通用 selector/关系 AST |
| task_admission.py | 复用五次准入/封装，提取与 probe/S3 共用的来源+Goal 判定 |
| public_agent.py | 默认/效率 prompt 注入、实际摘要一致性；保留一个 Host loop |
| episode_runtime_v2.py | 调用共同判定并保持重开/奖励责任；正常使用正式 TaskPack |
| artifact/batch/source readers | 只做实际新语义/字段所需适配与 cold tests，禁止全套盲升版本 |
| S2 campaign helpers | 真实 manifest 子集、复用原子落盘/并发/统计；不复制一份业务 pipeline |

如又需要自动状态映射、任意时序逻辑或重建 S1 才能继续，说明越过本任务范围。先用明确的可执行反例判定缺口并记录，不默默扩大。与此同时，FinalStateGoal、三个算子、反馈、正式 S3 接入等已明确的必交能力不能以表示限制为由跳过。

## 12. 审查依据

当前代码事实以 `17a87ab` 上以下符号为准：`sample_task_draft`、`_validate_sampled_draft`、`derive_argument_origins`、`materialize_candidate`、`_structure_id`、`evaluate_goal/_atom_matches`、`_filter_attempt`、`public_agent._capture`、`run_task_episode`、Episode paired reader。

本设计基于读取的远端代码与任务材料，没有执行用户本机 20 个 Release。任务递进、深度扩展和短解反馈是方法借鉴与项目改进，不在本任务中声称首次提出。具体实现和实测以交付的 commit/manifest/report 为准。
