# Foundry S2：面向有效多步任务的递进采样实现方案

> **文档状态：设计建议，尚未实施。**  
> **设计日期：2026-09-05。**  
> **分析基线：** `zhkzly/agent-world-model`，分支 `s3-sft-trajectories`，提交 `1a6d3421315fc1e1c07961b54f950814ea21d40c`。  
> **目标：** 保持公开可解、真实执行、确定性验证、fresh reset、路径开放等要求，提高任务的业务完整性与有效依赖深度，使一部分任务即使由高效求解器执行，也需要更多有意义的工具交互。  
> **交付边界：** 本文是可供开发实施的规格，不是已经完成的算法、实验或收益报告。

**阅读路径：** 先读第 0 节掌握最终方案；实施时按第 15–16 节拆任务，查第 12–13 节接口和测试；设计取舍与证据分别见第 2–11 节、第 18–19 节。

---

## 0. 先读这一页：最后推荐实施什么

将 S2 从主要围绕 `Goal shape × focus tool × outcome` 采样，扩展为：

```text
选择合格种子／提出新的完整业务目标
→ 选择一种有业务理由的扩展
→ 冻结候选意图与公开 instruction
→ 独立执行者在 fresh reset 下尝试完成整个目标
→ Host 从真实执行中构造并核验 TaskDraft / Goal / answer
→ fresh replay + 五次 fresh 求解、至少两次通过
→ 独立高效求解 + 有限的删步／等价路径审计
→ 记录任务有效性、依赖证据和最短已知成功路线
→ 分层入池；有扩展价值的任务继续作为下一轮种子
```

**生成器负责增加真实工作，求解器始终负责减少无意义工作。** 不向求解 Agent 提供最低调用次数，不按轨迹长度增加 S3 reward。

第一版只主做两种扩展：

1. **前置条件扩展**：让 Agent 自己完成原来已经准备好的业务前置阶段。
2. **对象发现扩展**：把直接给出的内部 ID，替换为公开可唯一解析的业务描述。

关联业务结果扩展作为下一项；多分支、多对象资源优化、异常恢复、跨环境任务不是第一版的必选内容。

### 0.1 对上一版讨论的关键修订

| 上一版容易直接照做的地方 | 审查后的决定 |
|---|---|
| 给已有任务递归加步骤即可 | 先冻结意图，后执行；不能执行失败后缩小任务冒充成功 |
| 用最短已知路线判断扩展成功 | 必须同时保存探测预算、成功次数和依赖证据；不同探测预算下的最小值不能公平比较 |
| 把辅助查询从 Goal 去掉即可 | 还要处理结构去重；否则对象发现扩展可能与直接给 ID 的任务碰撞 |
| Agent 先探索，然后用该会话证明子任务可解 | 探索与子任务见证分开；见证执行者不能从父任务或探索记录中提前知道被隐藏的目标 ID |
| 删除某步后失败，说明该步必要 | 先排除参数泄漏、固定路径校验和没做重新规划等解释；最多形成局部依赖证据 |
| 简单规定长短比例 | 长度配额只作用于语料选择；达不到就报告不足，不放宽 Good Task 门槛 |
| 每轮采更长的继续扩展 | 只保留有业务增长、依赖增长和家族新颖性的有限前沿；长不是唯一排序依据 |
| 先扩到几十个新环境 | 先固定少量现有 Release 做因果归因；明确缺能力再反馈 S1 |

### 0.2 必须首先解决的三个落地障碍

**障碍一：验收规则会影响“看起来多难”。** 当前 Atom 按工具名和完整参数匹配，最终状态投影与答案按参考结果精确比较。若更短的合法路径被拒绝，长度审计会高估任务的有效工作量。[C04]

**障碍二：当前结构去重可能吞掉发现型扩展。** `_structure_id` 使用 Goal 结构、变化状态路径和答案 schema，不包含用户如何确定目标。去掉辅助查询后，“给定 ID 取消”与“先定位对象再取消”可能得到相同结构键。[C03]

**障碍三：实际采样入口没有自动选择新的初始场景。** `sample_task_draft` 支持 `reset_start`，但现有 campaign 调用未传该参数。设计中不能把“换到早期状态”当成已有自动能力。[C01][C06]

这三项必须进入代码改动和测试，而不只是写进 Prompt。

---

## 1. 范围、证据与不做的事情

### 1.1 本次审查已经检查的内容

检查了固定提交上的采样提示、`SamplingTarget`、TaskDraft、参数溯源、candidate materialization、Goal evaluator、TaskPack 准入、campaign 调度和相关实验报告。具体文件与论文见文末来源索引。

**没有**读取用户本机 `/home/kelong/pycodes/...` 下的未推送改动；**没有**打开或复跑仓库外的 20 个 Release、69 个 TaskPack 和 552 条原始 Episode。因此，对环境具体能力的判断是待实测假设，文中的维修／订阅案例是候选设计，不是已运行成功的新增任务。

基线以指定提交为准，不根据分支名里的 `s2`、`s3` 推断新旧。后续分支若已经改变对应模块，实施前应做差异审查，不直接覆盖。

### 1.2 保持不变的约束

- Acting Agent 只见 instruction、reset observation、公开 ToolSpecs 和自身 observation；看不到 protected state、参考答案、Goal 真值、父任务答案或验证内部信息。
- 真实代码与持久状态执行；所有见证、replay、独立求解都从各自 fresh 实例开始。
- 所有正式起点来自 Release 支持的 reset。没有 S2 隐藏 setup、原生写库或中间快照恢复。
- Host 冻结可追溯证据。LLM 可以提案和指出语义问题，不能自报“已成功”代替执行检查。
- 不生成每个任务专属的 Python Checker，不向 Framework 加维修／采购等业务分支。
- 保留五次有效 fresh 求解、至少两次通过的发布门槛；基础设施问题不充当模型失败。
- S3 继续使用冻结的任务真值和 `1 / 0 / null` 责任划分，不负责扩任务、改题或修改 reward 真值。
- 任务难度、长度分档、语料选择和训练器字段不混入任务的业务真值。

### 1.3 第一版明确不做

不训练任务生成器；不引入全局 Tool Graph；不做跨 Release 的多环境超级任务；不支持任意程序化参数表达式；不强制任意嵌套 `ForEach`；不证明全局最短解；不通过删掉合理批量接口制造难度；不为了修饰简历而预设模型提升数字。

允许在**单条真实轨迹内部**记录局部依赖证据。这是事后分析数据，不是用于编造工具链的全局 Tool Graph，也不进入求解 Agent 的输入。

---

## 2. 当前代码审查：具体改在哪里、为什么

以下为静态代码事实；右侧是设计决定，不是已实施内容。

| 编号 | 当前事实 | 对算法的影响 | 决定 |
|---|---|---|---|
| A01 | `SamplingTarget` 要求确定形状、非空 focus tools 和 outcome；采样提示要求 focus tool 属于 objective。[C01][C02] | 为覆盖查询接口，容易把取证步骤变成任务目标 | 新采样请求以业务意图为中心，工具与形状改为统计／偏好；不按出现次数强制 Goal |
| A02 | `_select_target` 对历史尝试的形状、工具、结果做计数，非按有效增长产率调度。[C06] | 未必优先找到有效复杂任务，且会持续触碰不支持的组合 | 先均匀试验，再按“有效扩展产率＋覆盖缺口”调度 |
| A03 | `sample_task_draft` 可以接收 reset 参数；现有 `_run_attempt` 未提供它。[C01][C06] | 不能假设递进采样会自动换早期起点 | 新增并验证 `StartRef`；仅使用合法 reset 输入或默认世界已有早期实体 |
| A04 | 重放整个采样轨迹；采样中的每次状态修改都必须在 DraftGoal 中，否则 `unexplained_sampling_mutation`。[C03] | 随意探索后再截取目标，会把试探性修改一起带入任务 | 分开 Scout 与 Witness；保持这条保护，不简单删除检查 |
| A05 | `_atom_matches` 按工具名与参数相等匹配；最终状态／答案精确匹配参考。[C04] | 不同查询、写路径、对象选择或生成 ID 可能造成假阴性 | 先用等价解测试限制支持范围；必要时补通用结果断言，不靠白名单补丁凑通过 |
| A06 | 参数来源主要通过公开叶子值相等或题目字面量匹配推导。[C03] | 不能直接支持任意算术派生；同值也不代表同语义实体 | 第一版只用可靠公开绑定；算术扩展显式标记不支持，后续再加有界表达式 |
| A07 | `AnswerProjection` 仅 source/object/array。[C02] | 计算、排序、聚合答案不是现有通用能力 | 第一版最小答案来自公开可读事实；不增加假装“预处理”的工具 |
| A08 | 结构键不包含目标解析方式，且 campaign 在 filter 之前按它拒绝重复。[C03][C06] | 对象发现扩展可能被粗去重直接淘汰 | 区分实例去重、任务语义签名与家族分组；旧结构键只保留为诊断特征 |
| A09 | 五次 filter 是独立会话，可复用同一策略路线；代码支持 driver factory。[C05] | 可复用执行基础设施，但不能叫五种独立模型 | 准入与复杂度探测使用分离的策略配置和记录 |
| A10 | `ForEach` 为同类原子 body；一个冻结 reset 的 `If` 只实际走一个分支。[C02][C04] | 不适合直接声称支持任意多步循环或两分支策略测试 | 先不扩这一层；条件反事实用多个独立验证的场景任务 |
| A11 | 旧报告与用户后续汇总的均值、P95 等部分数值并不完全相同。[C08] | 很容易用错统计口径或混用批次 | P0 对固定原始产物重算；本文只把已知“中位数为 2”作为动机，不以其他未统一数值设结论 |

### 2.1 不能只改采样 Prompt

仅写“至少使用八个工具”不会处理 A04、A05、A08。一个看起来成功的改动，可能只是在强迫 Agent 绕路、把辅助查询写进 Goal，或者让重复目标带着不同文本进入语料。

最低限度需要同时修改：**请求语义、意图冻结、候选生成、去重和复杂度审计**。原有执行、回读、失败归因与准入逻辑尽量复用。

---

## 3. 目标与评估口径

### 3.1 优化对象是任务，而不是一条轨迹

用以下元组理解一个任务实例：

```text
T = (release_id, reset_config, instruction, frozen_goal, answer_contract, verifier_version)
```

父子任务可以有不同 instruction 或不同合法 reset，因此是不同任务实例。父任务的通过证据不能继承为子任务的通过证据。

任务有效性记为 `V(T)`；有效性只取决于任务语义与验证证据，不依赖长度档位。

复杂度记录为向量，而不是一个越大越好的分数：

```text
C(T) = {
    shortest_known_calls,
    probe_budget,
    successful_probe_count,
    witnessed_dependency_depth,
    dependency_evidence_levels,
    meaningful_stage_count,
    branch_or_selection_requirements,
    policy_specific_success_rate,
    solve_cost
}
```

“有意义阶段数”属于经过证据审查的分析项，不是自动证明的数学事实。它不能单独触发发布或提高 reward。

### 3.2 两种最短已知路线必须分开

**全历史最短已知路线 `L_best_all`**：对所有已经审计有效的成功路线取工具调用数的最小值。用于生产分档，可以随新证据变短。

**固定协议最短已知路线 `L_best_probe`**：只在预先冻结的标准探测协议下取最小值。用于比较父子任务、轮次和算法。

设真实最短公开解长度为 `L*`，则：

```text
L* ≤ L_best_all
```

因此，不能写“已证明至少需要八次调用”。只能写“固定探测协议下，最短已知成功路线为八次”。

**比较要求：** 父子使用相同策略、工具预算、token 预算和有效探测次数；报告各自成功次数。父任务被尝试了三十次、子任务只尝试两次时，不得据此直接判断子任务更长。

新找到正确短路线必须进入 `L_best_all`。语料的长度分档可以版本化更新，但 Task 本身不因此变无效。

### 3.3 什么计入工具调用

计数单位为 Host 实际分派给公开环境的单次工具调用，包括合法业务拒绝调用。另记 `invalid_call_attempts`，不要把未分派的无效 JSON 当成真实工具工作量。

不计入：Host 的 reset、protected read、重开、evaluator、自身文件读写和其他 Episode 的调用。同一模型响应内若包含多个已分派调用，分别计数；provider turns 单独统计。

同时报告成功路线中的错误尝试、相同读请求重复、重复写入等诊断量。不要直接“扣掉所有失败调用”：合法业务拒绝和恢复有时正是任务要求。

### 3.4 第一版的目标区间

优先补齐 **5–8 次**与少量 **9–15 次**最短已知成功路线的任务，同时保留基础任务。区间是试验用分档，不是模型必须遵守的调用下限，也不是普适难度定义。

先看现有环境自然能支持什么，不承诺固定 25%/50%/25% 配额。对每个环境分别报告分布，避免少数长流程环境掩盖其他环境依旧只有短任务。

---

## 4. 最小可实现范围与 verifier 前置门槛

这部分用于避免两个极端：一边完全不修验证就制造“假长任务”，另一边先重建万能 evaluator 导致算法永远无法试验。

### 4.1 第一版先选择可被可靠表达的任务子集

优先选择：固定业务对象或公开条件能唯一确定对象、现有 reset 中存在合法早期状态、明确的多阶段状态转移、答案可以从公开结果读取的任务。

非平凡性单独检查：初始状态已经满足全部修改目标的候选不得靠追加无关查询变成新任务；查询答案已经完整包含在 instruction/reset 时，不强制一次工具调用来制造非平凡。正确拒绝可以不改变状态，但应存在真实的规则判断或信息获取要求。

暂不发布为本轮复杂任务成果：

- 任意选择一个合法对象，但当前 evaluator 只接受参考选择的任务。
- 非唯一写路径会生成不同合法 ID，而当前规则仍冻结参考 ID 的任务。
- 必须有中途过程证据，但当前状态／事件证据无法正确表达的任务。
- 依赖算术、优化目标或任意派生参数，而当前溯源不支持的任务。
- 更短合法路线已被发现，却仍遭当前 evaluator 拒绝的任务。

这些可以作为 `RepresentationBlocked` 或 `VerifierDisputed` 候选保留，不计入发布数，也不作为模型失败训练样本。

### 4.2 P0-A：无需万能新 DSL 的最小修复

1. 将取证调用与业务要求区分。普通发现型 read 不因为被采样器执行，就成为强制 Atom。
2. 保留所有真实副作用的核对。去掉 read Atom 不等于允许任意隐藏修改。
3. 对同一目标准备 `list → mutate` 与 `inspect → mutate` 等合法正例；只要指向相同事实和目标，应通过。
4. 同时测试错误对象、错误值、缺失最终操作、附带无关修改等反例，防止“修假阴性”变成放宽所有比较。
5. 纯查询任务需有路径无关的答案／事实断言；若目前只能通过固定 read Atom 验收，不把它作为对象发现扩展的生产种子。

**不能仅删掉 `_atom_matches` 或关闭 after-state 检查。** 如果现有 Goal 无法表达修复后的含义，进入 P0-B，而不是偷偷改宽松判分。

### 4.3 P0-B：被实际案例要求时，增加最小结果断言

这是有边界的通用 kernel 扩展，不是为每个环境生成 Checker。外层仍可用 Atom / All / If / ForEach；新增 Atom 的结果语义，不把任意工具调用直接当成目标。

建议最小结果断言只有：

| 通用断言 | 用途 | 约束 |
|---|---|---|
| `EntityFieldEquals` | 指定实体达到要求状态／关系 | selector 必须明确且实体唯一；expected 来自公开要求或经过语义对齐的真实证据 |
| `UniqueEntityExists` | 新建的业务对象确实存在且归属正确 | 按稳定业务键与关系定位，不固定参考执行偶然生成的 ID |
| `AnswerMatchesFact` | 答案与已验证实体事实一致 | 不接受虚构值；事实须对 Agent 公开可读取 |
| `UnrelatedStateUnchanged` | 防止修改无关实体 | 作用域与允许副作用必须事先有规则依据，不能从参考 diff 自动放宽 |

写动作、查询路线仍然可以不同。需要强制审批、尝试某类业务请求等过程要求时，使用有明确公开语义的事件／持久历史检查；不能把工具名匹配当成所有过程要求的通用替代品。

**第一版不要求处理任意多解或任意历史时序。** 但一旦 instruction 允许它们，不能按参考结果唯一匹配；要么正确支持，要么明确拒绝该候选。不能悄悄把题目改成“必须选参考对象”。

### 4.4 结果断言如何绑定到真实状态

Sampling Agent 只提交公开实体锚点、要求字段和对应的公开 observation 引用。Host 解析 protected state schema 与真实状态，形成受保护的 `StateBinding`。

绑定必须同时具有：实体种类／作用域、身份键、字段路径、公开来源和唯一性检查。**不能因为某个标量值在两个地方都等于 `1`，或两个对象都存在 `status`，就认定语义一致。**

无法机械消除歧义时返回 `BindingAmbiguous`。必要时由 S1 补充任务无关的实体身份／字段映射元数据并重新 Qualification；这不是给任务生成 Checker，也不能在 S2 临时编辑已有 Release。

参考 before/after 全量快照仍保留用于审计。它们不自动定义“所有未来合法结果必须等于参考快照”。

**条件时点必须显式区分：** 技术员在分派前应当可用，分派后变成占用是正确结果；库存可用量也会因预留而下降。不能把前置条件误写成终态条件。绑定应标明 `initial / before_required_action / final` 等受支持时点。无法从原生规则、可靠历史或 Host 采集证据检查中间条件时，不能伪装成终态断言；先限制该任务类型或补足通用事件证据采集。

**允许副作用范围必须独立审查：** 比如派工可以影响请求、技术员占用和对应历史，但不能仅因为参考执行意外改了另一个租客，就把该租客也加进允许范围。暂时改坏无关状态再恢复是否违规，必须根据公开任务／环境规则决定；若属于过程中禁止事项，就需要逐步状态或可靠原生历史，单看终态不足。

### 4.5 版本与公平比较

修改验收语义时冻结新的 evaluator 版本和必要的新 artifact format，重新 replay、重新准入。旧包原地不改；旧报告不重贴标签。

原格式基线保留在独立旧 checkout／旧产物目录。新生产路径不加入隐式兼容 fallback。实验的各个算法组使用**相同的新冻结 verifier**，避免把修 verifier 的收益误算成采样算法收益。

P0-A 足以覆盖的任务可以先做小规模机制试验；存在已知验收争议的任务不得进入正式长任务语料。P0-B 的范围由真实阻塞案例决定，不预先实现完整业务逻辑语言。

## 5. 核心算法：意图约束的有限递进搜索

算法工作名：**Intent-Grounded Task Evolution**。这是本文对方案的命名，不是已发表算法名称，也不表示递归扩展本身是原创。

### 5.1 三个池，而不是一个“成功池”

```text
CandidateArchive：所有提案、失败、争议与证据，完整保留。
ValidTaskPool：通过语义／执行／准入要求的 TaskPack，与长度无关。
EvolutionFrontier：从 ValidTaskPool 中选出仍有扩展价值的有限种子集。
```

语料集由单独的 CorpusPolicy 从 ValidTaskPool 选择。一个合法短任务不应因为没达到长度配额被标成“坏任务”；它可以不进入本轮中长程训练子集。

### 5.2 角色与信息边界

| 角色 | 可见 | 不可见 | 产物 |
|---|---|---|---|
| Proposer / Scout | Need 的公开业务部分、ToolSpecs、父任务公开意图、自己通过公开工具获得的事实 | protected state、父任务答案、Goal 内部数据、独立求解答案 | 扩展提案、公开可行性线索 |
| Witness Executor | **仅子任务冻结 instruction、reset observation、ToolSpecs、自身 observation** | 父任务 instruction、探索历史、父任务目标 ID、预期路线、答案 | 子任务真实成功或失败执行 |
| Draft Extractor | 冻结意图与上述见证的公开 trace | protected state | 公开来源引用、候选目标证据与答案投影 |
| Host | 真实状态、schemas、公开执行证据、已冻结意图 | 不向 Acting Agent 泄露受保护部分 | bindings、Goal、replay、判定 |
| Admission Solver | 正常 PublicTaskView 与自己的环境交互 | 提案、父任务、见证、答案、Goal | 五次独立会话证据 |
| Efficient Solver | 与 Admission Solver 相同的公开信息，另有“在满足要求下高效完成”的固定策略提示 | 参考长度、长度目标、父任务、Goal、答案 | 有限预算的短路线搜索 |
| Semantic Reviewer | instruction、公开约束与证据、断言的语义说明 | 不把私有答案补给任何求解者 | 不一致／歧义线索，不计算 reward |

Proposer 可以复用父任务的公开目标理解业务，但不能把“父任务里恰好知道的 ID”带进子任务见证者上下文。已有 `prior_accepted_summaries` 不应直接注入 Witness Executor。

Scout 在可丢弃的独立实例中探索，可以执行公开动作，但其变更绝不成为子任务初始状态。若它发现合法起点，需记录正式 reset 配置或默认世界中的公开发现条件，由新实例重新构建。

### 5.3 候选意图先冻结

建议新增 `IntentSpec`，包含：

```text
instruction_exact           公开题目原文，执行前冻结
public_target_descriptions  对象与范围的公开描述
required_outcomes           必须达成的业务结果
constraints                 禁止项、筛选条件、明确的过程要求
answer_fields               用户要求返回的最小字段及类型意图
start_ref                   固定 Release 内合法 reset 的引用
```

它**不包含**参考答案、需要猜测的内部 ID、工具调用序列、预期调用次数、protected state 路径。

另存仅用于采样分析的 `EvolutionDelta`：父任务、扩展算子、保留的用户需求、增加／替换的部分、业务理由、预计新增依赖。它不进入 Witness / Admission / S3 Prompt。

前置条件扩展可能换了合法起点，对象发现扩展可能替换了目标描述，因此不强行要求数学意义上“子任务包含父任务所有字面条件”。必须记录哪些保持、哪些改变，并说明仍然是在扩展同类用户目标。

**修改规则：** 执行后若发现题目缺字段或不可解，可以创建新 revision，但新 instruction、新 intent ID、新执行、新 replay、新五次准入，全部重新开始。仅 JSON 编码／投影语法纠正可在不改变冻结语义的条件下修复；不得让纠正答案格式成为增加隐藏要求的渠道。

### 5.4 一轮搜索

1. 按家族和环境配额，从前沿选择有限种子。
2. 为每个种子选择一个可行扩展算子；默认提出两个不同候选，而不是无限采样。
3. 先做便宜检查：业务理由、公开可发现性、现有表达范围、重复风险、合法起点。
4. 冻结 IntentSpec，运行新的 Witness Executor。
5. 未完成整个冻结目标则记录失败。不能将成功的前半段改写成一个简单子任务计为增长。
6. 完成后提取公开证据，由 Host 构造 Goal 和最小答案，并走完整 fresh replay。
7. 对 candidate 做语义对齐与新去重，再运行原五次 fresh 准入。
8. 对已准入任务做高效求解与有限依赖审计；争议任务隔离。
9. 有效任务进入 ValidTaskPool。根据新颖性、依赖增长、可验证长度档位和成本选择下一轮前沿。
10. 所有结果进入归因与统计，下一轮再统一更新调度权重。

**有效性不增长仍可有价值：** 一个子任务真实增加了条件判断，但调用次数未变，可作为“决策型增量任务”保留，不算“长度增长成功”。别为了单一长度指标删除它。

### 5.5 主流程伪代码

以下是控制流规格，不是可直接导入的现成实现；名称在第 12 节映射到现有模块。

```python
for round_index in range(config.max_rounds):
    schedule = scheduler.freeze_round(frontier, prior_round_records)
    round_records = []

    for job in execute_schedule(schedule):
        proposal = propose_extension(job.public_seed, job.operator, job.start_options)
        if not proposal.has_supported_public_intent:
            round_records.append(record_terminal(job, "ProposalRejected"))
            continue

        intent = freeze_intent(proposal)  # 先确定完整用户要求
        witness = run_fresh_public_solver(intent, role="witness")
        if witness.infrastructure_defect:
            round_records.append(record_terminal(job, "InfrastructureFailure"))
            continue
        if not witness.has_valid_terminal:  # 仅表示正常终止，尚非成功真值
            round_records.append(record_terminal(job, "WitnessUnsolved"))
            continue

        draft = extract_draft(intent, witness.public_trace)
        candidate = host_materialize_and_replay(intent, draft, witness)
        if not candidate.valid:
            round_records.append(record_failure(job, candidate))
            continue

        alignment = audit_intent_alignment(intent, candidate)
        if not alignment.acceptable:
            round_records.append(record_failure(job, alignment))
            continue

        fingerprint = make_task_fingerprint(intent, candidate)
        if exact_or_semantic_duplicate(fingerprint):
            round_records.append(record_terminal(job, "DuplicateTask"))
            continue

        admission = run_five_fresh_admission_trials(candidate)
        if admission.has_untrusted_trial:
            round_records.append(record_terminal(job, "InfrastructureOrTruthDefect"))
            continue
        if admission.pass_count < 2:
            round_records.append(record_terminal(job, "PolicyRejected"))
            continue

        probes = run_fixed_complexity_protocol(candidate)
        dependency = audit_local_dependencies(candidate, witness, probes)
        if probes.verifier_dispute or dependency.truth_dispute:
            round_records.append(record_terminal(job, "VerifierDisputed"))
            continue

        task_pack = seal_new_task_pack(candidate, admission)
        assessment = write_separate_assessment(task_pack, probes, dependency)
        valid_pool.add(task_pack)
        round_records.append(record_admitted(job, task_pack, assessment))

    persist_round_in_logical_order(round_records)
    frontier = select_next_frontier(valid_pool, round_records, config)
```

代码必须保留每个阶段的真实 typed failure，不把上述伪代码中的简写变成一个笼统的 `except: continue`。

见证模型未完成，不证明任务不存在解；该结果叫 `WitnessUnsolved`，而不是未经证据确认的 `EnvironmentUnsupported`。

---

## 6. 扩展算子的精确定义

### 6.1 O1：前置条件扩展（第一优先级）

**目的：** 将原来在起点已满足的业务前置条件，转成需要 Agent 通过合法公开动作建立的条件。

例子：

```text
父任务：为一个已经分派技术员的维修请求安排上门。
子任务：为一个尚未分派的对应请求，完成合格技术员选择、分派与上门安排。
```

算法步骤：

1. 识别父任务最终业务动作依赖的状态，例如“已分派”。只把它当成待确认前置条件，不因为工具描述里出现相关词就认为成立。
2. 通过公开信息确定可建立该状态的业务动作与对象关系。
3. 从现有默认世界选择尚未达到该状态的对应实体，或选择 Release 已支持的 reset 配置。
4. 冻结新的目标和起点。不得在隐藏步骤中“撤销分派”构造更早状态。
5. 在新实例真实完成所有阶段，并检查目标结果与副作用。
6. 检查能否合法绕过新增阶段。如果可以，它可能不是必要的状态依赖；仍可保留有效任务，但不能按这条依赖申报增长。

**准入证据：** 合法起点、公开前置条件来源、新增操作产生的真实业务状态、后续操作消费该状态的证据、完整任务 replay 与准入结果。

**常见失败：** 早期状态不存在；Builder 未实现建立条件的操作；所谓前置条件没有被环境执行语义约束；新增阶段只是“查看一下”的仪式性步骤。

**停止条件：** 当前环境已经到达有意义的业务起点，不再反复添加“先取消再重建”“先弄坏再修复”等人为阶段。

### 6.2 O2：对象发现扩展（与 O1 同期实施）

**目的：** 让目标通过公开关系与条件确定，而非由 instruction 直接提供内部 ID。

例子：

```text
父任务：取消订阅 S-103。
子任务：取消给定客户账户下唯一仍有效、且满足明确公开条件的订阅。
```

算法步骤：

1. 从父目标中选择一个内部对象标识作为候选替换位置。
2. Scout 通过公开接口寻找上游关系，例如客户→账户→订阅。
3. 构造足以解析目标的业务描述，不把原 ID、特有答案字符串或参考工具链藏在附加说明里。
4. 验证候选集完整性与唯一性。分页未读完、范围未限定、只看到一个候选，不等于唯一。
5. 子任务见证者使用全新会话，仅见新 instruction，重新获取参数。
6. 去掉与新用户要求无关的参考 read Atom；保留可核对的对象事实与真正结果条件。
7. 测量独立求解是否确实需要额外信息获取，而不是只是文本变长。

**第一版限制：** 只做由公开条件唯一确定的目标。多个合法目标的任务需要正确的多解验收，不把“选了第一个”冻结成未公开规则。

**必要测试：** 相同最终目标和相同 state diff 下，直接 ID 任务与关系发现任务不应被旧结构键硬合并；但仅将 `S-103` 换成另一 ID、调用需求不变的实例应归入同一任务家族。

**不要强迫读取：** 若一个合理查询直接返回最终目标，接受更短路线。新增“必须查询三张表”的文字通常是在指定过程，而不是制造真实发现需求。

### 6.3 O3：关联业务结果扩展（下一阶段）

**目的：** 从局部操作扩展到同一用户需求的完整结果。

```text
父：取消订阅。
子：取消订阅，并依照公开规则完成允许的退款处理。
```

新增结果必须与原目标有关，并在 Need 与工具实际能力之内。不能把“取消订阅＋统计无关客户”包装成一个任务。

条件结果的范围须明确。固定场景只能证明被执行分支；没有执行过的 else 分支不能被声称为构造性验证完毕。需要两种行为时，为两个合法 reset 场景分别执行和发布，再将其作为同一家族的场景对评估。

### 6.4 什么时候允许任务起点变化

允许三种来源：

- 默认世界已经存在的更早阶段实体，公开信息可以找到。
- 同一 Release 的正式 start schema 允许的 reset 配置。
- 经 S1 修改并重新 Qualification 的新 Release。

不允许：调用父任务执行后的快照、借用 Scout 状态、原生插入记录、让 Witness 看不到前置 setup。

`reset_config` 可以包含环境种子或场景配置，但必要的决策信息仍必须通过 reset observation／工具公开。不能让 Agent 必须知道 Host 传入的某个隐藏场景标签。

### 6.5 一个完整的示意任务家族

以下为待真实验证的候选，不预设工具数：

| 层次 | 用户需求 | 新增能力 |
|---|---|---|
| T0 | 给已分派的指定请求安排上门 | 基础状态操作 |
| T1 | 为未分派的指定请求选择符合公开条件的技术员并安排上门 | 状态准备与选择 |
| T2 | 根据住户、房产和维修描述定位请求，再完成 T1 的业务结果 | 关系发现 |
| T3 | 若环境支持，从新的有效维修需求建立请求，再完成安排 | 更早业务起点与新增对象 |

T3 的新建对象可能暴露当前生成 ID／结果绑定的局限。若无法正确处理替代合法执行的 ID，先停留在 T2，不为了继续增长而将隐藏 ID 写进题目。

任务终点是“安排处理”，不是要求 Agent 假装现实中的漏水已被修好。模型只能对环境实际支持、且用户授权的业务记录采取行动。

---

## 7. 高效求解与依赖审计：如何排除假长度

### 7.1 高效求解者不是对抗验证器的作弊者

固定策略提示可以是：

> 使用正常公开工具完成全部用户要求。在不遗漏条件、不猜测隐藏信息、不产生未授权副作用的前提下，选择尽可能直接的方案。合理的批量查询或批量操作可以使用。最终答案只包含要求字段。

它看不到目标长度、参考步骤数、父任务、Goal 或正确答案。不能给它一个“正确目标 ID”再要求它删步骤，这样会把本应需要发现的工作消除。

第一版每个 candidate 追加两次高效求解，预算固定。两次都失败时，只记录未找到新路线，不说明任务“不可压缩”。任何基础设施故障单独记账。

### 7.2 比较父子时固定探测协议

建议协议 `complexity-probe/1`：五次标准公开策略尝试，加两次高效策略尝试。每次预算相同且在实验前冻结；保存模型、driver、system prompt、工具预算与 token 限制。

生产筛选阶段可以复用满足该协议的 admission 五次，节省成本，但必须标记 `reused_admission_evidence=true`。这种证据经过“至少两次通过”的选择，不能当作无偏的难度估计。

**正式算法比较另跑冻结后、未参与筛选的探测批次。** 它才用于报告难度变化。不要在同一批测试上选任务后，再把其成功率当成独立结果。

`L_best_all` 包含有效见证、准入与所有后续发现的成功短路线；`L_best_probe` 仅包含当前固定探测协议的路线。两个字段不能混用。

### 7.3 依赖证据分三级

| 级别 | 含义 | 允许的表述 |
|---|---|---|
| E0：候选依赖 | 工具描述、字段关系或模型分析认为可能依赖 | “待验证依赖” |
| E1：公开数据／状态见证 | 后一步实际消费此前公开结果，或使用前一步建立的状态 | “见证路线中存在依赖” |
| E2：局部干预支持 | 有效删步／替换／独立重规划试验支持该依赖，在已测试方案中不能省略 | “经局部审计支持的依赖” |

E2 仍不是全局必要性证明。报告依赖深度时写明级别与计算方法，不将 E0 的边混入“已验证深度”。

不能把相同布尔值、同样的 `status` 字段或偶然相等的数字自动认作依赖；必须有实体身份、字段含义、时点和真实消费关系。

若已有逻辑链 `A→B→C`，不要因为 A 的某个值也出现在 C 的输出中，就随意添加更多边提高密度。依赖深度和边数都不是优化 reward。

### 7.4 删步审计必须区分两种实验

**实验一：固定见证的删步重放。** 它回答“这条具体见证能不能少一步”，不是“这个任务有没有另一条短解”。

- 删除某步后，后续参数必须重新依据保留的公开来源绑定。
- 被删步骤唯一提供的 ID 不允许从原日志偷偷填回。
- 无法重新绑定时，记 `DependencyUnresolved`，不等同于任务不存在短解。
- 因 exact tool-event 匹配失败，但结果正确时，记 verifier 争议，不当作依赖证据。
- 不建议对每个任务穷举所有删除组合。第一版最多审计三个看起来最关键或最可疑的操作。

**实验二：独立重规划。** 让新 Agent 只见原题，尝试更直接路线。它用于发现查询替代、批量操作、可并行的独立步骤等。

两种结果分开保存。固定重放没有通过，不得自动写成“步骤必不可少”。

### 7.5 正反例审计

正例候选：等价发现查询、无关独立动作的合法顺序变化、合法批量操作、不同但符合公开条件的合法结果。

反例候选：错误对象、漏掉子结果、错误分支、越权范围、附带无关修改、答案与状态不一致、伪造检查结果。

正反例可以由通用轨迹变换和独立求解生成，但必须在真实环境执行。不能把修改了 observation JSON 的伪轨迹当成真实运行；伪造 JSON 只用于纯 verifier 单元测试，单独标注。

语义上“应该通过／不通过”的判定需要公开要求与独立审查支持，不由生成该变体的 LLM 自己宣布。第一批小规模候选建议逐题审查这些配对案例；之后再扩大自动化。

### 7.6 分支、集合和资源约束不靠形状计数

一个固定 reset 下只执行 then，不代表训练了跨场景条件判断。要验证这种能力，需要合法场景对，并在两种场景分别证明可解。

`ForEach` 的成员集必须完整，分页和范围要明确；重复执行 N 次不等于依赖深度为 N。多个独立对象的宽度与因果链深度分别统计。

多个任务共享预算／库存时，整体计划可能有价值，但第一版不做无法确定性验收的最优解选择。公开条件不完整或多个最优解无法处理时，应归因到表达能力，不拼接更多工具补偿。

## 8. 去重、家族与测试隔离

### 8.1 三种身份，不能用一个 hash 解决

**任务实例身份**：绑定具体 Release、reset、instruction、Goal 和答案契约。参考证据如何进入既有 TaskPack ID 继续遵循其格式，不把难度评分、worker 数或后续 probe 结果塞进业务真值。

**任务语义签名**：用于区分实际要求是否相同。建议从冻结意图及已核验的公开绑定生成规范化数据：

```text
目标实体角色与作用域
目标定位方式：literal_id / public_selector / relation_lookup
公开筛选谓词与必要关系
要求的业务结果与禁止项
起点的业务状态类别
明确要求的过程语义
答案要求的语义字段
```

普通 list 与 inspect 是可替代证据路线，不能因为工具名字不同就成为不同语义签名。不要简单 hash 整段自然语言；那只会把改写当成新任务。

**任务家族身份**：根任务谱系，加上规范化后的业务流程／公共选择模式。具体对象 ID 替换、同义改写通常仍属同一家族。

### 8.2 旧结构键怎么处理

保留 `task-structure/3` 作为粗粒度特征和历史对照，不再把“结构键相等”单独作为对象发现扩展的硬拒绝条件。

具体规则：

1. 相同实例身份：硬去重。
2. 相同 reset、相同已核验语义签名：作为重复或等价版本合并／择优，不重复宣称为新任务。
3. 仅粗结构键相同，但一个直接给 ID、另一个要求关系发现：保留为不同任务，归到相关家族。
4. 签名解析存在歧义：进入重复待审队列；不要靠“更长的一定保留”裁决。
5. 两条成功路线属于同一个任务：记录为路线多样性，不计作新任务数量。

如果任务签名使用局部依赖特征，只使用对公开用户需求的语义抽象；不把完整参考动作顺序编码进去。参考路线变化不应把同一个任务变成两个家族。

### 8.3 训练／开发／测试先按根家族分配

在递归前分配根任务家族的 split。所有后代、参数变体、题目改写和配对 reset 场景继承同一 split。

训练端 Scout、历史摘要、调度反馈不能看到测试任务或测试求解结果。同环境内留出的家族测试与整环境留出测试分开报告。

仅按祖先隔离还不够：两个独立根可能是同一个模板。需要跨根比较语义签名，并把疑似相同业务模板合并到一个隔离组。不能认为“没有同一个 parent_id”就没有泄漏。

测试集合一旦用于指导下一轮生成，就成为开发集；最终测试需要另行冻结。

---

## 9. 前沿选择与预算调度

### 9.1 第一版不训练调度器

先使用可解释的计数策略，避免把一个尚未证明有效的采样算法进一步包装成 RL 系统。

**冷启动：** 每个可用的 `(Release, operator)` 分配相同数量的小预算尝试，记录实际可行性。

**之后：** 保留 20% 均匀探索，其余按覆盖缺口、有效增长产率和成本选择。这是试验初值，可在 dev 数据调整，不是论文结论。

可使用以下简单权重：

```text
p_growth(cell) = (1 + 有效且有新增能力的候选数) / (2 + 已完成语义尝试数)
weight(cell) = p_growth(cell) × coverage_deficit(cell) / max(cost_ema(cell), cost_floor)
```

- `coverage_deficit` 有正下限，避免完全饿死一个环境；同时设环境与家族最大份额。
- Provider 故障计入真实成本，但不当作“该业务扩展不可行”的语义失败。
- `cost_ema` 的计量单位在同一实验中固定，可用 provider tokens；若使用货币成本须绑定当次价格配置，不能猜测计费。
- 不把原始轨迹长度直接乘进权重。特别长但结构单一、冗余多的任务不应垄断预算。

### 9.2 “增长成功”的定义

至少满足：任务有效、保留连贯用户意图、不是语义重复、确有新增决策／信息／业务阶段要求。

再分别标记：

```text
capability_growth：新增可核验的能力要求。
length_growth：固定探测协议下观察到更长的高效完成路线。
dependency_growth：新增 E1/E2 支持的有效依赖。
```

三者不是同一个布尔值。比如约束判断变复杂而工具数不变，是 capability_growth，但不是 length_growth。

父子起点／对象同时变化时，长度差还可能来自实例差异。记录变化项，优先用匹配场景对比较，不轻率把所有差异归因于算子。

### 9.3 有限前沿与停止条件

建议试验初值：最多三轮；每个父任务每轮最多两个候选；每个根家族下一轮最多保留一个后代。必要时保留一个未扩展根作为重新探索起点，但仍消耗显式预算。

前沿选择采用分层顺序：

```text
有效性通过
→ 满足家族与环境上限
→ 覆盖缺口与新颖性
→ E1/E2 依赖增长
→ 目标长度档位覆盖
→ 成本
```

不采用“调用越多分越高”的单一排序。

出现下列情况停止该扩展方向：连续少量尝试没有新增能力；达到长度档位后继续扩展只是重复；缺少合法起点；表达能力阻塞；相同家族占比过大；预算耗尽。

停止并不撤销已有有效任务。失败记录可以反馈到 S1／表示层，但不能成为降低验证门槛的理由。

### 9.4 并发与恢复

按轮冻结 job 清单，以逻辑 job ID 排序持久化结果。下一轮只消费上一轮完整终态记录，不按“哪个 worker 先完成”动态改变同一轮的采样目标。

这能避免并发调度速度改变算法决策。由于模型采样不一定完全可复现，不承诺相同 seed 必然产生逐字相同的新任务；必须用真实配置、模型、提示、响应与产物身份标识实验。

重复启动不能覆盖历史失败。恢复读取已有 terminal records，跳过已完成逻辑 job；基础设施重试保留 attempt 子记录和原因。

---

## 10. 数据契约与产物

以下为建议新增的设计契约，不是当前代码已经支持的格式。正式实现时冻结版本并做严格 reader 校验。

### 10.1 `EvolutionTarget`

| 字段 | 含义 |
|---|---|
| `release_id` | 固定不可变环境 |
| `parent_task_id` / `root_family_id` | 父任务与根家族；新意图种子可以没有 parent |
| `operator` | prerequisite / discovery / outcome_extension |
| `round_index` / `job_id` | 有界递归与恢复身份 |
| `coverage_request` | 能力／长度档位的采样偏好，不是求解约束 |
| `allowed_start_refs` | 仅限已验证合法的起点引用 |
| `budget_profile_id` | 见证、准入、探测与审计预算 |
| `split_group_id` | 整个谱系继承的数据分区 |

禁止字段：`required_tool_call_count`、隐藏答案、参考 action sequence、任意 Python setup。

### 10.2 `IntentSpec` 与 `IntentBinding`

`IntentSpec` 是公开用户要求的冻结版本。`IntentBinding` 是 Host 根据公开证据解析目标的受保护结果，包含：

```text
clause_id
public_description / public_source_refs
resolved_entity_identity
uniqueness_evidence
bound_goal_predicate_ids
required_answer_field_ids
```

每个 Goal 要求至少对应一个公开 clause 或公开环境规则；每个 clause 都要有对应的验收处理。无法覆盖的 clause 不允许留在题目里但不检查。

不能让 Host 通过 protected state 决定 Acting Agent 该选谁，再把这个选择当成题目已经公开。protected state 用于核验，不提供行动参数。

### 10.3 `EvolutionRecord`

保存提案、冻结意图、语义修订关系、见证引用、replay 引用、准入引用、最终 terminal 和责任归因。每一阶段记录时间与成本；所有候选都有终态。

`parent_id` 和 `root_family_id` 服务于采样与数据隔离；不把“这是第三轮”“此题应更难”放进 PublicTaskView。

### 10.4 `ComplexityAssessment`

建议字段：

```json
{
  "format": "task-complexity-assessment/1",
  "task_pack_id": "<digest>",
  "verifier_version": "<frozen-version>",
  "probe_protocol_id": "<digest>",
  "probe_attempts": 7,
  "valid_probe_attempts": 7,
  "successful_probe_attempts": 4,
  "reused_admission_evidence": true,
  "l_best_probe": 6,
  "l_best_all": 5,
  "witness_dependency_depth": 3,
  "dependency_evidence_counts": {"E0": 0, "E1": 2, "E2": 1},
  "length_bucket": "5-8",
  "status": "assessed",
  "route_ids": ["<digest>"],
  "audit_ids": ["<digest>"]
}
```

上述数字只是格式例子，不是真实结果。`l_best_*` 没有成功证据时必须为 null，不能用 max budget 或无穷大代替。

`witness_dependency_depth` 的计算规则需固定：在经审查的 E1/E2 有向无环局部关系中，最长依赖链的节点数；它不是所有可能解的下界。并列子任务分别计宽度。

### 10.5 `CapabilityGapRecord`

```text
Release / reset / intent
尝试完成的具体业务目标
已观察的公开事实和动作结果
阻塞分类
最小可复现的公开反例或缺失证据
建议责任层：S1 Need / S1 actor / S2 representation / S2 search / verifier
```

分类至少包括：

| 终态／问题 | 含义 |
|---|---|
| `WitnessUnsolved` | 当前执行者未找到解，不证明环境无解 |
| `StartUnsupported` | 指定起点不被该 Release 正式支持 |
| `RepresentationBlocked` | 可执行意图暂不能用当前 Goal／来源机制表示 |
| `IntentDrift` | 产物不再对应冻结的完整用户要求 |
| `BindingAmbiguous` | 公开目标或 protected 对应关系未唯一确定 |
| `VerifierDisputed` | 发现可信的语义与判定冲突，待修复复验 |
| `NoObservedGrowth` | 任务有效但没有观察到本轮要求的增长 |
| `DuplicateTask` | 等价任务重复，不是模型失败 |
| `InfrastructureFailure` | 执行／提供方基础设施不可信 |
| `PolicyRejected` | 获得五次可信准入结果，但少于两次通过 |

S2 候选失败不是 S3 reward。不要把这张表的所有失败都转成负训练样本。

### 10.6 目录布局

```text
campaign/
  config.json
  input_manifest.json
  evaluator_manifest.json
  rounds/
    round-000/
      schedule.json
      jobs/<job_id>/
        proposal.json
        intent.json
        witness.public.json
        materialization.trusted.json
        admission.trusted.json
        complexity.trusted.json
        terminal.json
  taskpacks/<task_pack_id>/...
  assessments/<assessment_id>.json
  lineage.json
  split-manifest.json
  corpus-manifest.json
  report.json
```

`trusted` 不仅依赖文件名隔离：构造 PublicTaskView 时必须显式 allowlist 字段，并对嵌套结构做泄漏测试。SFT 输出只能由 S3/S4 的正式公开视图生成，不能直接导出此目录的所有 JSON。

---

## 11. S1 反馈闭环：何时改环境

先在同一批固定 Release 上诊断。不要让每次扩展失败都触发环境改写，否则无法判断改善来自采样器还是环境变了。

| 观察结果 | 归因原则 | 下一步 |
|---|---|---|
| 人工提出的完整目标能通过公开工具完成，原采样器从不提出 | S2 目标选择可能不足 | 改意图采样与前沿选择 |
| 有合法完整路线，但始终从接近终点的实体开始 | 初始状态使用偏差 | 优先使用既有早期实体，再考虑正式 reset 场景 |
| 前置条件在 Need 中明确存在，但 actor 可绕过 | 环境语义缺陷 | 形成公开反例，S1 修复并重新发布 |
| 完整需求所需业务能力根本未列入 Need | Need 范围限制 | 决定是否值得扩展业务范围，不指责代码生成器 |
| 工具能做，但 ID／计算／历史约束无法表示 | S2 表示边界 | 增加有界公共表示，不创建每题专用工具 |
| 换路径即因数据缺失或未实现动作崩溃 | 交互覆盖不足 | S1 扩展行为验收，不能只修参考路线 |
| 只有当前 Agent 没做出来 | 证据不足 | 在固定预算内独立诊断，不宣布无解 |

### 11.1 S1 推荐补充的质量要求

环境应提供合法的多个业务阶段、明确的状态前置条件、实体关系和可公开读取的决策信息。检查合理替代路线，不只检查一条示范链。

不要通过增加工具数量、把原子事务拆成多次 API、删除合理批量能力或加入无业务意义的分页来增加长度。

合法 reset 场景可以覆盖不同条件，但必须版本化、确定性重建、公开可求解。对子任务隐藏原始数据库写入，不属于合法 reset 场景。

这些要求与 ScaleEnv 强调的数据流、前后置条件、状态依赖及交互完整性方向相近；其全局图和生成初始数据库方式不直接照搬。[P03]

### 11.2 S1 与 S2 的证据要分开

S1 工作流诊断可以证明环境支持某类行为，但不自动成为训练任务。S2 仍需从公开输入重新构造自己的见证与任务。

同一 Need 发布新 Release 后，旧任务和旧指标保持绑定旧版本。只有新版本重新执行和重新准入后，才报告新的任务能力。跨版本比较应明确指出“环境也发生变化”，不要与固定环境上的采样算法对照混为一谈。

---

## 12. 代码改动映射与接口草案

### 12.1 现有模块

| 模块 | 改动 |
|---|---|
| `task_draft.py` | 将硬 shape/focus 目标与新的业务采样请求区分；必要时冻结新请求格式；增加公开要求与来源契约 |
| `task_proposal.py` | 解耦探索、见证执行、Draft 提取；见证者输入不得有父任务摘要；加入冻结意图核对 |
| `task_candidate.py` | 保留真实 replay、来源与副作用检查；加入 intent 对齐和新语义签名；不再仅凭旧结构键去重 |
| `task_goal.py` | 先修明知错误的路线绑定；被案例要求时实现第 4 节最小结果断言与严格版本规则 |
| `task_admission.py` | 复用五次 fresh 准入；不追加失败重试到成功；保留公开视图隔离；所有新真值格式严格读写 |
| `public_agent.py` | 复用现有公开执行循环；为 Witness / Admission / Efficient 绑定独立策略配置和输入 allowlist |
| `scripts/run_s2_task_campaign.py` | 将调度／产物逻辑下沉为可复用组件；支持显式 Release 子集、StartRef 与有界轮次；baseline 与新方法共用验证和记账 |
| `episode_runtime_v2.py` 及相关 S3 模块 | 只有新真值格式落地时同步适配；继续冻结任务与 post-reopen 验证，不引入长度 reward |
| `PROJECT.md`、相关 Trellis spec | 同步描述当前唯一生产契约，删除已过时入口说明；旧架构只在历史记录保留 |

现有 campaign 读取入口要求恰好 20 条 S1 记录，并另有采样 Release 子集机制。[C06] 新实现应允许显式 `release_ids` 的子集输入，不要求为了三环境 pilot 复制一个假的完整 campaign。必须验证输入 manifest 的真实来源，不猜测路径。

### 12.2 建议新增的少量模块

```text
src/agent_env_foundry/task_intent.py
    IntentSpec、EvolutionDelta、公开绑定契约

src/agent_env_foundry/task_evolution.py
    两个扩展算子、有限前沿、完整控制流

src/agent_env_foundry/task_complexity.py
    固定 probe、L_best 指标、局部依赖审计

src/agent_env_foundry/task_quality_artifacts.py
    assessment、谱系、签名、gap records 的严格产物读写
```

调度器暂时可以留在 `task_evolution.py`。没有必要为了每个阶段新建一个微服务或 Agent framework。

### 12.3 接口语义草案

以下函数名为计划新增，不能当作当前 API 已存在：

```text
propose_extension(public_seed, evolution_target, scout_driver) -> IntentProposal
freeze_intent(proposal, start_contract) -> IntentSpec
run_intent_witness(prepared, intent, policy_driver, instance_root) -> PublicWitness
extract_task_draft(intent, public_witness) -> TaskDraft
materialize_intent_candidate(prepared, intent, draft, witness) -> MaterializedCandidate
audit_task_complexity(prepared, candidate, protocol) -> ComplexityAssessment
select_evolution_frontier(valid_tasks, assessments, lineage, policy) -> Frontier
run_task_evolution_campaign(config, inputs) -> EvolutionCampaignManifest
```

共同要求：输入强类型／严格 JSON schema；所有预算为有上限的正值；传入固定 Release 身份；实例路径必须 fresh；typed failure 不丢失；禁止原地修改已发布产物。

`run_intent_witness` 返回真实交互记录和正常终止标记，不接受 LLM 自报的 `success=true` 作为成功真值。真正完成与否由 Host materialization、对齐检查和 evaluator 判定。

### 12.4 单一执行内核，而不是复制三套流水线

比较不同采样策略时，可以有 `direct / length_prompt / evolution` 的实验策略选择；这不应演变成三个不同的 reset、evaluator 或 TaskPack reader。

旧版本基线通过固定旧 checkout 留档复现。新策略在同一个当前内核上改变候选提出方式、预算分配和语料选择。不要把“算法对照”做成隐藏格式兼容 fallback。

### 12.5 配置草案

这是**计划中的配置格式**，当前 CLI 不保证直接接受。具体模型由实施者填入已有可用路线，不绑定某个商业模型名称。

```yaml
format: s2-task-evolution-config/1
baseline_commit: 1a6d3421315fc1e1c07961b54f950814ea21d40c
strategy: evolution
seed: 20260905

inputs:
  s1_manifest: REPLACE_WITH_VERIFIED_LOCAL_MANIFEST
  seed_task_manifest: REPLACE_WITH_VERIFIED_SEED_MANIFEST
  release_ids: []  # 必填：三个已验证 Release ID，不是环境显示名称

scope:
  operators: [prerequisite, discovery]
  allow_hidden_setup: false
  allow_cross_release_task: false
  allow_generated_checker: false
  allow_unverified_derived_operands: false

search:
  max_rounds: 3
  max_roots: 12
  candidates_per_parent: 2
  frontier_per_root: 1
  max_proposals: 72
  exploration_fraction: 0.20

execution:
  max_tool_calls_per_run: 48
  max_provider_turns_per_run: 64
  infrastructure_retries: 2
  semantic_retry_same_candidate: 0
  release_workers: 3
  freeze_schedule_per_round: true

admission:
  valid_runs: 5
  minimum_passes: 2

complexity:
  efficient_runs: 2
  max_deletion_probes: 3
  minimum_successful_standard_probes: 2
  length_buckets: [[1, 4], [5, 8], [9, 15], [16, 48]]
  include_length_in_reward: false

artifacts:
  preserve_all_terminals: true
  preserve_old_taskpacks: true
  identity_excludes_complexity_scores: true
```

48 次调用／64 次 provider turn 只是确保 5–15 次目标不被过紧预算截断的初值，不是平均消耗目标。现有 route 若没有独立 tool-call 上限，需要在 Host 增加计数并绑定策略身份，不能假装已经支持。

`semantic_retry_same_candidate=0` 指不因准入没通过就继续尝试直到 2/5。允许创建新 revision，但必须有语义／规格变更理由，计为新候选并重走全部流程；不能只换一个 ID 逃避失败记录。

## 13. 测试矩阵：开发时应直接转成测试项

单元测试中的最小状态 fixture 可以手工构造，用于检验 kernel；但这些 fixture 通过不能代替真实 Release 的端到端验证。框架代码不得为 fixture 的业务域增加条件分支。

### 13.1 意图与公开信息边界

| ID | 场景 | 必须结果 |
|---|---|---|
| I01 | 提案要求创建、分派、预约，执行只查询了技术员 | 不得缩小成查询题计为扩展成功 |
| I02 | 子任务移除父任务中的目标 ID，但 Witness 仍收到父摘要 | 输入泄漏测试失败 |
| I03 | 公开查询不能唯一确定目标 | `BindingAmbiguous`，不能使用 protected state 替 Agent 选目标 |
| I04 | 分页只读了第一页，声称唯一或完整集合 | 拒绝唯一性／完整性声明 |
| I05 | 冻结后修改了 instruction 的一个条件 | 新 intent ID、新 candidate、重新执行，不复用原准入 |
| I06 | 参数可以从公开信息计算，但当前表达机制不支持 | `RepresentationBlocked`，不当作隐藏猜值，也不悄悄接受 |
| I07 | 相同数字分别是数量和客户 ID | 不得仅因相等形成错误来源绑定 |
| I08 | 去掉重复查询仍满足真实信息需求 | 仍然允许完成，不强制 read 次数 |
| I09 | 修改目标起初已经完成，或查询答案已经完整公开在题目／reset | 不靠装饰调用通过非平凡性检查 |

### 13.2 执行、状态与重放

| ID | 场景 | 必须结果 |
|---|---|---|
| E01 | Scout 修改了其环境后提出任务 | Witness 必须从独立 fresh reset 重建，不继承修改 |
| E02 | 使用 Release 不支持的 reset 参数 | 正式拒绝，不做本地隐式 setup |
| E03 | 前置阶段可由公开操作建立 | 子任务完整执行与 fresh replay 通过，参数逐步公开获得 |
| E04 | 环境允许直接绕过所谓前置阶段 | 不认定该阶段为已证明必要；检查 Need 是否真的要求它 |
| E05 | Witness 存在任务外修改 | 继续拒绝；不能删除现有 unexplained-mutation 保护来让它过 |
| E06 | close 后 reopen 同目录，不 reset | 新 Goal 的关键持久事实仍成立 |
| E07 | 改一个独立 Episode 的状态 | 不影响其他 Episode 的初始或最终真值 |
| E08 | 相同 reset 和相同公开动作重放 | 在声明的确定性契约下观察与状态可重复 |

### 13.3 verifier 正反例

| ID | 场景 | 必须结果 |
|---|---|---|
| V01 | list 与 inspect 得到同一实体事实后完成目标 | 均通过，不能仅因发现路径不同拒绝 |
| V02 | 查询到另一个实体的同名字段 | 不得通过错误替代来源 |
| V03 | 状态正确但答案指向错误实体 | 失败 |
| V04 | 完成目标同时修改无关对象 | 失败，不能从参考 diff 自动扩大允许范围 |
| V05 | 两个独立业务动作合法交换顺序 | 满足公开要求时均通过 |
| V06 | 任务允许多个合法选择 | 支持该语义时均可通过；未支持时拒绝发布该任务，不能冻结参考选择 |
| V07 | 合法路线导致新建对象 ID 不同 | 按正确实体关系验收，或明确列为当前表示阻塞；不隐藏 exact ID 规则 |
| V08 | 用户明确要求先审批，执行绕过审批 | 失败；证据不充分则该任务不得宣称已可靠支持 |
| V09 | 全部查询但从未完成最终修改 | 失败 |
| V10 | required 字段被偷偷增加到 final answer schema | 意图对齐检查失败 |
| V11 | 误改无关对象后恢复，但公开规则禁止这种中途修改 | 必须使用过程证据拒绝；不能只看最终快照 |
| V12 | 资源在操作前可用，操作后因合法预留而占用 | 验收通过；不能要求前置可用条件在终态继续成立 |

### 13.4 去重、长度与调度

| ID | 场景 | 必须结果 |
|---|---|---|
| D01 | 直接 ID 与公开关系发现，最终 Goal 与 diff 相同 | 可区分语义要求，不能仅用旧粗结构键拒绝 |
| D02 | 同一个任务换措辞 | 合并为重复或同一家族，不夸大任务数 |
| D03 | 同一任务有三条合法路线 | 一个 Task，多条 route |
| D04 | 不同根产生同一模板 | 同组隔离或标记疑似泄漏，不只依赖 parent_id |
| L01 | 参考 10 次，高效解 4 次 | `L_best_all=4`，不进入 9–15 档；Task 仍有效 |
| L02 | 高效解均失败 | 不宣称不可压缩；记录探测不充分 |
| L03 | 删除发现步骤后从旧日志填回隐藏 ID | 审计无效，不计为公开短解 |
| L04 | 删除步骤后只因固定工具匹配失败 | verifier 争议，不计为因果依赖 |
| L05 | 父任务 30 次探测、子任务 2 次探测 | 不用于公平的 `L_best_probe` 增长比较 |
| L06 | 失败执行达到 48 次预算 | 不以 48 填充成功长度；长度为 null／无成功记录 |
| L07 | 改变 probe protocol 或模型 | 新 assessment 身份，不能混入原固定协议统计 |
| S01 | worker 完成顺序交换 | 同一轮的已冻结调度与下一轮输入汇总规则不受完成顺序影响 |
| S02 | 断点恢复 | 已完成 job 不重复采样，历史失败不被覆盖 |
| S03 | 一个环境增长率很高 | 家族／环境份额上限仍生效，其他环境保留探索预算 |

### 13.5 准入、责任与产物

| ID | 场景 | 必须结果 |
|---|---|---|
| A01 | 五次可信准入仅一次成功 | 不发布；不能追加第六次直到凑够两次 |
| A02 | 某次 Provider 429 | 单独重试上限与记录，不当作语义失败 |
| A03 | 五次准入两次通过，但语义审核发现隐藏条件 | 不因 2/5 覆盖已知任务缺陷 |
| A04 | 复杂度没达到档位，但任务有效 | ValidTaskPool 保留或语料不选，不标 Agent failure |
| A05 | evaluator 规则改变 | 原 candidate 重新验证；旧 TaskPack 不原地改真值 |
| A06 | relocation 后冷读全部产物 | 身份与 public/trusted 投影一致 |
| A07 | 给 S3 的 PublicTaskView | 不含 parent、Goal、expected answer、参考路线、长度目标、probe 结果 |
| A08 | 只导出成功 S2 Witness 作为 SFT | 阻止该捷径；训练 Episode 继续由 S3 正式生成和 S4 筛选 |

---

## 14. 实验设计：怎样证明改进来自算法

### 14.1 先做小规模机制试验

建议固定三个环境，例如维修、事件管理和订阅处理。最终选择须以实际 Release 的可执行能力为准，不能只按工具数决定。

从这三个环境选择最多 12 个已审计种子／根家族。每轮每个根最多两个候选、最多保留一个后代进入下轮，三轮最多 72 个扩展提案。前沿提前耗尽时，少于 72 个也是真实结果，不虚构候选补数。

提案上限不是发布数目标；不把 `WitnessUnsolved` 或 `RepresentationBlocked` 算成环境生成失败。

所有候选必须有真实终态记录。第一批发布候选逐题审查公开意图与正反例，以便及时发现系统性错误。

### 14.2 三个必要对照组

| 组别 | 候选生成方式 | 其他条件 |
|---|---|---|
| B0 | 当前直接采样思想：覆盖 shape/tool/outcome 后提出任务 | 同一组 Release、同一冻结 verifier 和报告口径 |
| B1 | 与 B0 相同，但 Prompt 要求较完整／较长任务 | 同上；不加入长度 reward |
| B2 | 本文意图冻结＋O1/O2 扩展＋有限递归＋高效审计 | 同上，完整统计新增探测成本 |

B0 保留其原采样思想用于对照，但为了公平验证，结果使用共同的当前验收版本。原封不动旧产物结果另列为历史参考，不与新 verifier 的结果直接比较。

**预算公平：** 既报告等提案数的结果，也报告固定总 provider token／调用预算内的有效产出。B2 多了探测和审计，不能只按“72 次采样”说成本相同。

方法顺序轮换或以批次交错运行，尽量减少服务负载差异。记录真实 route、temperature、模型版本、系统提示和时间；模型版本不明时如实记录提供方返回信息，不凭名字假定相同模型。

### 14.3 关键消融（在核心试验可行后做）

**去掉递归：** 只做一轮意图级扩展，但分配相同总预算。用于区分收益来自“更好的目标粒度”还是来自“递归累积”。

**去掉高效审计：** 尽量使用同一批已产生候选，比较按参考长度选择与按固定 probe 选择的语料。用一批双方都未见过的独立高效探测评估它们，避免自己的筛选规则证明自己有效。

**保留旧粗去重：** 对对象发现候选离线对照被旧结构键误合并的数量，再审查这些是否真的增加信息需求。不要把“被保留下来更多”直接当成质量提高。

不必第一轮同时完成所有消融。主流程能稳定产生明确增量后再增加。

### 14.4 必须报告的指标

| 层面 | 指标 |
|---|---|
| 有效性 | 提案→见证→replay→准入→发布各阶段数量、失败归因、正反例审计问题数 |
| 采样质量 | 独立语义家族数、依赖 E1/E2 分布、业务阶段与对象发现类型、重复比例 |
| 执行长度 | `L_best_all`、固定协议 `L_best_probe`、成功轨迹长度；按任务加权，不按 rollout 数重复加权 |
| 长度可信度 | 参考解被缩短比例、已发现合法短路线数、verifier 争议数量、成功 probe 数 |
| 难度 | 对固定策略的独立成功率、失败分类、预算截断比例；不能把框架故障算模型难度 |
| 成本 | 全部提案、失败、replay、准入、审计的 tokens、工具分派、延迟和成本；每个有效家族／中长任务的成本 |
| 分布 | 每个环境和家族的份额、初始状态类型、长度梯度、任务类型覆盖 |

五次准入已经参与筛选，不是最终独立评估。报告评估成功率时，以任务／根家族为聚类单位估计不确定性；同一任务的多次 rollout 不能当作独立任务样本。小样本优先给完整计数与分布，避免用显著性语言包装。

### 14.5 试验成功条件与停止条件

以下是建议在试验前冻结的工程目标，而不是普适标准：

- 至少两个不同 Release 能产生通过完整验证的扩展任务。
- 有新增任务来自至少六个根家族，而非一个流程的大量变体。
- 在通过审计的扩展子集中，出现稳定的 5–8 次最短已知路线，并有公开依赖证据；观察中位数能否达到至少 5。
- 与 B0/B1 相比，在相同总预算口径下看到更好的有效多步任务产率，或能清楚解释质量提高所付出的成本。
- 已知等价路径假阴性、隐藏条件、非法初始状态等问题没有被当成“复杂性”。

未达到这些目标也要保留结果。若主要阻塞是表示或环境能力，先修该层；若单纯高效解都只需两步，就说明该任务家族不适合长任务目标，不继续堆同义 Prompt。

### 14.6 后续训练价值只做独立闭环

生成机制通过后，再由 S3 为冻结 TaskPack 生成轨迹，S4 做去重、轨迹质量控制和训练。

至少比较：基础任务 SFT 与基础＋扩展任务 SFT；匹配实际 chat template/tokenizer 下参与 loss 的训练 token 或公开说明的算力预算，不使用 Provider 计费 token 代替训练 token。

按根家族隔离，并单列未见环境结果。高成功率教师数据可以用于 SFT，不因教师全对就宣布无价值。对具体 RL 算法的采样信号另做模型相对评估，不在本轮 S2 算法里强制失败率。

在这组训练对照完成之前，允许的结论是“产生了更完整、经验证的多步任务”，不是“证明模型能力提升”。

---

## 15. 按 PR 拆分的实施顺序

### PR0：固定基线与最小语义审计

**做什么：** 验证输入提交与真实 manifest；重算基线任务／轨迹口径；收集等价查询、错误对象、无关副作用等最小案例；确认哪些环境属于第 4 节可支持子集。

**验收：** 固定输入身份、可重复统计脚本、正反例测试、明确的表示阻塞清单。必要的最小 verifier 修复落地并冻结版本。没有通过语义门槛的任务不进入后续“长度提升”报告。

**不做：** 新增环境、训练模型、一次重写所有 Goal 语法。

### PR1：意图冻结与新去重

**做什么：** 实现 IntentSpec、Witness 输入隔离、Draft 提取、完整目标对齐、任务语义签名与谱系。

**验收：** I01–I08、D01–D04；冻结后不能缩题；父任务 ID 不泄露；同 Goal 的发现型任务不会被粗去重抹掉；改写不会被当新任务。

**不做：** 递归调度和复杂度自适应。

### PR2：O1/O2 与合法起点

**做什么：** 在同一 Release 上实现两种扩展；正式 StartRef；复用完整 replay 和五次准入。

**验收：** 至少两个环境有实际扩展见证与重放证据；每个失败都有责任归因。单元测试通过不能代替真实运行。

**不做：** 隐藏 setup、原生写库、临时增加每题工具。

### PR3：高效探测、依赖审计与分档

**做什么：** 固定标准／高效 probe；实现 `L_best_all` 与 `L_best_probe`；有限删步；争议隔离；独立 assessment 产物。

**验收：** L01–L07；参考路线可以被更短解降档；审计失败不能自动变成高难度；所有额外成本有记录。

### PR4：有限递归与 campaign

**做什么：** 三轮以内的有限前沿、每轮冻结调度、家族上限、断点恢复、完整终态记账；先均匀预算再启用简单权重。

**验收：** S01–S03、A01–A08；串并发不会通过完成顺序改变逻辑调度；旧任务和已发布真值不被覆盖。

### PR5：机制试验与报告

**做什么：** B0/B1/B2 固定环境、冻结 verifier 对照；逐题语义审计；冻结独立 probe；产出失败分析与环境能力缺口。

**验收：** 不只交一张“平均调用数上升”的图，而是给任务实例、家族、依赖、短解、成本和失败归因的完整证据。

后续再选择：补有界派生参数、O3、场景对、S1 能力增强或 SFT 对照。由实际阻塞决定，不同时扩张所有方向。

---

## 16. 给实施 Agent 的任务书

下面这段可以直接作为开发任务的起始说明；实施时同时提供本文件。

```text
以当前固定 s3-sft-trajectories 基线为起点，实现 S2 的意图约束递进采样。
先核对当前 checkout 与 1a6d342... 的差异，不覆盖未提交修改，不混用旧分支架构。

目标不是奖励更长轨迹，而是在保持 Good Task 准入要求下，
产生具有更完整业务目标、公开信息／状态依赖的任务。

按 PR0→PR5 实施。第一版只主做 prerequisite 和 discovery 两种扩展。
保留真实公开执行、fresh replay、五次可信求解至少两次通过、
状态隔离、不可变产物、post-reopen 验证和 S3 reward 责任边界。

先修复影响实验判断的辅助查询绑定／结构去重问题。
如果遇到多解、动态 ID、派生参数或历史约束无法表达，
给出最小反例与 typed blocker，不加每题 Checker，不写业务域分支，
不放宽为只看 ok=true，不把 protected state 用作执行参数来源。

把 Scout、Witness、Admission、Efficient 的输入严格分开。
Witness 不能见父任务和探索记录，冻结意图后不许缩题冒充成功。
所有提案、失败、重试、审计和成本都保留。

实现 L_best_all 与固定协议 L_best_probe；找到更短合法解时更新分档，
不改变该任务的成功 reward。长度目标不进入 Acting Prompt。

先在固定少量现有 Release 中得到真实证据，再决定是否需要改 S1。
不要只交 mock、绿色单测或手工拼接轨迹作为阶段完成证据。
```

### 16.1 本地准备建议

这些是供用户执行的命令示意，本文没有执行或修改该本地 Worktree：

```bash
cd /home/kelong/pycodes/foundry-s3-sft-trajectories
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/s3-sft-trajectories

# 确认基线与未提交改动后，从指定远端另建工作分支。
# 分支或目录已存在时，先检查，不强制覆盖。
git worktree add -b s2-task-evolution \
  ../foundry-s2-task-evolution origin/s3-sft-trajectories
```

若远端已不等于文档基线，先比较差异并更新 source manifest。不要使用 `git reset --hard` 去迁就本文。

---

## 17. 常见误实现与最终交付检查

### 17.1 必须避免的误实现

| 误实现 | 为什么错误 | 正确处理 |
|---|---|---|
| instruction 加“至少调用八次工具” | 将数据采样目标变成用户要求，鼓励冗余 | 长度只用于选择任务 |
| 失败候选自动变成已完成的查询小任务 | 丢掉原来的业务扩展目标 | 新 revision，原失败保留 |
| 继承父环境快照作为子任务起点 | 破坏 fresh reset 与公开可解 | 合法 reset 或公开重建 |
| Proposer 的所有上下文给子任务求解者 | 被隐藏的目标信息可能提前泄漏 | 全新 Witness 会话 |
| 只删 read Atom，不改粗结构去重 | 信息发现扩展仍可能被淘汰 | 增加语义目标定位特征 |
| 只比较 reference trace 长度 | Teacher 绕路就能提高指标 | 独立高效探测＋依赖证据 |
| 少跑难题，找不到成功短解就分到最长档 | 以探测不足伪造难度 | 缺失值与预算截断单列 |
| 相同 scalar 值自动认作数据依赖 | 可能连错实体或字段 | 身份、类型、字段、时点与来源共同核对 |
| 任意放宽最终状态忽略列表 | 会放过无关修改 | 公开规则支持的结果／副作用范围 |
| 强制任意合法选择等于参考选择 | 把私有决定变成隐藏要求 | 正确支持多解或拒绝该任务 |
| 候选不断重跑直到通过 2/5 | 发布证据被成功重采样污染 | 冻结五次准入，所有终态记账 |
| 更复杂必须让教师失败更多 | 教师失败可能来自语义或基础设施缺陷 | 模型难度与任务缺陷分开 |
| 直接把 S2 扩展成功轨迹当新 SFT 成果 | 混淆生成、准入和训练利用 | S3 正式采集，S4 独立筛选训练 |

### 17.2 Done Checklist

- [ ] 基线 commit、输入 Release／TaskPack／corpus manifest 都已冻结并校验。
- [ ] 统计区分任务实例、根家族、rollout、路线和 provider tokens。
- [ ] 每个 candidate 有冻结意图，修改意图必有新 revision。
- [ ] Witness 不接收父任务、Scout 历史或隐藏 ID。
- [ ] 所有 task 起点都能从正式 reset 重建。
- [ ] O1/O2 有多个真实环境上的公开执行证据。
- [ ] 去重能区分 ID 直给与关系发现，也能识别同义改写。
- [ ] 等价查询路径通过，错误对象和无关副作用被拒绝。
- [ ] 已知 verifier 争议候选被隔离，不用来宣传长任务或训练失败样本。
- [ ] 五次准入与 2/5 门槛保持，infra 不成为模型负例。
- [ ] 最短已知长度绑定 probe 协议，失败和缺失值不伪装成长度。
- [ ] 找到更短正确解会降档，S3 reward 不因调用变少而下降。
- [ ] 依赖证据区分 E0/E1/E2，不声称全局最短或全局必要性。
- [ ] 前沿有限、家族限额有效、所有阶段成本与终态可重建。
- [ ] 数据分区按根家族和跨根语义相似性隔离。
- [ ] 冷读、迁移与 public/trusted 泄漏测试通过。
- [ ] 对照实验使用同一环境与 verifier，报告额外审计成本。
- [ ] 未训练前不写模型提升；未审查原始产物前不写“已完成真实实验”。

---

## 18. 论文依据与采用边界

这里列出的是经过检索的相关原始论文。算法主体是面向当前代码的设计建议，不是把任何论文结果直接搬成 Foundry 的效果。

| 编号 | 论文 | 本文借鉴 | 不照搬的部分 |
|---|---|---|---|
| P01 | Recursive Synthesis for Long-Horizon Terminal Tasks，固定阅读 v2，2026 | 已验证种子、递归扩展、重新验证、家族限额 | 可修改环境和任务专属脚本的终端任务格式；其命令数不等于本项目工具调用数 |
| P02 | TaskCraft: Automated Generation of Agentic Tasks，固定阅读 v1，2025 | 区分深度／宽度；把直接给出的目标信息转为前置查询 | 其主要任务形态与 Foundry 状态业务不同，不能直接推断训练效果 |
| P03 | ScaleEnv: Scaling Environment Synthesis from Scratch for Generalist Interactive Tool-Use Agent Training，固定阅读 v1，2026 | 数据、前后置条件、状态依赖与交互完整性 | 全局 Tool Graph、按链构造数据库和图规模要求不直接采用 |
| P04 | EnvScaler: Scaling Tool-Interactive Environments for LLM Agent via Programmatic Synthesis，固定阅读 v1，2026 | 环境逻辑与场景起点分离；注意反向包装调用序列的局限 | 每任务生成验证函数及 S2 任意生成数据库不采用 |
| P05 | ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities，固定阅读 v1，2024 | 用状态、必要里程碑和禁止事项表达业务要求 | 不引入其全部会话／评测框架，也不把里程碑数量当任务难度 |

公开来源：

- [P01] `https://arxiv.org/html/2608.05466v2`，重点为第 4 节与 Appendix D；本文不复述其规模或训练增益作为项目目标。
- [P02] `https://arxiv.org/html/2506.10055v1`，重点为任务深度／宽度扩展方法。
- [P03] `https://arxiv.org/html/2602.06820v1`，重点为第 4.1.3 与 4.2 节。
- [P04] `https://arxiv.org/html/2601.05808v1`，重点为第 4.1 与 4.2 节。
- [P05] `https://arxiv.org/html/2408.04682v1`，重点为有状态评估、milestones 与 minefields。

**可能形成的项目贡献需要实验支持：** 在不可变环境、公开执行与统一验证边界下，将完整意图扩展、来源隔离、最短已知解审计和依赖感知去重组合起来，改善单位预算内有效多步任务的产出。不能只因引入“递归”就声称提出了全新算法。

---

## 19. 固定代码来源索引

下列引用均对应分析基线提交，而不是默认分支。正文的代码事实可以通过文件和函数名复核。

**[C01] 采样提示、公开执行循环与 `reset_start`**  
`src/agent_env_foundry/task_proposal.py`：`_SAMPLING_PROMPT`、`sample_task_draft`、`_provider_turn`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/task_proposal.py`

**[C02] SamplingTarget、公开来源、答案与 Draft 类型**  
`src/agent_env_foundry/task_draft.py`：`SamplingTarget`、`PublicValueRef`、`AnswerProjection`、`ForEachDraft`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/task_draft.py`

**[C03] 物化、全轨迹 replay、参数溯源与粗结构去重**  
`src/agent_env_foundry/task_candidate.py`：`materialize_candidate`、`derive_argument_origins`、`_structure_id`、`_goal_structure`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/task_candidate.py`

**[C04] 通用 evaluator 的实际比较方式**  
`src/agent_env_foundry/task_goal.py`：`GoalTruth`、`evaluate_goal`、`_atom_matches`、`_evaluate_if`、`_evaluate_foreach`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/task_goal.py`

**[C05] 五次准入、Driver 接口与 TaskPack**  
`src/agent_env_foundry/task_admission.py`：`TaskFilterEvidence`、`filter_candidate`、`PolicyDriverFactory`、`seal_task_pack`、`PublicTaskView`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/task_admission.py`

**[C06] 当前实际 campaign 调度与调用入口**  
`scripts/run_s2_task_campaign.py`：`_select_target`、`_read_s1_releases`、`_select_pending_sources`、`_run_attempt`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/scripts/run_s2_task_campaign.py`

**[C07] S1 环境契约与需求范围**  
`src/agent_env_foundry/runtime_skills/environment-codegen/ENVIRONMENT_CONTRACT.md`；`experiments/batch-environment-task/needs.json`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/src/agent_env_foundry/runtime_skills/environment-codegen/ENVIRONMENT_CONTRACT.md`  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/experiments/batch-environment-task/needs.json`

**[C08] S2 / S3 报告与原始产物位置说明**  
`experiments/s2-good-task-sampler/S2_GOOD_TASK_CAMPAIGN_REPORT.md`；`experiments/s3-verified-sft-trajectories/S3_TRAJECTORY_CAMPAIGN_REPORT.md`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/experiments/s2-good-task-sampler/S2_GOOD_TASK_CAMPAIGN_REPORT.md`  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/experiments/s3-verified-sft-trajectories/S3_TRAJECTORY_CAMPAIGN_REPORT.md`

**[C09] 当前产品阶段边界**  
`PROJECT.md`；`.trellis/spec/backend/s2-good-task-sampler.md`。  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/PROJECT.md`  
`https://github.com/zhkzly/agent-world-model/blob/1a6d3421315fc1e1c07961b54f950814ea21d40c/.trellis/spec/backend/s2-good-task-sampler.md`

---

## 20. 最终决策

**实施这套方案，但以“小规模验证有效增长”作为第一目标，不立即扩大环境和轨迹数量。**

首先证明：在既有业务环境中，意图约束的前置／发现扩展能够产生新的、公开可解的完整任务；这些任务在独立高效求解下仍然需要更多有效操作，并且没有借助隐藏初始化、强制参考路线或去重漏洞制造增长。

如果这一点成立，再增加递归规模、场景与业务范围，并通过 SFT／RL 对照检验训练价值。若不成立，失败归因应明确指出问题在目标搜索、环境状态、表示能力还是 verifier，而不是继续要求模型“调用得更长一点”。
