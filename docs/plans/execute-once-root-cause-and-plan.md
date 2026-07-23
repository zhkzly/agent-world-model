# 计划：让环境“真正执行一次” — 根因诊断 + 修复方案（交接文档）

> 状态（2026-07-23）：历史 run 的只读事实摘录，不是当前 HEAD 的根因或修复授权。
> E1--E4 可以排除部分历史候选故障，但不足以证明当前 Supervisor、隔离 profile 或
> Integration 路径正确；任何后续改动须按
> [refactor-plan-calibration.md](refactor-plan-calibration.md) 重新在当前 HEAD 复现并归类。

> 本文档是交给执行 AI 的**行动计划**。它基于对一次**真实失败 run** 的只读诊断
> （`.agent-world-live/workgraph-hotel-v2/state/runs/run-5eb0ddffdf7843b1b2f3b6efeb82e501-af0e5fe53ee418dc`）
> 与只读复现，未对代码做任何修改。执行者必须先读“0. 北极星与铁律”，任何一步若与之冲突则停止并回报。

## 0. 北极星与铁律（不可违反）

- **北极星**：把一句自然语言需求变成**真能确定性执行**的 Agent RL 训练环境；状态转移由生成代码拥有，
  反馈**不撒谎**（绝不用 LLM 文本 / mock / template / 固定回放 / 固定环境 id / 伪成功）。
- **“放松校验让它过” = DRIFT**，禁止。修复不得以削弱 gate 的判定强度为手段。
- 每一处重大修改都必须**先阐述**：改什么 / 为什么（对应哪条真实证据或 bad case）/ 如何符合北极星 / 影响面；
  对齐后再动代码。不要跳过阐述直接实现。
- 不读、不外泄任何机密：`.agent-world-live/**` 内的 `auth.json`、`codex-home/**`、
  `.producer-provenance.key`、provider transcript、sealed/private verifier 数据一律不得进入诊断、日志、artifact、Registry。

## 1. 已确认的事实（证据链，执行者应先自行复现确认）

E1. 管线**到达 integration**，候选工程完整生成：该 run 下存在
    `builder/.agent-runtime/workspace/candidate/candidate/{runtime,materializer,self_check,spec}.py`、
    `verifier/batches/{00,01}` 等。→ 不是卡在 Research/Design。

E2. telemetry（`state/telemetry/telemetry.sqlite`）按 component/node/status 统计：
    research 116 passed / 51 failed（失败几乎全是 `ResearchProviderError`+SSL，外部抖动，可重试）；
    designer/design 仅 1 passed，其余 failed/error/budget_exhausted；judge/integration 2 次且都 `integration_not_ready`。

E3. integration 的 repair 披露（`builder/.agent-runtime/workspace/inputs/repair-disclosure-2.json`）三条同因：
    `runtime_protocol` / `task_materialization` = **“runtime exited without a response”**，
    `clean_deployment` = 因前序 integration 失败未跑探针。

E4. **候选环境本身可用**：把 `candidate/` 单独裸跑
    `python -m candidate.runtime`，发 handshake **29ms 得到正确 JSON 响应，进程存活**。
    → “exited without a response” 不是生成质量问题。
