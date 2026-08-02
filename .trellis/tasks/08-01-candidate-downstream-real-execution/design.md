# Candidate 后置节点真实执行设计

## 两条不混淆的执行线

```text
同一份 Candidate 源码
        |
        +-- 本机执行闭包 --> Integration --> ReleaseAssurance --> Observability --> Package --> Registry
        |                         (唯一进程执行边界；无 namespace sandbox)
        |
        +-- 正式 WorkGraph/Registry provenance gate --> 接受或明确拒绝
                                      (绝不将诊断 Artifact 升格为 WorkCommit)
```

本机线验证后置代码的实际行为和节点间输入投影。正式线验证生产控制面不会绕过
provenance。二者都是真实执行，但回答不同的问题。

## 本机执行边界

现有 `IsolationPolicy` 将路径投影和 bwrap 绑定耦合。本任务删除该实现和所有兼容分支，
以唯一的本机 process execution boundary 保留由 framework 决定的 cwd、Candidate source
snapshot、解释器、临时状态布局、超时和输出采集，直接启动子进程。

它不得：

- 改写 Candidate 源码；
- 把宿主目录形状泄漏给 Code Agent；
- 伪造 subprocess 成功、跳过 `uv sync`、测试或 runtime protocol。

本机执行边界是 `EnvironmentJudge`、Doctor 与 Consumer 的唯一默认路径。它不再生成或依赖
`/workspace`、`/state`、`/opt/agent-world/*` 这类 namespace 内路径。

## 顺序和门槛

1. 固定源码 digest、Design/WorldSpec、ImplementationContract、Verifier projection 与
   Candidate manifest。
2. 运行新的本机 Integration；它是 Candidate 后置链的第一个真正运行节点。
3. 对输入 Verifier 进行绑定验证；只有它不匹配或缺失时才启动新的 Verifier node。
4. 使用同一闭包运行新的本机 ReleaseAssurance。
5. 运行 Observability closure，并将其与前述实际 attempt 绑定。
6. 由 Package 节点构造可移动闭包；对 Registry 执行实际 publication/preflight。
7. 另行运行正式 provenance gate；若缺少 WorkCommit 则保留拒绝，不能用 diagnostic adapter
   修补。

每一站只在上一站 `ready/pass/committed` 后前进。若出现一个新终态，停止链路、读取安全
报告，按五个 lens 与时序角色扮演定位首个偏差。

## 失败归因

| 证据 | 归属 | 下一步 |
| --- | --- | --- |
| 本机命令/cwd/path 不能启动 | framework local adapter | 修 adapter 并重跑同一节点 |
| Candidate 自己的公开测试、协议或材料化失败 | Candidate-visible build feedback | 形成精确反馈或记录需要真正 Candidate repair |
| Verifier bytes 与 Candidate Design 不匹配 | frozen closure/provenance | 重新选择正确绑定，不改 Candidate |
| Direct LLM 零 Provider event | Provider/profile/adapter | 单独 route probe/retry，不阻塞确定性本机节点的归因 |
| Registry 拒绝诊断 Candidate provenance | 正确生产门禁 | 记录拒绝；等待正式 WorkCommit |

## 观察

Provider 调用每 2–3 分钟只读观察；本机子进程同样每约 2–3 分钟检查实际输出、进程和
终态。约五分钟没有实际进展时检查 liveness/transport/child-process 状态，不静默等待数小时。
