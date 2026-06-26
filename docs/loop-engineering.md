# Harness 101: Loop Engineering...从 React 到 Orchestration

> 来源: QQ 长截图 `longCapture.png`。本文由分块 OCR 提取，图表与代码块可能需要人工复核。



## 1.前言

2026 年春节前在我们从头设计DeerFlow2.0时，曾认真考虑过一件当时觉得有点"反直觉"的事:与其为某一类任务费心写一个Skill，让模型每次照着这份说明书临场发挥，不如让AI直接为这个任务生成一段代码，把流程钉进脚本里，之后照着脚本跑。当时这个想法没有名字，我们也没敢把它推到台前。现在回头看，它其实有了名字-这正是Claude Code 之父Boris Cherny 近期推出的Dynamic Workflow，以及它背后那个更大的趋势:LoopEngineering.

让我把这件事说得更直白一些。Claude Code的作者Boris Cherny 在一次访谈里说过一句让笔者印象很深的话:

I don't prompt Claude anymore. I have loops running that prompt Claude and figuring out what to'op

by Boris Cherny

我已经不再亲自去 prompt Claude 了，我让一堆loop 跑着，由它们来 prompt Claude、替我决定下一步做什么。

同一时期，OpenClaw 之父Peter Steinberger 也表达过几乎一样的判断一一你不该再去prompt 你的codingagent，你该去设计那个替你 prompt agent 的loop。两个人，两个团队，指向的是同一个方向。Addy Osmani后来把这股潮流命名为Loop Engineering:你要做的不是写更好的 Prompt，而是设计一个能持续找活、派活、验收、记录、再决定下一步的loop，让这个loop 去戳 agent，而不是你自己。

你知道吗一一LoopEngineering正在成为社区热词?

它并不是某个人的个人口号。Boris Cherny(Claude Code)说"我的工作就是写loop"，Peter Steinberger(OpenClaw)说"你应该设计让 agent 被 prompt 的 loop"，Addy Osmani 把这股潮流总结成 LoopEngineering一一把找活、派活、验收、记账、决策这几件事固化成一个能自跑的系统。这更像是ClaudeCode、Codex这些团队不约而同走到的同一个路口。

Harness101:Overview

Plugin System LayerPluginsSkillsHooks

Session LayerSession StorageSession Manager

Orchestrator LayerWorkflowSub-agentAgent TeamHgeitTe

Tool LayerContext LayerPromptingCompressorBuilt-in Tools

Long-termMemoryShort-termMemoryMCP ToolsMCP

Agent Loop

Observability&EvalsLayer

Feedback LoopTracing & DebuggingEvals

在 Harness 101 这个系列里，通过上面这幅图笔者尝试告诉大家什么是我心中的 Harness，本文的主角上图中的Orchestrator Layer 层，即编排层。曾经我们在课程中提到的 Sub-agent、Agent Teams 就是最典型的多 Agent 编排方式，当然还有 DeerFlow 1.0 时代的 Supervisor-based 事先写死的 Multi-agent。

而Loop Engineering 是紧随其后的又一个趋势一一它不是笔者一个人的观察，而是Claude Code、Codex 这些团队当下正在共同走的方向。它和 Harness 的话题彼此呼应，但落点不太一样:Harness 关心的是agent 运行时周围的

UP那它到底解决什么问题？说白了，LoopEngineering 针对的是那种有明确阶段、有验收标准、还要被反复执行的任务。这类任务如果只靠一条 Prompt 或一次拼接失败T请回到中断处缓慢滚动屏幕在模型这一次的临场发挥上一一偶尔成功，但跑得多了就会发现它不稳、丢步骤、也没法复盘。Loop Engineering 做的事，就是把这样一条任务拆成环节、组织成一个能反复跑、看得见、还能从断点续上的loop，把流程的确定性从模型脑子里挪到结构里。但它不是万能药:面对一次性的、探索性的、边界还很模糊的任务，开一段对话、写一个Skill往往更轻、更灵活；搭一个loop 是有前期成本的，只有当任务会被反复执行、阶段足够清晰、又需要可审计时，这份成本才真正划算。

至于为什么是现在一一笔者觉得有三股力量凑到了一起。一是模型终于稳到可以被当成一个"可靠的被调用者"，你敢把一个子任务整段交给它；二是旗舰模型已经强到能把这段编排脚本现场生成出来，搭loop的门槛被拉低了;三是agenticcoding用得越来越多，大家陆续撞上了单次ReAct的天花板，自然会往"把流程固化下来、让它能反复跑"这个方向找出路。三者叠加，Loop Engineering 就从少数人的玩法，变成了一个摆在台面上的趋势。

这篇文章想做两件事。一是把Skill和Workflow的分野讲清楚一一它们常被混为一谈，但其实各管一段。二是把一个loop到底由什么构成讲清楚一一当我们说"设计一个loop"，到底是在设计什么。需要先说明的是，文中用来举例的DeerFlow3.0预计的API形式还是计划阶段的草样，随时可能改；笔者更想借它把背后的思路讲明白，而

## 2.从 ReAct 到 Orchestration

第一代 Agent 范式的名字叫ReAct。它的思路很优雅:让LLM 自己充当那个loop一一reason(想一步)、act(做一步)、observe(看结果)，再回到reason，如此往复，直到任务完成。流程不写在代码里，而是藏在模型每一轮推理的"脑子"里；工程师能做的，是再配一份Skill，当作交给模型的说明书，告诉它这类任务该怎么一步步走。

这套范式很好用，但放到要稳定交付的场景里，它的代价会慢慢显出来。最容易被提起的是loop 本身的维护成这套范式很好用，但放到要稳定交付的场景里，它的代价会慢慢显出来。最容易被提起的是loop本身的维护成本，但笔者觉得更要紧的，是它把整条流程的重量都压在了模型运行时的InstructionFollowing上。每跑一步，都要模型当场把Skill读懂、不跑偏、不漏步骤、不把顺序搞乱。一旦某一步理解偏了，后面整条链路就跟着步，都要模型当场把 Skill读懂、不跑偏、不漏步骤、不把顺序搞乱。一旦某一步理解偏了，后面整条链路就跟着歪下去，而且事后很难复盘一一你说不清它到底是在哪一步、为什么飘走的。于是这套流程不太可靠、不太能重放、也不太好审计；更现实的是，往往只有旗舰模型才勉强扛得住这种全程高强度的 Instruction Following。

先看ReAct自己充当loop 的样子一一模型一个人既做决策又做执行，流程在它脑子里转圈:

任务TASK

Reason 推理REASONING

自认为完成SELF-CHECK

Act 调用工具输出TooL USEOUTPUT

Observe 观察结果OBSERVATION

Orchestration走的是另一条路。它无需模型在运行时凭PromptInstructions或记忆维持流程，而是先用一个模型(通常是旗舰模型)，把整条流程一次性"编译"成一段WorkflowScript一一把每一步的Prompt、要喂进去的上下文，都写进这段代码里。之后真正执行的时候，确定性交给代码(阶段顺序、异步并行、同步等待、循环、逻辑分支由脚本表达)，判断力才留给被代码显式调用的LLM:

高等级 Agent负责生成负责设计流程High-level Agent

生成可复用的Workflow Script可复用的流程蓝图Reusable Workflow Script

固定 LoopFixed loopPhase 1

agent() 调用 LLMagent() calls LLM

Phase 2Phase

不通过 /retry不通过/retryassert() 不通过,assert()不通过，回到Phase2回到Phase 2assert() LLM判定assert()LLMevaluation

通过 / pass

Phase 3 / 输出Phase3/Output

这里有一件容易被忽略、却恰恰最关键的事:这段WorkflowScript本身就是模型生成的。它不是懂JavaScript的工程师手写死的静态pipeline，而是旗舰模型按"这次是什么任务"现场写出来的一一这正是DynamicWorkflow里"Dynamic"的由来。生成之后，它就是一段普通的、看得见摸得着的代码，用户随时可以手工改它、把它固化下来、之后反复复用。

把流程编译成代码，换来一个很实际的好处。脚本一旦生成，结构就固化进了代码本身，运行时不再需要模型靠强Instruction Following 去维持流程一一于是负责 orchestration 的那个 agent，以及它派出去干活的各个 sub-agent，都可以落到普通模型上。旗舰模型只在"生成这段脚本"时出场一次，之后的多次执行交给便宜、够用的普通模型。一句话概括:旗舰模型生成一次，普通模型执行多次。稳定性、灵活性、可复用性、可观测性大体都能保住，成本还顺手压了下来。

那么Loop Engineering 到底指什么？笔者比较认同 Boris Cherny 的讲法。他说自己几乎不再亲手给 Claude 写Prompt了，取而代之的是一些一直在跑的loop，由这些loop 去 prompt Claude。换句话说，工作的重心从"写好这一次的Prompt"，挪到了"设计那个会反复prompt agent 的循环"。这个循环负责把一类活儿从头管到尾:找活、把活拆开派给agent、验收产出、记录状态、决定下一步该干什么一一它能自己跑起来，人只在需要的时候搭把手。把这套围绕loop 来组织工作的工程实践叫作Loop Engineering，笔者觉得是贴切的。

要分清的是，Loop Engineering 是一种宏观的工程姿态，它并没有规定loop 必须长成什么样一一你可以用一个常驻进程加几个定时任务把它搭起来，也可以用别的形式。DynamicWorkflow只是其中一种具体形态:它把"单个loop"落成一段模型生成的脚本，用代码把骨架钉死、用［agent()把智能嵌进去。本文之所以拿它当主角，是因为它把前面那条"确定性交给代码、判断力交给模型"的思路表达得最干净。下一节就从它和Skill的对照说起。

## 3.Skill与DynamicWorkflow的分水岭

Skill和 Dynamic Workflow 常被放在一起谈，也常被混为一谈，但它们其实各管一段。把这条分野讲透，是这篇文章里笔者最想说清楚的一件事。

Skill是写给LLM读的自然语言指令。它是一份说明书，灵活、可组合，你可以把好几个Skill凑在一起让模型自己取用。代价是:执行路径每一次都由模型即兴决定一一这一回它先做A再做B，下一回可能顺序就变了，甚至漏掉中间一步。稳定性靠模型"自觉"，因此对运行时的InstructionFollowing要求很高，往往只有旗舰模型才跑得比较稳。

Dynamic Workflow 是一段确定性代码。流程被钉死在脚本里，阶段顺序、并行、循环、分支由代码决定，绝不会因为模型"今天状态不太好"就丢了某一步。而 LLM 只在被显式调用的地方介入一一比如［agent()负责一段需要因为模型"今天状态不太好"就丢了某一步。而LLM 只在被显式调用的地方介入一一比如「agent()负责一段需要智能的子任务，assert()负责一次需要判断的验收。代码管编排，模型管思考，各司其职。智能的子任务，［assert()负责一次需要判断的验收。代码管编排，模型管思考，各司其职。

两者的取舍，其实可以用一句话概括:Skill把结构交给模型，Workflow把结构交给代码。下面这张表把几个维度摊开对照:

维度SkillDynamicWorkflow

结构归属交给模型，运行时即兴决定路径交给代码，路径写死在脚本里

稳定性靠模型自觉，每次可能不同流程固化，绝不丢步骤

对运行时InstructionFollowing的要求很高，每步都要模型当场读懂照很低，结构已进代码，模型只管被调用处做

执行可用的模型档位往往得用旗舰模型才跑得稳orchestrationagent与sub-agent都能用普通模型

可复用，但每次执行结果会漂可复用性脚本可存档、可反复跑出可比结果

可观测性路径藏在模型脑子里，难审计阶段、日志显式可见，可重放可审计

适合场景探索性、边界模糊、要临场应变阶段清晰、有验收标准、要稳定交付

把这张表读完，本文的中心论点也就浮出来了。一旦把结构交给代码，运行时就不再需要模型一个人扛住整条流程-一于是orchestration agent 和它派出去的 sub-agent 都可以降级到普通模型，旗舰模型只在"生成这段脚本"时出场那一次。

不过笔者想强调，这并不是用代码去"取代"LLM。DynamicWorkflow的精妙之处，恰恰在于它用代码去"编排(Orchestration)"LLM一一确定的事情让代码稳稳地执行，需要智能和灵活的地方仍然原原本本地交还给模型它既要稳定，又要保住智能，两头都想要。

说到这里，笔者其实有点感慨:这正是我们做 DeerFlow 2.0 时隐约想要、却没能给它一个名字的东西。当时只觉得"让AI生成一段代码再照着跑"是个不太正经的念头，现在看来，它也许正是把灵活和稳定一起握住的那条缝。

## 4.一段深度研究Workflow

前面讲的都是抽象，现在把它落到地上。我们拿"深度研究"这个任务做例子一一给定一个用户问题，先快速理解，再拆成几个子课题并行去查，整合成稿，反复审改，最后做一次最终验证(终验)。这是一条阶段分明、又带验收标准的复杂任务，正适合用一段DynamicWorkflow来表达。

有一点想先说清楚:下面这段脚本不是哪位工程师坐下来一行行手写的，而是旗舰模型按"深度研究"这个任务现场生成的产物。在 DeerFlow 3.0的计划里，它出自一个叫workflow-creator 的 Skill一一你把任务描述给它，它把这条loop 写成代码交还给你。生成之后，这段脚本就是你的了:你可以手工改它、存档它、下次再原样跑一遍。

在读那一大段JavaScriptWorkflow脚本之前，先给大家看一张图建立骨架:

Quick Search 快速理解

Planning 拆子课题

Parallel Research 并行研究

Drafting 整合初稿

Review 审稿

assert判定需无实质意见修改则回炉

改写报告Final Validation 终验

交付报告

骨架就是这么简单:快搜、规划、并行研究、起草、审稿循环、终验。审稿那一环画了一条回头的边，由assert判定是否要回炉一一这是整条loop里唯一会循环的地方。

Workflow的API 很简单就这么几个:

代码块

核心LLM方法===

//用于创建子Agent3

```text
async agent(taskPrompt, verificationPrompt?)
```

4

//用于通过LLM做断言(判断)

```text
async assert(prompt): Promise<boolean>
```

8//paraLLeL()等API不在本文中详细阐述。91011用户交互与反馈方法=====12131/向用户发送当前进度通知1415phase(phaseName, desc)laseName,desc)161/向用户发送日志17log(text)18

让我们看一个DeerFlowDeepResearch的示例，全部由模型生成:

生成的 Workflow 脚本 (JavaScript)//phase和Log用于即时反馈当前阶段28phase('QuickSearch'，“快速理解用户问题和主题')29log('开始Quick Search')303132

```text
const quick = await agent()
你是DeerFlowDeepResearch的快速搜索员。33用户问题:${query}34请用webSearch完成一次QuickSearch，输出用户真正想问什么、35关键实体、核心争议点、后续适合深入的方向。363738phase('Planning'，‘生成可并行研究的子课题')394041

const plan = await agent("
你是DeerFlow研究规划者。42用户问题:${query}43Quick Search: ${quick}44请生成4-6个可并行研究的子课题，每个含title／goal／searchHint。454647phase('ParallelResearch'，‘并行执行子课题研究')4849

const tasks = []
50

for(const item of plan){
```

51log(启动子课题研究:${item.title})52tasks.push(agent(^53

## 4.1 agent()的两个参数

读这段脚本，最值得停下来看的是［agent())的签名:［agent(taskPrompt，verificationPrompt?)。

第一个参数是任务 prompt，告诉这次调用要干什么。

第二个可选参数verificationPrompt才是精妙所在，也是DeerFlow 3.0 独有的一一它是这次调用的"准出门"，包含用自然语言描述的验证(Rubrics)。agent())内部并不是搜一次就交差:它可以多轮搜索、反思、自我修正，每产出一版结果，就拿［verificationPrompt这把尺子把关，没过就接着改，直到通过这道门，才把结果返回给脚本。

这带来一个很干净的结果:worker的"重试"不写在脚本层，而是被内化进了agent())自身。你在外层看不到任何「for(retry...)的样板代码，因为"反复尝试直到合格"这件事，已经被那道门吞进调用内部了。脚本只管编排阶段，每个［agent()自己保证交出来的东西达标。

你知道吗—一LLM-as-a-Judge?

verificationPrompt)和［assert()〕干的是同一件事:用一个 LLM 去判断另一个LLM 的输出是否合格。这种"让模型当裁判"的做法在社区里叫 LLM-as-a-Judge。它的价值在于，给本来非确定的生成套上一道可编排的准出门一一生成是发散的，判定是收敛的，两者一配，loop才有了"过没过"这个清晰的二值信号。

## 4.2哪些是代码，哪些是模型

把这段脚本拆开看，会发现它泾渭分明地分成两类东西。

一类是确定性的代码。阶段的先后顺序(QuickSearch一定在Planning前面)、Promise.all把子课题一次性铺开并行、while(revision〈3)控制审改最多三轮、［if(!needsRevision)break的分支、最后的

```text
return report 一一这些都是普通 JS 控制流，跑一百遍是同一个走法，不依赖模型的临场发挥。
```

另一类是LLM 真正发挥的地方，全文只有两种调用:agent()和［assert()。前者负责干活一一搜索、规划、写作、改写；后者负责判断一一这版报告该不该回炉、终稿能不能交付。除此之外，模型不掺和流程控制。

这恰好就是Orchestration的形态:骨架是代码，血肉是模型。代码保证流程不丢步、不跑偏、可重放；模型在被显式调用的那几个点上贡献智能。两边各管一段，谁也不越界。

还有两个不起眼但有用的调用:phase()给每个阶段打标，log()记细粒度日志。它们不参与逻辑，纯粹是为了让用户实时知道这条loop此刻跑到哪了、在干什么。一个在后台默默跑的长任务，如果不向外吐进度，对用户就是个黑箱；phase和log就是把黑箱凿开的那两个窗口。

## 5. Workflow 的解剖

上一章那段深度研究脚本是个具体例子。把它的各个零件拆开，会发现它们其实是一套可以复用的通用结构。一个成熟的Dynamic Workflow，大致由八个部件构成。下面逐一过一遍，每讲一个，都对应回深度研究里它具体是哪一段。

Trigger (触发)什么把这条loop启动了。可以是定时(每天早上跑一遍行业简报)、事件(收到一封邮件就触发归档)、或者手动(用户点一下"开始研究")。深度研究的例子里，Trigger就是用户抛出【query)那一刻。它不在脚本主体里，但它决定了脚本何时被唤醒。

Planner(规划器):把一个大任务拆成可以分头处理的子任务。对应深度研究里的Planning阶段一一那个［agent())调用读完Quick Search，吐出 4-6个带title／goal／searchHint的子课题。没有这一步，后面的并行就无从谈起。

State (状态)loop跑到一半攒下来的东西，活在脚本的变量和外部存储里，而不是某一次对话的上下文窗口里。quick、plan、results、report、revision—一这些变量就是这条loop的State。把状态外部化是关键一笔:它不依赖单次对话，于是loop可以停、可以续、可以被另一个进程读取。

Workers(干活的)真正出力的agent())调用。深度研究里，那一组并行的子课题研究员就是Workers，每个worker领一个子课题，自己去搜、去整理、去交差。它们是这条loop的体力担当。

Evaluator (验收)把关的环节，这里有两层。第一层是每个agent()〕自带的[verificationPrompt]，也就是前面说的那道"准出门"，把单次调用的重试内化掉，worker不达标就不许返回。第二层是独立的[assert()一一它站在阶段与阶段之间，是更高一级的闸门，比如审稿后判断"该不该回炉"、终验时判断"能不能交付"。一层管单次调用的质量，一层管阶段流转的去留。

```text
while(revision〈3))的审改循环，和if(!needsRevision)break)的条件分支。这正是"loop"这个
Loop/Branch(循环与分

while(revision〈3))的审改循环，和[if(!needsRevision)break)的条件分支。这正是"loop"这个
```

支)词最字面的来源一一流程不是一条直线走到底，而是会在某些点上绕回去、或者岔开。深度研究的回炉重写，就发生在这里。发生在这里

Stop/Resume(停下与续能在中途停下，也能从断点接着跑。这是长任务的命脉。一条要跑半小时、调几十次模型的loop，如果中间断跑)了只能从头再来，那基本没法用。因为State已经外部化，停在哪一步、攒了哪些中间结果都记录在案，于是Resume才成为可能。

Repeatability(可重复)同一份脚本，可以重复地、可审计地跑出可比的结果。流程钉在代码里，每次走的都是同一条路径，差异只来自agent()那几个调用点。这让loop既能复盘，又能比较一一换个模型再跑一遍、改个prompt再跑一遍，结果是可对照的。

把这八个部件串成一张状态机，大概是这个样子:

并行干活拆子任务TriggerPlannerWorkers

定时/事件/手动

Loop回炉重试两层验收EvaluatorResume续跑条件分支

BranchStopResume可暂停/可恢复

注意:这里只是举了一个例子，DynamicWorkflow 的灵魂是"Dynamic"，即动态灵活。

图里特意把「stop/Resume画成一个能回到Workers 的状态:loop 可以在干活途中暂停，记下当下的 State，之后从断点处续跑，而不是推倒重来。这条"能回去"的边，是长任务能用起来的前提。

值得一提的是，这八个部件并非每条workflow都得集齐。简单的loop可能没有Branch、也用不上Resume；但Trigger、Workers、Evaluator 这几样几乎是标配。把它们当成一张检查表，设计自己的loop 时挨个问一遍"这一项我有没有想清楚"，往往就能少踩几个坑。

你知道吗一一Repeatability与确定性重放(deterministicreplay)？

白Dynamic Workflow 的可复现，本质是把 LLM 的非确定性全部收敛到了［agent()这几个调用点上。骨架是确定的代码，发散只发生在被显式标记的地方，于是整条loop 可以被审计、被复现一一你能精确指架是确定的代码，发散只发生在被显式标记的地方，于是整条loop可以被审计、被复现一一你能精确指出"不一样"是从哪一次调用开始的。这种"确定性重放"正是纯 Skill 范式难以保证的:Skill 的执行路径每次出"不一样"是从哪一次调用开始的。这种"确定性重放"正是纯Skill范式难以保证的:Skill的执行路径每次都由模型即兴决定，连"走了哪几步"都未必能复盘。

## 6.让人留在Loop里

一个loop一旦跑起来，最省心的设想是:它自己埋头跑完，最后把结果端上来。但稍微长一点的任务，这个设想都很危险一一它意味着无人值守的loop，也在无人值守地犯错。自动化不等于失控，真正可用的workflow，得让人能随时看见它、也随时插得进手。需要先说明一下，下面提到的askUserQuestion()与drainInbox()都是 DeerFlow 3.0 计划里的形式，还曰

会随实现调整，这里更多是想把"人怎么留在loop里"这件事讲清楚。

把人留在loop里，笔者觉得可以拆成两个方向。

第一个方向是workflow主动找人。脚本跑到关键岔路时，与其替用户做主，不如停下来问一句。askUserQuestion())就是干这个的一一比如深度研究到了规划阶段，几个子课题的取舍方向不明，或者视频生成里角色设定有两版风格难以定夺，workflow 可以在这里挂起，把选项摆给用户，等到答复再往下走。这就是典型的Human-in-the-loop:人不是事后验收，而是在loop 内部的决策点上被请进来。

第二个方向是用户主动介入。有些循环一跑就是十几分钟，用户中途想纠个偏，总不能等它跑完。办法是让脚本在循环里时不时调一次［drainInbox()，拉一下用户发来的 steering 消息一一如果有，就把这条新指令并进当前上下文，及时调整；如果没有，就接着跑。这样用户不必盯着，但只要想说话，loop 在下一个检查点就能听见。

这两个方向，配合前面提到的phase()／log()实时上报，才算完整:phase()／log()让用户看得见进度，［askUserQuestion()〕／drainInbox()〕让用户插得上手。看得见又插得上，loop 才不是个黑箱。

下面这张时序图把三方的配合画了出来一一workflow 跑到关键点用askUserQuestion等用户答复，循环里则用drainInbox顺手拉取用户的steering消息。

WorkflowAgentUser

phase/log上报进度

askUserQuestion关键岔路提问

按选择派活

loop

[长循环每轮]

干活
