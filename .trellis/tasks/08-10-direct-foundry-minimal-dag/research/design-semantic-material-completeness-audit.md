# Research: DesignGraph semantic material completeness audit

- Query: 对 /home/kelong/pycodes/foundry-direct-graph 的 DesignGraph 做只读 semantic identity 审计；逐个覆盖 design.py 中的 GraphRunner.execute / _direct_commit 调用点，区分 exact dependency closure、模型/operation projection 与 semantic implementation identity。
- Scope: internal；静态、只读；唯一写入为本记录。
- Date: 2026-08-11

## Files Found

- /home/kelong/pycodes/foundry-direct-graph/AGENTS.md：项目工作边界与 source-of-truth 指向。
- /home/kelong/pycodes/foundry-direct-graph/docs/agent-world-environment-generation.zh.md：源事实；规定实际 prompt/input/output model/skill/profile 与 acceptance identity 的边界。
- /home/kelong/pycodes/foundry-direct-graph/docs/direct-rewrite-execution-map.zh.md：从 ArtifactRef 到最小 projection、operation、validate、commit 的执行图。
- .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md、design.md、implement.md、node-contracts.md：当前任务的节点、端口、投影与契约。
- /home/kelong/pycodes/foundry-direct-graph/agent_world/design.py：本审计的各节点 handler 与 Direct 提交点。
- /home/kelong/pycodes/foundry-direct-graph/agent_world/graph.py：GraphRunner 的 input resolve、semantic revision、WorkRecord 写入。
- /home/kelong/pycodes/foundry-direct-graph/agent_world/invocation.py：Agent/Direct 的实际 prompt 包装与 Runtime Skill 记录。
- /home/kelong/pycodes/foundry-direct-graph/agent_world/contracts.py：EnvironmentRequest.create 的 canonical need digest。
- /home/kelong/pycodes/foundry-direct-graph/tests/test_graph_contracts.py、tests/test_design_semantics.py：已有 semantic-revision 与 correction 行为测试。

## Identity Boundary Used

本审计不把三种关系混成一个 hash：

1. Exact dependency closure：一个 node 为运行、验证或输出因果性而必须绑定的最小 ArtifactRef 集。它必须准确；无关 shard 不能仅因方便而成为 dependency/input ref。
2. Semantic projection identity：operation、Direct model、Agent model 或 compiler 实际读取的、不可变且会改变语义结果的 projection，加上实际 prompt/profile/output/validator/compiler 的实现身份。改变其中任一项，应改变 semantic/acceptance revision。
3. Execution / repair policy：route、凭证、transport、retry、timeout、fallback、observation、local correction 次数等。它们可以影响执行或恢复，但不应被伪装成回答/接受语义身份。

GraphRunner 目前在 graph.py:463-596 将 resolved input refs 同时写入 WorkRecord.input_refs 与 dependency_refs；这不能证明两种关系天然相等。当前任务的局部修复应收紧不必要的 shard bindings，而不是把所有 refs 塞进 semantic_material。

## Findings

### Shared evidence

- graph.py:442-461 的 semantic revision 已绑定 node id、owner、execution kind、input/output contract、effective projection digest、prompt_id、route、Agent Runtime Skill digest 和 local_corrections。有效 projection 的 canonical digest 来自调用方给出的 semantic_material。
- graph.py:463-596 先 resolve refs、再计算 revision、再运行 operation；因此“某 ref 是 dependency”本身不会使 revision 改变，除非它对应的实际 projection/implementation identity 被放进 material。
- design.py:574-617 的 _direct_commit 对所有 Direct node 统一提交 effective_projection、output_shape、prompt_identity。它正确地让 Direct projection 进入 revision，但没有自动覆盖调用方遗漏的字段，也不表示 prompt literal/compiler identity 本身已被内容绑定。
- source-of-truth（docs/agent-world-environment-generation.zh.md:111-113）要求绑定实际 effective prompt/input、output model、Agent Runtime Skill（Direct 无 Skill）及 profile materialization；backend index（.trellis/spec/agent_world/backend/index.md:576-680）同时区分 acceptance identity 与 repair policy。

### Per-node pass / gap matrix

| Node / shard | Current exact dependency closure | Operation / model / compiler 实际看到的 projection 或外部不可变值 | Current semantic material and variation result | Decision |
| --- | --- | --- | --- | --- |
| research_plan | request_ref | Agent workspace request.json 中的 request.need；compiler 只读取 model result。 | request_digest + output shape；在 EnvironmentRequest.create 的 canonical-invariant 下，need 改变会改变 digest/revision。GraphRunner 还绑定 research-world-evidence 的 Runtime Skill digest。 | Pass（见全局 implementation-identity caveat）。 |
| research_acquire | plan_ref | Agent 读取 plan.queries；operation 还读取 research search/reader endpoint 与 credential，并以远端 body 生成 source content digest。 | plan_ref.digest + output shape；query/plan 改变会改变 revision。endpoint、credential、retry/fallback 是执行定义/来源 provenance，不是 semantic implementation identity，不能把 secret 或 transport 放进 material。 | Pass；不声称它证明外部内容 freshness。 |
| research_synthesis | request_ref、plan_ref、acquire_ref（同一 acquire artifact 供 sources/citations 两端口） | evidence.json 包含 raw need、plan.questions_to_resolve、citation index/url/text；compiler 读取 sources、citation cardinality 与 citation catalog。 | request digest、citation index/url/content_digest、output shape；遗漏 questions_to_resolve。只变 question 而 request/sources 不变时，workspace 会变但 revision 不变。 | Gap G1。 |
| world_architecture（Direct） | request_ref、evidence_ref；coverage 是同一 evidence ref 的第二逻辑端口 | Direct projection 为 need、evidence claims/conflicts/gaps、citation catalog；compiler 读取 citation set。 | _direct_commit 的 effective_projection 覆盖全部上述实际输入；相应变化改变 revision。 | Pass。 |
| shared_tool_semantics（每个 Direct group shard） | architecture_ref、evidence_ref | projection 为该 group、该 group 的 ToolSurface、catalog；compiler closure 读取同一 group/member 集。 | group/tool/catalog 都进入 effective_projection；同一 shard 的实际输入变化改变 revision。 | Pass。 |
| tool_semantics（每个 Direct tool shard） | 应为 architecture_ref、evidence_ref、该 tool 实际选择的一个 shared shard；当前实现传入全部 shared_refs。 | Direct projection/compile 仅读取当前 tool、frozen bindings、selected shared contract、citation catalog。 | projection identity 完整：selected contract 或 binding 改变会改变 revision。无关 shared shard 不在 projection，不应加入 material。 | Semantic pass；exact dependency closure gap G5a（当前过宽）。 |
| world_rules（Direct） | architecture_ref、全部 tool_refs | projection 为 architecture、全部 tool semantics；compiler 为重复/冲突检查也读取全部 tool local rules。 | effective_projection 覆盖其真实读取；任一 tool/rule 变化改变 revision。 | Pass。 |
| curriculum_plan（Direct） | architecture_ref、rules_ref、evidence_ref | projection 为 architecture、world rules、citation catalog；compiler 读取 architecture/evidence citations。 | effective_projection 覆盖其真实读取；变化改变 revision。 | Pass。 |
| task_requirement（每个 Direct family shard） | 应为 architecture_ref、rules_ref、curriculum_ref、evidence_ref、该 family 的 tool refs；当前实现传入全部 tool_refs。 | projection 仅含当前 family/difficulty/catalog/rules、family.tool_indexes 选择的 tools、citations/reachability；compiler 读取 family、architecture、citations。 | projection identity 对已选择 tools 完整；无关 tool 不在模型或 compiler projection，不能因被过宽绑定而加入 material。 | Semantic pass；exact dependency closure gap G5b（当前过宽）。 |
| modeling_gate | evidence_ref、architecture_ref、shared_refs、tool_refs、rules_ref、curriculum_ref、task_refs | 这是无 Direct model 的 compiler node；build design/recipes/config 时实际读取 evidence、architecture、shared contracts、tool semantics、rules、curriculum、task requirements。 | 仅含 architecture、shared refs、rules、curriculum、task refs、output shape；遗漏 evidence_ref 和 tool_refs。只变 evidence 或 tool semantic 时可改变 compiler result，但 revision 不变。 | Gap G2。 |

所有 Direct rows 共同经过 design.py:574-617 的 _direct_commit。因此“effective_projection 是否完整”与“Direct prompt/compiler 的实现身份是否被绑定”是两件事：前者除上述 G1/G2 外为 pass；后者仍受 G4 约束。

### Confirmed gaps: smallest field repair and regression

#### G1 — research_synthesis misses the plan question projection

Evidence:

- design.py:798-809 将 plan.questions_to_resolve 写入 Agent 可见 evidence workspace。
- design.py:901-912 的 semantic_material 仅有 request/citation/output-shape，未包含该字段。

Smallest repair:

- 在该现有 semantic_material map 加入 exactly questions_to_resolve: plan.questions_to_resolve；若需要缩短存储，加入该已渲染 questions field 的 canonical digest，不能改为整份 plan ref 的代理 hash。
- 不增加 node、端口、schema 或泛化反射。

Regression:

- 在 tests/test_design_semantics.py 增加一组仅改变 plan.questions_to_resolve、保持 request 与 acquired sources/citations 不变的 synthesis fixture。
- 断言捕获到的 workspace questions 改变，且对应 WorkRecord.semantic_revision_digest 改变。

#### G2 — modeling_gate omits evidence and tool semantics actually read by its compiler

Evidence:

- design.py:2017-2055 在 graph.execute 前以 evidence、architecture、shared、tools 组装 recipes/initial config。
- design.py:2103-2111 正确把 evidence/tool refs 作为 graph inputs；但 2115-2122 的 material 没有 evidence_ref.digest 或 tool_refs。
- graph.py:442-461 只 hash supplied material/projection declaration，不会从 dependency refs 推导它们。

Smallest repair:

- 在 modeling_gate 的现有 semantic_material 加入 exactly evidence: evidence_ref.digest。
- 加入 exactly tool_semantics: [ref.digest for ref in tool_refs]，保留既有确定顺序。
- 不需要把未读取的 ref、retry、route、credential 或 provider 信息加入 material。

Regression:

- 扩展 tests/test_design_semantics.py 现有 modeling-gate semantic test：保持其余输入相同，分别只替换 committed evidence ref、只替换一个 committed tool ref；两次均断言 gate WorkRecord.semantic_revision_digest 改变。
- 保留现有“shared ref 改变会改变 revision”的覆盖，三种输入分别验证。

#### G3 — local_corrections is recovery policy, not semantic implementation identity

Evidence:

- graph.py:442-461 将 node.local_corrections 放进 semantic declaration。
- graph.py:673-681 只把它用于是否允许本地 correction attempt。
- tests/test_graph_contracts.py:931-1001 已断言同一 work 的 correction attempt 保持相同 semantic revision。
- backend index:576-595 明确把 repair policy/epoch 与 acceptance identity 分开；更改 recovery cap 不应使已接受输出失效。

Smallest repair:

- 从 graph.py 的 semantic declaration 移除 local_corrections；仍将其保留在 NodeSpec/attempt policy。
- 不将 correction text 加入 semantic material；它是同一 work 的 repair evidence，而不是新的目标语义。

Regression:

- 在 tests/test_graph_contracts.py 构造仅 local_corrections 值不同的两个等价 NodeSpec，断言 semantic_revision 相同。
- 保留并运行已有 correction-attempt 同 revision 测试，以证明恢复行为未被删除。

#### G4 — prompt/profile/compiler implementation identity is only manually named, not actually bound

Evidence:

- design.py:515-562 的 _agent_json/_direct_json 包含会改变模型所见 instruction/system message 的 literal template；invocation.py:239-280 还执行 Agent prompt wrapper 和 mounted-skill reporting。
- _direct_commit（design.py:574-617）只放入 node.prompt_id；graph.py:442-461 使用的是这个 name，而不是实际 template/profile/compiler revision。
- GraphRunner 对 Agent Runtime Skill source digest 的绑定是 pass；Direct 没有 Runtime Skill 是正确的。缺口是 template/profile materialization 与 compiler/validator implementation identity，而不是应当给 Direct 补一个 Skill。

Smallest repair:

- 对当前已有 handler 使用显式、局部的 prompt_template_revision（精确对应其 system/instruction template 与 profile materialization revision），并在既有 material/declaration 中绑定它；可让现有 prompt_id 直接成为该冻结 revision/digest。
- 对当前 compiler/validator handler 增加一个显式的 compiler_or_validator_revision 到其既有 material/acceptance record；只在该 handler 的语义/接受逻辑变化时调整。
- 这不是自动扫描源码、generic framework、全局 schema 或新增 node；它只是为当前已存在的 literal/template/handler 给出可审计的闭合身份字段。

Regression:

- 用不调用真实模型的 graph fixture，分别只改变一项 local prompt-template revision、profile-materialization revision、compiler/validator revision；断言 revision 改变。
- 对 Agent fixture 同时断言 Runtime Skill digest 仍被保留；对 Direct fixture 断言没有虚构 Skill field。

#### G5a/G5b — two Direct shard families bind unrelated artifacts as dependencies

Evidence:

- tool_semantics：design.py:1400-1515 只读取 selected shared contract；1524-1528 却传入全部 shared_refs。
- task_requirement：design.py:1856-1951 只读取 family.tool_indexes 选择的 tool projections；1960-1966 却传入全部 tool_refs。
- node-contracts.md:55-62 及 backend index:1318-1390 要求 input disclosure/dependency 与因果关系显式且最小，不可由“同一 GraphRunner 输入列表”偷换为全部相关项。

Smallest repair:

- tool_semantics：在调用点由当前 tool 的 selected shared contract 找回对应 ArtifactRef，只绑定该一个 ref；没有 selected contract 时不提供 optional shared-tools port。
- task_requirement：按 family.tool_indexes 保序映射到对应 tool ArtifactRef，只绑定这些 refs。
- 不修改 semantic_material 以“补偿”此问题；投影本来只含 selected values。也不建议在本审计范围内改造 GraphRunner 的全局 input_refs/dependency_refs 数据模型。

Regression:

- 对 tool shard：只改变无关 shared shard，断言该 tool WorkRecord 不含它的 input/dependency ref 且 semantic revision 不变；改变 selected shard 时两项按契约变化。
- 对 task family shard：只改变非 family.tool_indexes 的 tool，断言不在 ref closure 且 semantic revision 不变；改变已选择 tool 时按契约变化。

### Passes and deliberate non-inclusions

- research_plan 的 request_digest、research_acquire 的 plan_ref.digest，分别覆盖其实际 need/query projection（EnvironmentRequest.create 的 canonical digest 不变量成立时）。
- research_acquire 的 endpoint、reader URL、credential、HTTP retry/fallback 不是要写入 semantic material 的“遗漏字段”。它们是执行定义、provenance 或 secret；远端内容本身以产出的 content digest/citation identity 进入下游。
- world_architecture、shared_tool_semantics、world_rules、curriculum_plan 的实际 projection 与 compiler read set 已由现有 effective_projection 覆盖。
- tool/task Direct shard 的 semantic material 不需要、也不应该包含无关 shared/tool refs；其问题是过宽 dependency closure，不是 material 缺字段。
- Runtime Skill digest 已是 Agent node implementation identity 的一部分；Direct node 没有 mounted Runtime Skill，不能因形式对称而添加。

### Reviewer-finding check and rebuttal

请求中提到的“最新 final whole-diff block”在允许读取的任务文档与 research 文档中未找到；implement.jsonl/check.jsonl 受研究角色隔离，未读取。因此本记录不声称看到了或复述了两条未提供的 reviewer 原文。

代码和合同足以反驳下列两种若被提出的结论：

1. “每个 tool_semantics shard 必须把全部 shared_refs 加入 semantic_material”是错误的。design.py:1510-1515 的 Direct projection 仅有 selected shared contract，compiler 也只读取 selected contract（1409-1508）；把无关 shard hash 进去会将 dependency closure 与 semantic projection identity 混同。正确修复是 G5a 收紧 refs。
2. “每个 task_requirement shard 必须把全部 tool_refs 加入 semantic_material”是错误的。design.py:1943-1951 只向模型暴露 family.tool_indexes 选择的 tools，compiler 读取的也是 family/architecture/citations（1856-1941）；合同要求 family 的 actor/tool scope，而非全局 tool 集。正确修复是 G5b 收紧 refs。

若 reviewer 原意是“当前 shard ref closure 有问题”，该方向成立但措辞应反转：现状不是遗漏全部 refs，而是绑定了无关 refs。

## External References

- 未进行外部网络检索或真实模型调用。
- 任务材料提及 openai-codex==0.144.4 与 uv 0.11.29；本审计未独立验证这些版本，且它们不构成当前节点的 semantic material。

## Related Specs

- docs/agent-world-environment-generation.zh.md:111-113：实际 prompt/input/output/skill/profile 与接受身份边界。
- docs/direct-rewrite-execution-map.zh.md:53-60：精确 ArtifactRef -> 最小 executor projection -> operation -> validate -> commit。
- .trellis/spec/agent_world/backend/index.md:576-595：definition/acceptance/repair identity 分层。
- .trellis/spec/agent_world/backend/index.md:601-680：Direct 与 Agent 的 prompt/Skill/profile 边界。
- .trellis/spec/agent_world/backend/index.md:1318-1390：causal dependency 与 input disclosure 的区分。
- .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:55-62：input refs 与 dependency refs 不可隐式推断。

## Caveats / Not Found

- 本结论是静态代码/合同审计；没有运行测试、真实 LLM、网络检索或 git 操作。
- 未访问 implement.jsonl/check.jsonl，故没有消费角色隔离外的 whole-diff/reviewer block；上文 reviewer rebuttal 仅针对可由代码证明的两类可能错误主张。
- G1 的 citation/content identity 假定 research_acquire 正常路径用 content digest 对其传给 synthesis 的 staged text 保持完整性。没有主张已证明任意手工构造、digest 与 text 不一致的 mutable sources 也安全；这属于输入完整性 hardening，未将其扩大为本次 semantic-material 修复范围。
- G4 的判定以 source-of-truth 要求“实际”实现身份为准。若存在未展示且受强制执行的变更控制，能保证每个 literal/template/compiler 变化同步递增现有 prompt_id/acceptance revision，则需以该证据重新评估；当前可见代码未验证此不变量。
