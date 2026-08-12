# 通用调研：Context、Prompt、Skills、Feedback、Observe、Retry 与 Memory

- 日期：2026-08-12
- 范围：通用 LLM / Agent 系统，不绑定某个项目、框架或模型供应商。
- 方法：优先使用官方工程文档与原始论文；项目代码和单次运行只作为应用案例，
  不作为通用结论的唯一证据。

## 一句话结论

可靠的 LLM / Agent 系统不是靠一条巨型提示词，而是让代码选择最小充分的上下文，
让 Prompt 清楚表达当前愿望，让 Skill 提供稳定可复用的做事方法，让工具和校验器产生
可信事实，再把这些事实编译成下一条可执行的用户 Feedback；模型负责重新提出结果，
代码负责验证、次数、路由、提交和停止。

## 概念边界

| 概念 | 回答的问题 | 典型生命周期 | 不应承担的职责 |
| --- | --- | --- | --- |
| Context engineering | 本次推理究竟让模型看到什么、按什么顺序看到 | 每次推理重新选择 | 把所有历史、文档和日志全部塞入 |
| Prompt engineering | 如何用角色、措辞、结构和示例表达当前任务 | 节点/版本稳定部分 + 当前输入 | 代替确定性校验、权限和发布逻辑 |
| Skill | 某类 Agent 如何反复完成一项工作的稳定程序 | 版本化、跨任务复用 | 保存当前任务、当前错误或会话日志 |
| Tool contract | Agent 能调用什么，参数、返回值和副作用是什么 | 能力版本 | 把本次工具结果写进长期说明 |
| Tool observation | 这次调用实际发生了什么 | 当前 Agent loop | 获得更高指令权威或发布权 |
| Feedback | 同一任务中，下一条更具体的用户修改愿望 | 一次 correction turn | 原样转储异常、自己批准重试或放宽验收 |
| Observe | 面向人和调试者的安全事实投影 | 运行后/运行中查询 | 自动成为模型输入、路由或 Gate |
| Artifact | 已验证、可追溯的跨节点事实 | 持久、不可变版本 | 保存未验证的对话和原始秘密 |
| Memory | 经筛选后值得跨会话复用的经验 | 长期、可失效 | 充当当前运行事实或权威 Artifact |
| Resource | 可检索的完整资料或证据来源 | 长期、按需读取 | 自动注入每次上下文 |

## 1. Context engineering：选择状态，而不是堆积文本

Context 是一次推理时真正进入模型的信息总和，包括稳定指令、当前请求、选中的历史消息、
工具定义、工具结果、检索片段、工作区内容和 Feedback。Prompt 只是其中一部分。

一个实用的选择准则是：只保留完成当前决定所需的最小充分、高信号信息。这里的“最小”
不等于越短越好，而是：

1. 当前目标和不可变约束完整；
2. 输入只投影当前节点所需字段；
3. 输出合同完整且可操作；
4. 证据与指令明确分隔；
5. 不重复相同规则，不预载无关下游状态；
6. 长资料通过索引、引用和渐进披露按需读取；
7. 对进入与未进入上下文的内容都能测试。

长上下文容量不是自动的质量提升。研究显示，信息位置、干扰项和长度本身都会影响模型使用
信息的能力。因此应先改善选择、排序和去重，再考虑摘要、缓存或更大的上下文窗口。

## 2. Prompt engineering：把任务写成可执行愿望

高质量 Prompt 通常分成稳定角色与动态任务两部分：

- 稳定部分：角色、权威边界、允许的能力、输出模式、不变量；
- 动态部分：本次目标、冻结输入、相关证据、成功条件和完整输出合同。

基本规则：

1. 用消息角色表达权威层级，不把外部材料、工具结果或上一份答案写成更高层指令；
2. 每条重要规则只表达一次，并放在模型使用它之前；
3. 输出要求具体到字段、基数、闭集、引用和禁止项，但机械 ID、哈希、大小、排序等交给代码；
4. 例子只在它确实消除歧义时使用，并测试它不会锚定错误模式；
5. Prompt 应像代码一样版本化，并以真实失败建立 eval；
6. 不用任意短超时或输出 token 上限掩盖输入/合同问题；物理 Provider 终态应被观察和归因。

## 3. Structured output：SDK envelope 固定，不代表业务对象正确

官方 SDK 可以把 Provider 的外层响应解析成类型化对象，但消息内容是否符合业务 JSON Schema
是另一层合同：

- JSON mode 主要保证“输出是 JSON”，不保证字段和语义符合 Schema；
- Structured Outputs / schema parsing 在支持时更强，但仍需处理拒绝、截断、空结果和不支持能力；
- SDK transport retry、业务 semantic correction 和 workflow repair 必须分开；
- 最终业务对象仍需由代码做 closed-shape、引用、类型和语义校验。

因此“使用官方 SDK”和“使用严格输出合同”是互补关系，不是替代关系。

## 4. Skills：稳定程序，不是第二份 Prompt 或会话记忆

Skill 适用于有重复步骤、领域方法、工具纪律或可复用脚本的 Agent 工作。推荐渐进披露：

1. 先暴露名称和简介，让 Agent 判断相关性；
2. 需要时读取完整 `SKILL.md`；
3. 再按需读取 references、templates 或执行 scripts。

Skill 中适合保存：步骤、检查清单、工具选择、失败处理、输入输出约定和可复用脚本。
不适合保存：当前用户请求、当前失败、秘密、原始日志、运行时 Artifact、临时 Provider 配置。

Direct LLM 一般不需要 Skill；只有需要工具、工作区探索或多步自主执行时才使用 Agent + Skill。
确定性工作优先写成代码或脚本，而不是要求模型每次重新计算。

## 5. Feedback：下一条用户愿望

Feedback 的核心定义是：第一次结果被可信观察拒绝后，系统在同一任务对话中向同一个 LLM
或 Agent 提出的下一条、更具体、可执行的用户修改愿望。

它不是：

- 再发一次完全相同的冷请求；
- 原始异常、栈、测试日志或 validator JSON 的转储；
- “请再试一次”“更认真一点”之类无事实自我反思；
- patch/diff 指令（当节点合同要求完整对象时）；
- 让模型决定 retry、route、budget、Gate 或 release；
- 修改 Skill 来承载当前一次失败。

最小有效 Feedback 有四部分：

1. 连续性：任务、冻结输入和完整输出合同不变；
2. 事实：上一结果哪里不符合，期望条件是什么；
3. 动作：返回完整 replacement，不是补丁、解释或道歉；
4. 自检：修复所有同类位置，并重新检查完整结果。

示意：

```text
Same task. Keep the original objective, frozen input, and complete output
contract unchanged. The previous answer was rejected for these observed
reasons: <safe actionable issues>. Return one complete replacement, not a
patch or explanation. Fix every matching occurrence and recheck the whole
replacement before answering.
```

反馈质量依赖“外部可验证事实”。Self-Refine 等工作表明模型可利用自然语言反馈迭代；CRITIC、
编译器和测试反馈研究进一步表明外部工具事实通常比无依据的自我反思更可靠。与此同时，已有研究
也说明纯内在自我纠错可能无效或退化，因此不能把“模型会反思”当成验收。

是否保留上一份 rejected answer 应显式决定：若保留，它只能作为当前未提交对话中的低权威
assistant 数据，不能进入 Artifact、Skill、Observe 或长期 Memory；Feedback 不再重复粘贴它。
若答案可能含注入文本、秘密、巨大噪声或不完整副作用，则应省略或终止，而不是盲目续聊。

## 6. Observe、工具事实与 Feedback 的关系

三个对象来自相同运行，但用途不同：

```text
真实执行 / 工具 / validator
            |
            +--> 完整内部证据与 Artifact
            +--> Observe：给人看的安全“发生了什么”
            +--> Feedback：给当前模型的“下一步请怎样改”
```

Observe 不应自动整段注入模型。Feedback 只选择其中与当前提案因果相关、可安全披露、可执行的
事实；完整证据仍由框架保存，用于审计、进展比较和最终验收。

## 7. 四种循环必须分开

| 循环 | 何时发生 | 输入 | 谁决定停止 |
| --- | --- | --- | --- |
| Agent tool continuation | Agent 尚在一次工具任务内 | typed tool observation | Agent 在能力范围内行动，框架有硬边界 |
| Node-local correction | 未提交提案被校验拒绝 | 原任务 + rejected proposal（可选）+ Feedback | 框架的显式次数与 no-progress 规则 |
| Transport replay/fallback | 连接、限流或可安全重放的基础设施失败 | 相同语义请求，不产生 Feedback | 框架 transport policy |
| Workflow repair | 已形成 terminal Finding，需要新 Artifact revision | 诊断、修复计划和因果后缀 | workflow policy / 人类风险边界 |

默认一次初始生成加一次 correction 通常最容易审计。更多 correction 只有在明确策略、预算和
可证明进展时才合理；相同归一化错误集应停止。次数越多不是上下文工程越好，往往说明输入合同、
Skill、工具事实或 validator Feedback 仍有问题。

## 8. 错误分类与可修复条件

只有同时满足以下条件才适合 semantic Feedback：

1. 确实存在可归因于模型/Agent 的未提交输出；
2. 原目标、输入和输出合同仍然有效；
3. 问题位于输出，而非凭证、权限、网络、框架 bug 或未知副作用；
4. 可以给出安全、具体、可执行的事实；
5. correction 额度仍在。

认证、权限、不可重放副作用、未知状态和框架缺陷通常应 terminal 或 needs-human。格式错误能否
纠正取决于是否有完整、非截断、可归因的模型输出和明确格式要求，不能笼统把所有 parse error
都当成可重试，也不能笼统全部归因于 Provider。

## 9. Memory 与 Resource：结论和依据分开

长期知识至少分两类：

- Memory：短小、稳定、经过验证的经验、偏好或决策，例如“Feedback 是下一条用户愿望”。
- Resource：可按需检索的完整文档、论文、网页和带引用的综述，回答“为什么”。

从一次运行到长期知识应有 promotion gate：先有真实观察和复核，再提炼适用范围、反例和失效
条件。不要自动保存原始 Prompt、模型输出、完整 transcript、秘密或单次 run 状态。

Memory/Resource retrieval 也只是候选上下文。检索内容必须保持为低权威证据，由当前任务重新
验证；它不能替代当前 Artifact、工具结果、validator、Judge 或用户指令。

## 10. 最小实现检查表

设计一个 LLM/Agent 节点前，逐项回答：

1. 节点为何必须是普通函数、Direct LLM，还是 tool-enabled Agent？
2. 输入中哪些是冻结事实，哪些只是证据，哪些明确排除？
3. 初始 Prompt 的稳定角色、动态愿望和完整输出合同分别是什么？
4. 若是 Agent，唯一必要 Skill 和工具是什么？能否用代码替代机械工作？
5. 输出由什么 deterministic compiler/validator 验证？
6. 哪些失败有足够事实可生成 Feedback？Feedback 是否要求完整 replacement？
7. transport replay、local correction 和 workflow repair 是否明确分开？
8. correction 次数、no-progress 和 terminal 条件是否由代码拥有？
9. Observe 暴露什么安全事实，哪些内容明确不暴露？
10. 用哪个真实失败、确定性测试和真实边界试验证明有效？

如果上述问题可以用现有函数、一个消息 renderer、一个 Skill bundle 和一个校验器回答，就没有
理由先增加 context manager、feedback service、validator Agent、向量数据库、通用 RAG 层或复杂
记忆层级。

## 主要来源

### 官方工程资料

- OpenAI Prompt engineering：
  https://developers.openai.com/api/docs/guides/prompt-engineering
- OpenAI Conversation state：
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI Structured Outputs：
  https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Skills：
  https://developers.openai.com/api/docs/guides/tools-skills
- OpenAI Model Spec：
  https://model-spec.openai.com/2025-10-27.html
- Anthropic Context engineering：
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic Agent Skills：
  https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Anthropic Building effective agents：
  https://www.anthropic.com/engineering/building-effective-agents
- Anthropic Agent evals：
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

### 原始论文

- Self-Refine：https://arxiv.org/abs/2303.17651
- CRITIC：https://arxiv.org/abs/2305.11738
- Training Language Models with Language Feedback：
  https://arxiv.org/abs/2204.14146
- Large Language Models Cannot Self-Correct Reasoning Yet：
  https://arxiv.org/abs/2310.01798
- VRpilot（编译器/测试反馈）：https://arxiv.org/abs/2405.15690
- ReAct：https://arxiv.org/abs/2210.03629
- The Instruction Hierarchy：https://arxiv.org/abs/2404.13208
- Indirect Prompt Injection：https://arxiv.org/abs/2302.12173
- Lost in the Middle：https://arxiv.org/abs/2307.03172
- Context Length Alone Hurts：https://arxiv.org/abs/2510.05381
- Reflexion：https://arxiv.org/abs/2303.11366
- MemGPT：https://arxiv.org/abs/2310.08560

## 证据边界

- “外部事实反馈通常优于空泛自我反思”有多项论文和工程案例支持，但不保证每个模型、每个任务
  都会改善；必须用目标模型和真实节点做 eval。
- “保留上一份 rejected answer”是可用的对话模式，不是普适最优；是否保留取决于安全、长度、
  Provider 能力和实际对照试验。
- 长期 Memory、向量检索、反思日志和多轮 evaluator-optimizer 对长任务可能有价值，但不是每个
  节点的默认依赖，也不是修复一次格式/合同失败的最小方案。
