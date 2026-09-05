# Foundry S2：任务递进采样完整实施规格

> 状态：完整实施规格；算法代码尚未按本文实施，未宣称真实实验已经通过。  
> 更新日期：2026-09-05。  
> 代码基线：`zhkzly/agent-world-model`，`s3-sft-trajectories`，`e02595a4044419ae755f13f02e21237f1c935171`；该提交相对已跑通的 `1a6d3421315fc1e1c07961b54f950814ea21d40c` 仅增加设计文档及 README 入口。  
> 本文替代此前按 PR0–PR5、先后版本和可选接口组织的实施建议。旧论证可从 Git 历史查阅，不再作为另一份并列执行规格。  
> 交付方式：一次完整实现本文规定的方法、接口适配、测试、真实运行、产物冷读和报告。内部按依赖编写及验证，不等于分期交付；不得在中间检查点把任务标为完成。

## 0. 实施任务与唯一完成标准

实现 **Intent-Grounded Task Evolution：意图约束、执行验证与短解诊断反馈驱动的有限任务递进搜索**。

目标不是让 Agent 故意增加调用，而是从现有真实环境中合成业务更完整、信息和状态依赖更多、仍公开可解且可验证的任务。正确的高效解始终应该通过。长度只用于任务评估和语料选择，不进入题目要求或 S3 reward。

必须完整交付：

| 编号 | 必交能力 | 不算完成的替代品 |
|---|---|---|
| R01 | 冻结业务意图，隔离探索、见证和独立求解 | 只给原 Prompt 加“复杂一点” |
| R02 | O1 前置扩展、O2 对象发现、O3 关联结果扩展 | 仅硬编码一个业务链 |
| R03 | 合法起点选择、完整公开执行、fresh replay | 隐藏 setup 或拼接已有轨迹 |
| R04 | 有限的路径开放结果验证及严格公开来源检查 | 固定参考工具链或取消状态校验 |
| R05 | S2、复杂度探测、S3 使用一致的任务判定语义 | 各写一套通过条件 |
| R06 | 高效策略、长度探测、局部依赖审计、短解原因反馈 | 只统计 Teacher 的工具调用数 |
| R07 | 实例去重、任务语义分组、谱系及数据隔离 | 只用旧结构键或文本相似度 |
| R08 | 有限递归、预算调度、并发、恢复和失败留档 | 一个只能运行一次的演示脚本 |
| R09 | TaskPack 发布、磁盘重载、S3 rollout、重开验证及冷读 | 仅返回内存里的 Candidate |
| R10 | 自动测试、真实环境验收、独立对照和机器可读报告 | TODO、假报告、只跑 mock 或单元测试 |

这是 S2 方法及其 S3 接入的完整交付，不包含 S4 模型训练、跨环境超级任务、任意程序生成、任意算术规划、全局最短路径证明或训练任务生成模型。这些是明确的产品边界，不是允许少做 R01–R10 的理由。

**完成状态分开记录，不能混淆：**

- `implementation_complete`：R01–R10 所需代码、接口、CLI、测试和文档均已实现，无占位分支。
- `live_validation_complete`：真实 Release 上的自动生成、准入、TaskPack 重载、S3 与产物迁移冷读均有证据。
- `evaluation_complete`：所有声明的对照和审计已经运行，成本和失败完整记账。
- `effect_status`：`improved / inconclusive / not_improved`，依据真实结果填写，不能预设必须改善。
- 对外说“实现并验收完成”需要前三项为 true；说“解决任务偏短问题”还需要效果证据。真实环境、凭据或依赖不可用时，明确报告未完成的验收及阻塞，不以替代数据冒充通过。

不得在只做完一个算子、一个 canary 或一组单元测试后结束为“完整实现”。也不得因目标长度尚未达到而降低任务正确性门槛或无限重试。

## 1. 基线、权限和改动边界

### 1.1 从确实跑通的分支开始

实施前读取 `AGENTS.md`、`PROJECT.md`、`DECISIONS.md` 和当前 Trellis 工作流；确认实际 checkout、HEAD、未提交修改与本文基线的差异。用户提供的工作目录是 `/home/kelong/pycodes/foundry-s3-sft-trajectories`，它是本机路径，不能在没有访问该机器时声称已经运行。

保留基线代码和旧实验产物。不得 `reset --hard`、清理未知未跟踪文件、覆盖已有 Release 或重新生成“相似环境”冒充原环境。需要工作分支时从确认过的指定分支派生，不用旧 `main` 或同名历史分支代替。

本文作为实施输入；只有用户发起实现任务后才依仓库规则激活对应 Trellis task。文档存在本身不自动激活运行或授权修改业务数据。

### 1.2 已确认的接入点与必须解决的差异

| 现有位置 | 基线事实 | 本次完整实现要求 |
|---|---|---|
| `task_proposal.sample_task_draft` | 无冻结 instruction 的独立输入；执行后返回题目 | 固定意图模式与自由提案模式显式分离，固定题目禁止改写 |
| `task_draft.SamplingTarget` | shape、focus tool、outcome 为硬要求 | 递进请求不沿用工具覆盖作为业务 Goal；覆盖留在调度层 |
| `task_candidate.materialize_candidate` | 重放完整采样轨迹；拒绝未解释的修改 | 保留副作用审计，隔离 Scout；不得通过删保护让探索修改混入题目 |
| `task_candidate.derive_argument_origins` | 主要按公开叶子值相等或字面量找来源 | 引入显式引用和实体锚定；同值不自动代表同语义来源 |
| `task_goal.evaluate_goal` | Atom 匹配工具名、参数；终态与答案对参考精确比较 | 实现第 5 节有边界的结果判定，不能制造路径型假难度 |
| `task_candidate._structure_id` | 未表达对象如何被公开定位 | 不作为新任务的唯一重复拒绝条件 |
| `public_agent._capture` | 强制 `PUBLIC_AGENT_PROMPT_DIGEST` | 支持 Host 冻结的角色策略，保留摘要一致性校验 |
| `task_admission._filter_attempt` | 除 Goal 外还检查参数来源 | 与 S3、probe 共享同一个组合判定函数 |
| `episode_runtime_v2.run_task_episode` | Goal 判定与 S2 来源检查不完全相同 | 补齐共享验证，保留 close/reopen 和责任归因 |
| `preparation_v3` | 已有 Release/3 校验和真实原生运行时 | 复用，不重写简化加载器；暴露只读 schema 访问器供 Host 使用 |
| `scripts/run_s2_task_campaign.py` | 默认 20 个源记录；采样调用未传 reset_start | 公共输入解析支持真实 manifest 子集；显式传合法起点 |
| `episode_artifacts` | 已有 paired view、身份和冷读检查 | 复用其机制，同步新判定所需字段及严格 reader |

这些是规格的明确依赖，不是实现时“有空再做”的可选项。

### 1.3 不能保证的事情

静态审查和文档不能保证 AI 第一次编码无错误，也不能证明本机产物仍存在或模型服务仍可用。解决方式是要求实现者修复自己引入的问题并完成真实验收，不是跳过验收或把部分工作称为最终版本。

## 2. 固定产品约束

1. 所有行动发生在公开工具及真实持久状态上；无模拟 observation 冒充真实运行。
2. Witness、Admission、Efficient 和 S3 policy 看不到 protected state、参考答案、父任务轨迹、Goal、audit 结果或长度目标。
3. 起点只来自 Release 的正式 reset；不得复用 Scout 状态、恢复父任务中间快照或原生写库。
4. 题目在见证前冻结；可执行性与可信答案由执行、来源检查、replay 和准入建立。
5. 五次可信独立准入会话、至少两次通过；不因模型失败追加会话凑成功。
6. Provider、环境、产物或证据链故障与模型未完成分开；S3 仍为 `1 / 0 / null`。
7. 不生成每题 Python Checker，不在 Framework 写维修、采购等业务 if/else，不以全局 Tool Graph 编造链条。
8. 接受任务语义允许的等价解；更短正确解降低任务长度评估，不降低其 reward。
9. 长度、探测、调度和谱系不改变已冻结任务真值，不能写进公共题目作为执行下限。
10. 确定性校验不等于自然语言语义已被数学证明；语义审核、正反例和执行证据需共同留档。
11. 不为增加长度拆碎合理 API、删除批量接口、增加无业务意义的分页或要求无关查询。
12. 短任务可以合法并有训练用途；未入中长任务语料不等于模型失败或任务无效。

## 3. 必须实现的数据契约

所有新类型使用已有 Python、dataclass、JSON schema 与 canonical JSON 工具。公开字段与受保护字段分不同类型；不使用一个任意字典在不同角色间传递。格式严格拒绝未知字段，schema 校验、摘要重算、写入后冷读均有测试。

### 3.1 起点与提案

`StartRef`：

```text
release_id
reset_config: object | null
start_schema_digest
reset_config_digest
public_regime_description
qualification_evidence_id
```

`reset_config` 是 Host 的初始化配置，不全部暴露给求解者；任何决策必要信息必须能从 reset observation 或公开工具获得。合法性由 start schema 校验及两次 fresh reset 的一致性检查共同建立，不只依靠 schema。

`EvolutionTarget`：

```text
job_id, round_index, release_id
parent_task_id | null, root_family_id, split_group_id
operator: prerequisite | discovery | outcome_extension | root
allowed_start_refs
coverage_request, budget_profile_id
```

没有 required_call_count、隐藏 ID、参考解或任意 setup 程序字段。

`IntentProposal`：候选公开题目、业务目的、保留与新增的条款、合法起点引用、公开可行性线索。提案不是 Task，不继承父任务的成功结论。

### 3.2 冻结意图

`IntentSpec` 必须包含：

```text
intent_id                    Host 重算
instruction_exact            求解者实际看到的完整题目
start_ref_id
clauses[]:
  clause_id
  text                       在 instruction 中可定位的要求
  kind                       target | outcome | condition | prohibition | answer
  public_scope_description
  time_scope                 initial | final | before_event | throughout
answer_field_requests[]       字段及公开语义，不包含真实值
revision_of | null
```

`EvolutionDelta` 单独保存父任务、算子、增量理由、保持与变化项；不传给 Witness。

冻结后修改 instruction、条件、答案字段或范围，必须创建新 intent，重新 Witness、replay、五次准入。仅不改变语义的 JSON 编码错误允许在同一证据基础上重新提取；不得以“修答案格式”为名追加未公开字段。

### 3.3 公开绑定与实体定位

`PublicBindingSpec` 表达任务如何公开确定对象，不表达参考工具链：

```text
binding_id
entity_kind
resolution_kind              literal | public_predicate | related_entity | created_entity
public_anchor_refs
predicates                    有类型的等值/比较、字段关系与范围
cardinality                   unique
completeness_evidence_refs
```

允许公开关系解析和唯一目标；不要求参考发现工具。分页范围未完整获得不能声称唯一。新建对象通过业务键、关系及相对于 initial 的新增性识别，不依赖参考运行偶然分配的 ID。

本文不支持任意多个合法目标的自由选择。遇到这种题目必须拒绝发布为本次支持的任务，不能隐藏“选参考对象”规则。提案器可以提出一个本来就有明确公开选择规则的新需求，但必须重新冻结与执行，而非改题后复用旧结果。

### 3.4 证据与身份

必须有独立类型：

- `PublicWitness`：真实公开交互、正常/未完成终止标记、策略、用量；不包含成功真值。
- `IntentBinding`：条款到公开绑定、结果断言及答案字段的映射。
- `ReleaseBindingEvidence`：任务无关的公开实体与原生状态对应关系证据。
- `SemanticAudit`：审查者、输入摘要、逐条覆盖、问题、结论及引用，不计算 reward。
- `ComplexityAssessment`：探测协议、路线、最短已知长度、依赖证据和分档。
- `EvolutionRecord`：提案到终态的全部引用、责任、时间及成本。
- `CapabilityGapRecord`：公开可重现的阻塞，不把 Witness 没解出自动称为环境不支持。

Task 身份绑定 Release、起点、公开 instruction、结果/答案契约和验证版本；assessment、worker 数、长度、前沿排名不能进入任务语义身份。证据 bundle 自身可以有不同 artifact ID。必须区分语义身份与包含运行证据的物理包身份。

## 4. 完整执行链路与角色输入

### 4.1 单一链路

```text
读取并校验真实输入 manifest
→ 选择根任务、StartRef 和扩展算子
→ Scout 在独立可丢弃实例中探索
→ Proposer 提出完整子任务
→ Host 冻结 IntentSpec
→ 新 Witness 仅凭子任务公共输入执行
→ Extractor 从该次公开 trace 提取目标证据与答案投影
→ Host 绑定公开事实和真实状态、检查副作用与条款覆盖
→ fresh reference replay
→ 独立语义审查与正反例核验
→ 冻结 Candidate
→ 五次 fresh Admission，至少两次通过
→ 高效探测、局部干预、争议检查
→ TaskPack 发布并从磁盘重新加载
→ 单独存储 assessment、谱系、语料
→ 前沿选择与下一轮；结束后冻结 Corpus
→ S3 从磁盘消费 Corpus/TaskPack，独立 rollout
→ close/reopen、共享验收、Episode 落盘及迁移冷读
→ 独立评估与报告
```

不能另写一条只生成长 trace、不产生正式 TaskPack 的成功路径。

### 4.2 输入隔离

| 角色 | 允许输入 | 禁止输入 |
|---|---|---|
| Scout/Proposer | Need 的公开业务部分、ToolSpecs、父任务公开意图、自己探索的 observation | protected state、父任务答案、参考轨迹、评估隐藏答案 |
| Witness | 子任务 instruction、fresh reset observation、ToolSpecs、自身 observation、固定角色策略 | 父摘要、Scout 历史、预期步骤、隐藏目标 ID、长度目标 |
| Extractor | 冻结意图、Witness 的公开 trace、公共 schemas | protected state、自己执行新工具补造结果 |
| Host/Binder | frozen intent、公共证据、原生状态及 schema | 不可将受保护数据补给任何 Acting policy |
| Admission/Efficient/S3 | PublicTaskView、自身新环境与角色策略 | Witness、父任务、隐藏 Goal、正确答案、probe 结果 |
| Semantic Reviewer | instruction、公开规则、证据及断言的语义说明 | 不可修改已冻结任务，不可代替执行验证 |

公开视图使用显式 allowlist 和递归泄漏测试，不能只靠文件名带 `trusted`。

### 4.3 解决 Witness 的答案 schema 前置循环

Witness 执行时正式答案 schema 尚未由 observation 推导，不能把参考答案或预期值传给它，也不能要求先有 TaskPack。

Witness 使用固定的终止协议：`{status: done|unable, note: string}`。这是公开执行的停止声明，不是任务答案，不是成功标签。终止前的全部公开 observation 被保留。Extractor 随后给出 `AnswerProjection`，Host 按公开字段 schema 推导正式 type-only answer schema 和参考答案；后续 Admission、probe、S3 才使用该正式 schema。

复用公开工具分派、capture、provider adapter 与生命周期；角色终止 schema 可以不同，但不复制四套工具 loop。Witness 的 `done` 不足以通过 materialization；漏掉业务结果必须被断言和语义覆盖拒绝。

### 4.4 固定题目模式

`sample_task_draft` 的改造必须提供冻结 intent 的明确入口。直接根任务先提出 intent，再进入同一个执行内核。实验中的 baseline 可保留“先自由探索形成题目”的候选提出方式，但最终验证、来源检查、产物和 S3 消费共用当前内核。

不得把 `fixed_instruction` 塞进 development brief 却仍允许执行后重写。必须在 Host 比较冻结摘要、实际 public input 和 draft instruction。

## 5. 必须实现的有界结果验证内核

这是本次交付的一部分，不再写成“需要时再做”。不要求万能 DSL，但不能依靠已知错误的固定查询 Atom 宣称路径开放。

### 5.1 验收语义

保留 Atom / All / If / ForEach 的组合思想；新 Atom 表达结果或明确过程要求，不默认表达“参考调用发生过”。

至少支持以下有限断言：

| 断言 | 判定规则 |
|---|---|
| `EntityFieldEquals` | 在指定时点按唯一实体 selector 解析目标，字段与公开要求或合法引用一致 |
| `UniqueEntityExists` | 满足业务键和关系的实体恰好一个；新建要求还检查 initial 中不存在该实体 |
| `AnswerMatchesFact` | 输出字段与本次实际执行的已验证、可公开获取事实一致，不固定参考生成 ID |
| `UnrelatedStateUnchanged` | scope 之外的实体及关系保持不变；允许的维护字段有独立依据 |
| `PublicEventRequirement` | 仅在用户或公开规则确实要求过程时，核对真实事件、主体和先后时点 |

All 不默认要求顺序；If 的条件必须有明确时点和公开可观测来源；ForEach 作用于完整、冻结范围内的成员集合，保留有界同类 body，不扩展任意程序循环。

同一 frozen reset 实际走过一个条件分支，只证明该任务实例，不证明另一分支。跨场景分支能力通过各自执行、各自准入的匹配任务对验收。

### 5.2 原生状态绑定不能靠字段同名猜测

为每个 Release 构造并冻结 `ReleaseBindingEvidence`，只包含任务无关数据映射，不包含可执行 Python：

```text
release_id, actor_digest, state_schema_digest, public_schema_digests
entity_mappings[]:
  entity_kind
  collection_path
  identity_fields
  public_identity_sources
  public_field_to_native_field
  relation_fields
  justified_maintenance_fields
supporting_observations
native_snapshot_refs
qualification_record
```

集合路径用明确的 map/list 遍历规则；实体通过身份键定位，不能把数组位置当实体身份。公开字段到原生字段必须同时具备实体类型、身份、作用域和时点证据；布尔值或数字相同不构成映射证据。

实现流程：枚举 schema 允许的映射候选，使用有实体锚点的真实 observation 与原生快照验证，再由独立语义审查核对解释。确定性验证失败不能被审查者覆盖。若存在多个同样可行的映射，返回 `BindingAmbiguous`，不得任选一个。

该映射是 S2 Host 的受保护分析产物，绑定精确 Release，不修改 Release 字节；不能包含 Checker、Task-specific 路径代码或任意白名单。当前 Release 无法提供可靠身份/字段关系时产生 S1 能力反馈，不静默改环境。新增 S1 元数据或环境行为必须经正式 Qualification 和新 Release，不能混入本次固定环境对照。

这里不是声称自然语言语义能被 schema 自动证明。独立审查与反例仍是必要证据；不能用一个恒 true 的 `audit_alignment` 占位实现。

### 5.3 条款到断言的双向覆盖

每个 outcome、condition、prohibition 和 answer 条款必须映射到断言或明确的公开环境不变量；每个强制断言必须有反向的公开条款/规则依据。

`expected` 不能仅因为参考执行产生该值就成为用户要求。题目只要求预约成功时，不应额外冻结参考备注、辅助查询方法或未要求的历史字段。

没有可执行验收的条款不能留在 instruction 中假装支持。若题目需要修改，创建新 revision 全量重跑；不能在最终答案 schema 里悄悄增加约束。

### 5.4 副作用与过程

保留 witness/reference 的完整 before/after 及逐步状态证据。每个真实修改需要归属：用户目标、合法前置阶段或经公开规则说明的关联副作用。探索性/无关修改拒绝。

允许变化的实体范围按公开业务关系和冻结绑定规则计算，不从参考 diff 自动扩张。新建记录的 ID/计数器等维护字段只能按冻结的任务无关规则处理；不得使用一个“忽略所有 metadata”的宽泛掩码。

最终状态相同不代表过程中合法。`throughout` 禁止项必须通过 Host 逐次快照或已验证的原生历史检查；`before_event` 在事件前判断。资源分配前可用、分配后占用属于正常变化，不把前置条件错误地当作终态条件。

只在任务明确要求某个动作/审批/检查时检查其过程。普通辅助查询不能变成必须出现的事件。新建对象按实际业务身份绑定答案；不得要求复制参考执行的偶然 ID。

### 5.5 支持范围与拒绝语义

本次必须实现唯一对象选择、公开关系定位、结果断言、限定时点条件、无关状态保护和被公开要求的有界事件约束。任意多解优化、任意派生运算、未声明历史条件不属于支持范围。

`RepresentationBlocked` 用于某个候选确实超出这些已实现边界，不允许因为必交模块没写完就把所有候选都标成 blocked。

发现合法解被拒绝时记录 `VerifierDisputed`，隔离受影响候选并形成最小反例。修改验证器后，相关任务重新执行和准入，不原地改旧真值，不因希望任务更长而忽略短解。

## 6. 公开来源、策略和 S2/S3 一致性

### 6.1 参数与答案来源

保留 task literal、reset 和 prior observation 引用；补充指向实际公开 ToolSpec 中 enum/default 等明确常量的 `tool_schema_literal`，不得借此授权任意值。

为 Witness/Draft 声明的参数引用记录消费事件、参数 pointer、来源事件/字段、实体身份及类型。Host 验证来源先于消费、值和 schema 一致。后验发现两个值相等只能形成候选来源，不自动证明语义依赖。

Admission、probe、S3 也执行同一公开来源检查。来源分析无法支持某个确实需要计算的候选时归类为表示限制，不能声称它必然在猜隐藏信息。本文不实现任意算术表达式求解。

### 6.2 一个共享判定函数

新增或重构为唯一的 `evaluate_public_completion`：

```text
输入：Frozen TaskContract、公共 capture、原生状态证据、固定 validation profile
处理：生命周期完整性、公开参数/答案来源、答案 schema、结果/过程断言
输出：CompletionEvaluation + typed defect/violation
```

S2 filter、复杂度探测和 S3 都调用它，不能只共享 `evaluate_goal` 却在其他地方使用不同规则。S3 额外要求 post-reopen 状态可信；同一公共轨迹在健康相同状态下的任务判定必须一致。

任务或验证证据缺陷返回 typed defect；健康环境下未完成、错误对象/值等返回 policy violation。S2 候选阶段失败不直接转成 S3 reward=0。

### 6.3 角色策略与预算

定义 Host-owned `PolicyProfile`，包括角色、system prompt 原文和摘要、模型/route、driver、最大 provider turns、最大实际 tool calls、输出 token 上限、请求超时、基础设施重试上限。

将其编译进 PolicySpec/运行身份；实际模型请求、capture 和持久化字段必须相符。Host 检查实际 prompt 的摘要等于本次 profile，不再强制所有角色等于全局默认摘要；默认 profile 仍保持原默认行为。不得删除摘要校验或由 driver 私自注入未记录提示。

Efficient 提示只要求合法且高效完成；不包含最少/目标调用数、父任务或答案。标准、Witness、Efficient 的角色终止协议各自固定并记录，普通任务语义不随角色变化。

Tool-call 上限由 Host 在分派前执行，不能只靠 provider turns。SDK 重试与外层重试只有一层负责预算；默认禁用 SDK 隐式 retry，外层明确记录尝试。一次请求失败但未调用环境时可按上限重试；不因模型执行失败重新开始直到成功。

## 7. 三种扩展算子与诊断反馈

### 7.1 O1：前置条件扩展

识别父任务完成时依赖、而在原起点已具备的业务状态；找到现有公开操作能够建立它的合法早期情境；重新冻结完整目标并在 fresh 环境完成。

例如已分派请求的预约，扩展为未分派请求的人员选择、分派与预约。实际对象、资质和接口以 Release 为准。

不得先取消、弄坏或偷偷清空状态来制造工作。若合法直接接口能完成全部要求，则接受直接解；不能认定新增中间阶段必需。若 Need 明确规定不能绕过而 actor 允许绕过，记录环境反例。

### 7.2 O2：对象发现扩展

把直接提供的内部 ID 替换为明确、完整、可唯一解析的公开描述或实体关系。Scout 发现可行描述后，新 Witness 必须从零重新定位对象，不看父任务摘要。

先验证范围、成员完整性和唯一性；名称同义替换不自动算增长。合理的一次搜索返回目标时接受短解，不限制必须逐级调用查询接口。

语义签名必须保留“如何公开定义目标”，因此相同目标、相同最终 state diff 的 direct-ID 和 discovery 任务不被旧结构键直接合并。

### 7.3 O3：关联业务结果扩展

将局部操作扩展为同一用户意图下的关联结果，例如取消及公开规则允许的退款。新增结果必须是 Need 与真实工具支持的业务结果，不拼接无关查询。

涉及条件时，明确条件时点、实际分支和所需结果；不同起点各自生成可验证实例。候选使用当前支持的有限断言，不把未执行分支写成已验证事实。

### 7.4 算子共同验收

每个候选记录保留的终点、改变的起点/定位方式、新增条款、对应执行证据和依赖等级。只有业务连贯且有新增要求才算 capability growth；调用增长和依赖增长另外记录。

对 O1/O2 提供匹配任务对构造能力：直接 ID/公开发现 × 前置状态已具备/需建立。环境有合法起点时产生 2×2 对照；没有时记录 `MatchedStartUnavailable`，不能造假起点。对照任务也需独立 Witness、replay 和准入。

### 7.5 短解原因必须反馈下一轮

| 诊断 | 允许的反馈 | 禁止行为 |
|---|---|---|
| 起点已满足新增条件 | 选择其他合法 StartRef 或停止 O1 | 隐藏改库 |
| 一次合法查询已返回目标 | 标记无 discovery 长度增长，尝试其他有效关系或算子 | 禁止该查询 |
| 新增目标与原目标无关 | 拒绝候选并改变提案 | 只因够长而留下 |
| 正确短解被 verifier 拒绝 | 隔离、修复、重新验证 | 把拒绝当成依赖证据 |
| 原生业务能力缺失 | 生成 S1 GapRecord | 改 Prompt 假装接口存在 |
| 没找到新短解 | 记录探测结果和预算 | 宣称不可压缩 |

反馈为公开能力摘要与原因码，只进入 Proposer/调度器；不进入新 Witness、Admission 或 S3。反馈不能附带隐藏目标 ID 或已知正确答案。

## 8. 长度与依赖审计

`L_best_all` 为所有已经确认公开有效路线的最少真实 tool calls；`L_best_probe` 只在相同、冻结的探测协议内计算。没有成功路线时为 null，不用预算上限、0 或无穷大填充。

真实最短解 `L* <= L_best_all`。不得声称“已证明至少要 N 步”。父子比较绑定相同模型、提示、预算、试验次数，并报告成功次数及删步/探测成本。

计数单位是实际分派的公开工具调用；合法业务拒绝也计入。未分派的 JSON/参数错误另记。reset、protected read、reopen、evaluator 和其他候选的调用不计入求解长度。

完整实现以下协议：

- 生产审计：五次标准准入 + 两次独立高效求解；准入复用必须标注，不能当成独立无偏评估。
- 独立评估：冻结 corpus 后另跑未参与选择的相同预算批次。
- 局部删步：每个入选任务最多三个关键/可疑步骤，参数需从保留的公开信息重新绑定；不能从原 trace 补回被删步骤才给出的 ID。
- 等价路径：允许其他查询、合法批量操作与无顺序要求的动作交换。
- 匹配任务干预：按第 7.4 节检查增加的发现/前置负担与长度、成功率的关系。

E0 是工具描述或模型提出的候选依赖；E1 是公开身份/来源和实际状态支持的见证依赖；E2 是有效局部干预支持的依赖。E2 不是全局必要性证明。深度为已标注 E1/E2 局部 DAG 的最长链节点数；宽度另计，不把重复 N 个对象当作深度 N。

删步失败分开记录：公开参数无法绑定、业务前置条件失败、验证器争议、独立求解未找到路线。不得将它们全部标为 necessary=true。

长度档位固定为 1–4、5–8、9–15、16+；档位不是成功门槛。发现更短正确解只生成新 assessment/Corpus 版本，不更改 Task 真值。

## 9. 去重、谱系、有限递归与恢复

### 9.1 三层身份

1. `instance_fingerprint`：精确 Release/reset、冻结公开需求、selector、结果及答案契约。完全相同实例不重复发布。
2. `semantic_signature`：规范化条款、对象定位方式、条件/关系、业务结果、过程及答案语义。保留影响行动的常量与运算，不把所有数字都替换成同一种类型；不使用参考路线定义语义。
3. `root_family_id / leakage_group_id`：根与全部后代同组；不同根产生相同语义模板时合并泄漏分组。

旧 `_structure_id` 留作诊断特征，不单独拒绝 O2。文本改写、ID 参数化、实际能力变化分别统计。不确定是否同义时标记待审查，不能把所有相似任务直接删掉或把每次措辞变化都算新家族。

train/dev/test 按根/泄漏组分配，后代继承；已冻结 split 出现跨组碰撞时隔离冲突并形成新 manifest，不把测试内容用于调提示后继续声称 held-out。

### 9.2 前沿与调度

维护 CandidateArchive、ValidTaskPool、EvolutionFrontier，三者分离。短但合法任务保留；无增长不是模型失败。

实现可配置的有限搜索：默认三轮、最多 12 根、每父每轮两个候选、每根下一轮保留一个后代、总提案上限 72。覆盖不到某算子时使用调度配额，不扩大总预算。输入可减少时如实减少产出。

冷启动对 `(release, operator)` 均匀尝试。以后保留 20% 均匀探索，其余使用：

```text
p_growth = (1 + valid_growth_count) / (2 + completed_semantic_attempts)
weight = p_growth * max(coverage_deficit, positive_floor)
         / max(cost_ema, cost_floor)
```

预算单位固定为 provider token 或显式配置价格成本。基础设施故障计入真实成本，不计入语义失败分母。限制环境和家族占比，不按原始 trace 长度加权。

前沿排序：有效性 → 家族/环境约束 → 语义新颖与覆盖缺口 → 依赖增长 → 长度档位缺口 → 成本。同分使用 seed 和稳定 job ID 排序。

### 9.3 并发与恢复

每轮先冻结 Schedule，下一轮只消费本轮完整终态；不按 worker 到达顺序改变目标。身份不包含 worker 数。模型采样仍可能随机，不宣称同 seed 必然逐字重现。

每个 job、run、基础设施 attempt 有独立目录和身份；原子写入；已完成 job 不再执行；中断 job 保存 checkpoint，只有不能可信恢复的运行才建立新的基础设施 attempt。不得在半修改实例中开始一个“fresh”运行。

semantic failure 不重试到成功。新语义 revision 必须有真实变更理由、计入总提案预算、重新全链路验收；只换 ID 或措辞逃避失败记录不允许。

并发限制由统一调度器负责，使用每 Release 独立运行资源/串行实例操作，不能共享会话或混用 `state_events`。必须测试 1 worker 和多 worker 的同一固定调度语义。

## 10. 代码实现和完整接口

下列是必须落地的接口契约；模块可以合理合并，但职责、输入隔离、身份及验收不许省略。所有函数都要实现，不能留下伪代码或默认成功返回。

| 位置 | 必须工作 |
|---|---|
| `task_intent.py` | Intent/Start/Delta/公开绑定类型、严格 reader、冻结与 revision |
| `task_evolution.py` | O1/O2/O3、Proposer/Scout、反馈调度、有限前沿、campaign |
| `task_complexity.py` | probe、E1/E2、匹配任务、删步、长度和成本 |
| `task_quality_artifacts.py` | 谱系、签名、assessment、gap、schedule、报告的严格读写 |
| `task_proposal.py` | fixed intent 执行、角色终止协议、Extractor；复用工具内核 |
| `task_draft.py` | 新公共证据和结果契约；旧硬覆盖与业务目标分离 |
| `task_candidate.py` | Host binding、完整 replay、条款覆盖、副作用及语义签名 |
| `task_goal.py` | 第 5 节有限 AST、实体结果、过程时点、答案/状态一致性 |
| `task_admission.py` | 五次准入、共享 completion validation、严格 TaskPack 发布 |
| `public_agent.py`、`episodes.py` | 角色 PolicyProfile、实际提示、预算身份、capture 隔离 |
| `preparation_v3.py` | 复用真实运行时；必要的只读 schema 接口，不泄露给 policy |
| `episode_runtime_v2.py`、`episode_artifacts.py` 及 batch/source 模块 | 共享判定、post-reopen、当前格式、Corpus 接入和迁移冷读 |
| `scripts/run_s2_task_evolution.py` | doctor/run/resume/verify/compare CLI，薄封装 |
| 既有 S2/S3 campaign 脚本 | 输入子集、同内核策略与新 manifest 适配，不能保留失效的调用 |
| `PROJECT.md`、相关 Trellis spec、README | 同步唯一当前契约、真实命令和完成证据 |

核心函数的最低输入输出：

```text
resolve_inputs(config) -> ResolvedInputs
qualify_start(prepared, reset_config) -> StartRef
qualify_release_bindings(prepared, public_evidence) -> ReleaseBindingEvidence
propose_extension(public_seed, target, scout_profile) -> IntentProposal
freeze_intent(proposal, start_ref) -> IntentSpec
run_intent_witness(prepared, intent, profile, fresh_path) -> PublicWitness
extract_task_draft(intent, public_witness, public_schemas) -> TaskDraft
materialize_intent_candidate(prepared, intent, draft, witness, bindings)
    -> MaterializedCandidate
evaluate_public_completion(contract, capture, state_evidence, validation_profile)
    -> CompletionEvaluation
filter_candidate(prepared, candidate, admission_profile) -> TaskFilterEvidence
audit_task_complexity(prepared, candidate, protocol) -> ComplexityAssessment
seal_task_pack(candidate, admission, audit_refs) -> TaskPackArtifact
run_task_evolution_campaign(resolved_inputs, config) -> EvolutionCampaignManifest
verify_evolution_campaign(root, relocation_root) -> VerificationReport
```

保留现有公共 `run_task_episode`、`write_episode_bundle`、`read_episode_bundle` 的用途；按新类型同步参数、reader 和测试，不创建一个只为新算法绕开正式消费者的旁路。

SemanticAudit 必须真实调用独立审查或消费有来源的审核记录；缺审查不返回通过。可配置是否附加人工审计，但正常自动链路不能依赖每个任务都由用户手工补字段。自动审查不覆盖确定性失败，不冒充形式证明。

## 11. 格式切换和已有数据的处理

### 11.1 不静默改变旧格式语义

本次改变 Goal、公开来源和组合验收，使用明确的新格式：

```text
task-draft/2
candidate-task/3
goal-truth/2
public-task/2
task-pack/2
trusted-task-evidence/2
task-filter-evidence/2
```

新增 `s2-evolution-config/1`、`evolution-seeds/1`、`task-complexity-assessment/1`、`s2-evolution-campaign/1`。

Episode 需要记录共享验收证据/策略预算的字段，更新为 `episode-record/4`；公共输入或字段结构随之变化的 Training view 更新为 `training-episode-view/3`。严格同步 request、policy、batch/source manifest 的实际版本和 readers，并在仓库提交一张完整格式迁移表。不能只改常量而遗漏 reader 或身份预映像。

EnvironmentRelease/3 的 bytes 不变，不需要为了采样方法重建 20 个环境。S3 reward 的含义不变。

### 11.2 旧 69 个任务作为根种子，不自动升级真值

旧代码及旧 69 TaskPack、552 Episode 用固定 baseline checkout 的原 reader 做回归。新生产内核只写、读当前格式，不加隐式兼容 fallback。

实现一个离线 seed export 入口，显式使用基线解释器和旧 reader，导出严格的 `evolution-seeds/1`：旧任务公开 instruction、Release/reset 引用、来源摘要和泄漏分组，不导出答案、隐藏 Goal 或参考路线给 Proposer/Witness。

新内核接收该导出后重新 Witness、replay、准入；旧成功不能变成新准入证明。受保护 reset 配置仍由 Host 保存，公共视图不全量暴露。

当前规则下的 B0/B1 对照也重新验收，不能拿旧 verifier 统计直接对比新方法。旧产物不原地转换或重标。

### 11.3 身份与冷读

新 reader 必须重算文件摘要、语义/证据身份、policy 提示、来源、判定及公共投影。未知/旧格式在生产入口明确报错，并指向显式 baseline/export 工具；不得宽松忽略字段。

参考 before/after 保留为审计证据，不能成为所有合法解终态必须一致的隐式定义。assessment 独立更新不改变 TaskPack 业务真值；有验证争议时输出 exclusion manifest，不回写包。

## 12. CLI、配置和可恢复产物

### 12.1 使用 JSON 配置，不引入不必要依赖

新增 CLI 必须实现以下子命令，不把命令写进 README 却没有参数解析器：

```bash
uv run python scripts/run_s2_task_evolution.py doctor --config CONFIG.json
uv run python scripts/run_s2_task_evolution.py run --config RESOLVED.json
uv run python scripts/run_s2_task_evolution.py resume --campaign-root ROOT
uv run python scripts/run_s2_task_evolution.py verify --campaign-root ROOT --relocation-root NEW_ROOT
uv run python scripts/run_s2_task_evolution.py compare --config COMPARE.json
```

以上是本次要实现的命令，不是基线已经存在的命令。交付时替换为实测命令和实际路径。不得让用户再次手工拼每个模块的 Python 调用。

配置至少包含：

```text
format, baseline_commit, strategy, seed
inputs: baseline_checkout, s1_manifest, seed_manifest, release_ids
output_root
profiles: proposer, witness, extractor, reviewer, admission, efficient, s3
search: max_rounds, max_roots, candidates_per_parent, frontier_per_root,
        max_proposals, exploration_fraction, family/release_caps
budgets: max_tool_calls, max_provider_turns, max_output_tokens,
         request_timeout_seconds, infrastructure_retries
admission: valid_runs=5, minimum_passes=2
audit: efficient_runs=2, max_deletion_probes=3, heldout_probe_protocol
execution: release_workers, freeze_schedule_per_round
s3: rollouts_per_task
```

默认搜索预算按第 9 节；默认每次 48 tool calls、64 provider turns、基础设施 retry 2、每 Task 的 S3 rollout 2。输出 token/timeout 使用现有可用路线的明确配置，doctor 检查正值与真实 adapter 支持，不猜测服务能力。所有实际预算进入 config/profile 身份，不只是写配置却未执行。

API key 只来自当前进程环境或已有凭据管理，不写进 JSON、日志或 Git。默认 route 从实际已有配置读取，不假定容器中的 localhost 就是用户机器上的服务。

### 12.2 doctor 行为

检查 checkout 与未提交修改、Python/uv、锁定依赖、真实 manifest、Release/TaskPack 身份、路径存在和范围、原生可准备性、模型路由与 structured tool calling。成功时输出 `resolved-config.json`、`input-manifest.json` 和检查报告。

仓库报告中出现的本机产物路径只能作为发现候选。必须从实际存在的 record/manifest 核对 ID，不能拼出路径后直接当成存在。允许明确输入源目录进行受限发现，不扫描无关用户目录或猜测另一个版本。

缺凭据、缺旧产物、无法准备锁定环境分别输出具体问题；不得偷偷切换模型、重新生成环境或使用测试 fixture 通过 doctor。

### 12.3 目录和恢复

```text
campaign/
  config.json
  input-manifest.json
  format-manifest.json
  validation-profile.json
  release-bindings/
  starts/
  rounds/<round>/schedule.json
  rounds/<round>/jobs/<job>/
    proposal.json
    intent.json
    witness.public.json
    witness-state.trusted.json
    draft.json
    replay.trusted.json
    semantic-audit.json
    admission.trusted.json
    probes.trusted.json
    terminal.json
    attempts/<attempt>/...
  taskpacks/<pack_id>/...
  assessments/<assessment_id>.json
  lineage.json
  split-manifest.json
  corpus-manifest.json
  s3/episodes/<episode_id>/...
  verification-report.json
  evaluation-report.json
  completion-report.json
```

`resume` 复用已冻结 config/schedule，不接受改参数后续写同一 campaign。`verify` 在新根目录只携带声明的产物依赖，检查不能依赖原运行缓存或内存对象。

## 13. 自动测试清单

每项必须有对应自动测试；可合并测试文件，不可用文字说明替代。单元 fixture 允许手工构造，真实发布/效果证据必须来自原 Release 和真实 policy。

### 13.1 意图与来源

- I01：只完成冻结任务的一部分，不得缩小题目判成功。
- I02：Witness 收到父摘要、隐藏 ID 或 Scout 历史时，泄漏测试失败。
- I03：无法唯一定位，返回 BindingAmbiguous，不用 protected state 替 Agent 选。
- I04：未完成分页/范围枚举，不能声明唯一成员集。
- I05：冻结条件或答案字段变化，必须产生新身份并重新执行。
- I06：不支持的派生计算明确归入表示限制，不谎称隐藏信息。
- I07：同值不同实体/类型/时点不能自动绑定。
- I08：工具 schema 中实际公开 enum 可以作为明确来源；任意字符串不行。
- I09：任务初始已完成或答案已完整公开，不靠装饰查询制造非平凡。
- I10：Witness 终止 schema 不包含正式答案；done 不能单独触发成功。
- I11：Extractor 不能调用工具补证据或读取 protected state。
- I12：空审查器、恒 true 审查或缺 clause 映射不能通过。

### 13.2 原生执行与结果验证

- E01：Scout 修改不影响 Witness fresh reset。
- E02：非法 reset 返回 typed error，不作隐藏 setup。
- E03：真实多阶段 O1 路线和 fresh replay 状态一致。
- E04：直接接口合法绕过新增阶段，不强制步骤。
- E05：无关修改即使出现在参考 diff 中也拒绝。
- E06：close/reopen 不 reset，关键持久事实保持。
- E07：Episode 相互隔离，相同 reset/action 可重建。
- V01：list/inspect 等价发现后完成目标均通过。
- V02：其他实体同名字段不能替代目标事实。
- V03：状态正确但答案错误/指向其他对象失败。
- V04：只查询未完成最终修改失败。
- V05：独立动作合法交换顺序通过。
- V06：未支持的自由多解任务在发布前明确阻塞，不冻结参考选择。
- V07：新建对象合法 ID 改变时按业务身份和实际事实验收。
- V08：明确的审批等过程被绕过时失败。
- V09：误改后恢复但公开规则禁止中途修改时失败。
- V10：前置可用、终态占用的合法资源变化通过。
- V11：未公开的 required answer 字段不能混入 schema。
- V12：状态映射有歧义、不可信或与实体身份冲突时不得任选。

### 13.3 策略与共享验收

- P01：默认 prompt 行为不被高效角色修改。
- P02：高效 prompt 实际生效，摘要不一致时拒绝。
- P03：角色、模型、预算变化改变运行/策略身份。
- P04：tool-call 上限在 Host 分派前生效，不靠 turn 数替代。
- P05：SDK/外层重试不叠加突破预算，429 不记 policy failure。
- P06：相同健康 capture 在 S2、probe、S3 的公开来源和任务判定一致。
- P07：S3 post-reopen/证据故障优先返回 null，不因已满足目标而奖励 1。
- P08：运行中不能更改 policy/profile 或复用已关闭 driver。

### 13.4 算法、去重与复杂度

- O01/O02/O03：三个算子分别有可行增量与不可行/无关增量测试。
- O04：合法短解诊断反馈下一轮 Proposer，不泄漏给执行者。
- O05：默认起点已满足前置条件时不计 O1 增长。
- D01：direct-ID 与 discovery 不被旧结构键硬合并。
- D02：纯改写、换 ID、不同路线不夸大任务家族。
- D03：不同根相同模板合并 leakage group，不泄漏到 test。
- L01：参考 10 次、高效 4 次，长度更新为 4，Task 仍有效。
- L02：无成功 probe 时长度 null，不宣称不可压缩。
- L03：删步后补入隐藏旧 ID 的审计判无效。
- L04：固定工具匹配造成失败不能作为 E2 依赖。
- L05：不同预算/策略的最小值不能混进同协议比较。
- L06：匹配任务对保持声明不变项；无法重建起点时不给伪结果。
- L07：ForEach 宽度不当成依赖深度；E0 不混入 E1/E2。
- S01：冻结 schedule 的逻辑结果不随 worker 到达顺序改变。
- S02：恢复不重复完成 job，不覆盖失败，不复用半修改实例。
- S03：家族/环境份额及总预算在高产单一环境下仍生效。

### 13.5 产物和正式消费

- A01：五次仅一成功不发布，不追加第六次凑数。
- A02：2/5 不能覆盖已知隐藏条件或 verifier 争议。
- A03：短但合法不标成 Agent failure。
- A04：新验证版本不能原地修改旧包。
- A05：TaskPack 必须落盘再重载，之后通过真实 S3 消费。
- A06：Episode/training view 的原根与迁移冷读身份、reward、公共投影一致。
- A07：新旧格式明确区分，无静默 fallback。
- A08：S2 Witness、Admission、probe 不能直接冒充 S3 训练 Episode。
- A09：旧 seed exporter 不向新执行者泄漏 expected answer 或 Goal。
- A10：改变 assessment、worker 数或长度档位不改变任务语义身份。
- A11：配置缺产物/凭据时明确阻塞，不能自动用 fixture 补齐。

## 14. 真实运行、对照与最终验收

### 14.1 必须贯通的真实证据

先通过实际 manifest 校验当前 20 个 Release 与旧种子可读性。新算法运行支持任意已明确选择的 Release 子集，不硬编码必须复制成 20 条。

完整验收在至少三个实际可承载目标的 Release 上执行全部配置流程；记录所有候选。O1/O2/O3 各有真实被执行的提案，并报告各自准入/阻塞；至少两个算子在不同根上产生正式 TaskPack，至少一个家族出现第二次递进的已准入子任务。没有出现必须如实标为对应验收未满足，不用手工业务脚本替代算法。

每个正式入选 TaskPack 从磁盘重新加载后由 S3 执行配置数量的 rollout；所有成功、失败与 null 都落盘。每个成功 Episode 经真实 close/reopen 验收，全部密封产物本地及新根冷读一致。

人工指定一个任务只能用于定位集成问题，不能充当自动扩展成果；counter/mock 等测试不能充当真实场景完成证据。

### 14.2 对照实现包含在本次交付

四种策略共用当前环境、验证器、公开执行、成本记账与 reader：

| 策略 | 内容 |
|---|---|
| `direct_coverage` | 原有 shape/tool/outcome 导向的直接候选提出思想 |
| `intent_direct` | 完整业务意图优先，但不递归 |
| `evolution_without_shortcut_feedback` | 同样算子和递归，不用短解结果筛选/反馈 |
| `evolution` | 本文全部机制 |

独立最终 probe 对四组同等开放。对照同时报告等提案数与相同总 provider-token/调用预算；额外审计、失败和 reviewer 成本不能隐藏。旧粗去重影响可对同一批候选离线审计。

冻结 corpus 后另做独立标准/高效探测，不把用于 2/5 准入和选题的结果当作最终无偏效果。可用额外模型时添加未参与生成的策略，但未配置第二模型不能假称完成跨模型验证。

### 14.3 报告必须回答

1. 实際采样、见证、replay、准入、审计、发布、S3 各阶段有多少？失败责任是什么？
2. 新任务来自多少独立根/泄漏组、环境、算子和递进轮次？
3. `L_best_all`、固定协议 `L_best_probe`、成功次数、预算截断和 E1/E2 分布如何？
4. 哪些任务被短解压缩，哪些只是 verifier 假阴性，哪些新增依赖有匹配任务证据？
5. 每个有效任务/家族/中长任务用了多少真实成本？
6. 相同预算下是否比强的直接意图基线更有价值？
7. 代码、真实集成和算法效果分别达到什么状态？

按任务/根家族汇总，不把同一任务的八次 rollout 当八个独立任务。未经统一重算的旧均值/P95 不混用；532/530 等任何结果都从实际产物计算，不从本文或对话复制。

目标观察区间是有证据的 5–8 次及 9–15 次任务；没有达到不是理由去强制调用。可以得到“完整实现但效果未证实”的真实结论，不可捏造达标。

### 14.4 工程完成报告

`completion-report.json` 至少包含：

```text
implementation_commit
source/input/profile/verifier/format digests
requirement_to_code_and_test: R01..R10
unit/integration/type/lint test commands and outcomes
live campaign and output identities
relocation verification results
evaluation strategies and observed metrics
implementation_complete
live_validation_complete
evaluation_complete
effect_status
unresolved_defects
external_blockers
```

成功退出不能来自“脚本没抛异常”。verify 检查必需产物、终态、身份及 R01–R10 证据；缺项返回非成功验收状态。模型正常失败允许成为完整 campaign 的真实结果，不要求所有 rollout reward=1。

## 15. 给实施 AI 的执行指令

可以直接使用以下任务要求：

```text
以 s3-sft-trajectories 的已确认代码和真实产物为基线，完整实现
本文件定义的任务递进采样方法及 S3 接入。此次是一项完整交付，
不是讨论、原型或只实现某个阶段。

读取项目契约并激活对应实现任务；保护现有修改和旧产物。
依据本规格完成 R01–R10：三个算子、冻结意图、合法起点、
路径开放的有限结果验证、公开来源、共享 S2/probe/S3 判定、
高效策略、依赖与匹配任务审计、去重谱系、递归调度、恢复、
CLI、当前格式、自动测试、真实运行、迁移冷读和对照报告。

内部按依赖编写并持续集成，但不能在 canary、一个算子、
只生成 Candidate、单测通过或某个中间提交后宣布最终完成。
禁止 TODO、空实现、恒 true reviewer、伪产物、隐式兼容 fallback、
硬编码业务成功、隐藏 setup，以及重试到凑够成功。

遇到自己引入的代码/接口/格式问题，修复后继续完整验收；
候选不支持时保留具体 typed 失败，不能省略必交模块。
外部凭据、原产物或模型服务不可用时，给出确切阻塞、已完成证据
和可恢复运行入口，明确真实验收未完成，不使用 mock 冒充。

同步 PROJECT/DECISIONS/相关 Trellis spec/README 中实际改变的契约，
但不改变公开执行、真值隔离、无任务专属 Checker 和 reward 责任边界。
最终提交代码、测试、实际命令、完成报告与真实实验索引；
将代码实现完成、真实链路完成和算法效果分别报告。
```

这里允许分多个内部 commit 以便审查和恢复，但只有一个最终交付目标。用户不需要在每个中间检查点重新批准下一部分，也不需要自己把多个未接通模块再组装起来。

## 16. 静态审查证据索引

所有事实以本规格基线为准。实施时先核对实际 HEAD 差异，不能用以下旧行号直接覆盖新代码。

- `src/agent_env_foundry/task_proposal.py`：`sample_task_draft`、`_sampling_terminal`、`_validate_sampled_draft`。
- `src/agent_env_foundry/task_draft.py`：`SamplingTarget`、`PublicValueRef`、`AnswerProjection`。
- `src/agent_env_foundry/task_candidate.py`：`materialize_candidate`、`derive_argument_origins`、`_structure_id`。
- `src/agent_env_foundry/task_goal.py`：`evaluate_goal`、`_atom_matches`、If/ForEach 判定。
- `src/agent_env_foundry/task_admission.py`：五次准入、`_filter_attempt`、TaskPack reader。
- `src/agent_env_foundry/public_agent.py`：`PUBLIC_AGENT_PROMPT_DIGEST`、`ResponsesPolicyDriver`、`_capture`。
- `src/agent_env_foundry/episode_runtime_v2.py`：`run_task_episode`、post-reopen 与 reward。
- `src/agent_env_foundry/episode_artifacts.py`：record/public view、摘要和 paired cold reader。
- `src/agent_env_foundry/preparation_v3.py`：Release 原生准备、schemas 和状态回读。
- `scripts/run_s2_task_campaign.py`：输入约束、调度、去重和采样调用。
- `tests/test_task_sampling.py`、`tests/test_episode_runtime_v2.py`、相关 candidate/goal/artifact 测试：现有可注入测试设施，只能证明相应测试，不代替真实模型实验。

本文是基于已有代码的实施契约，不宣称递归扩展、意图生成或短解反馈为首次提出，也不将未运行的算法收益写成项目成果。
