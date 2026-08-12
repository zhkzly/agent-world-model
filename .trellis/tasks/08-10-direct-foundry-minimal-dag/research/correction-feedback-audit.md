# Research: correction-feedback-audit

- Query: Independent audit of the current bounded correction path, its input/contract delivery, and safe live second-attempt evidence before another full Direct E2E.
- Scope: internal
- Date: 2026-08-12

## Findings

### 1. First validation frontier

**It usually raises only the first issue; it does not aggregate all safely discoverable same-object issues.** `GraphRunner.execute` holds one `CorrectionPacket`, calls one compiler, catches one `NodeExecutionError`, and immediately either schedules the second call or fails (`agent_world/graph.py:486-515`). Its failed validation record retains only a code (`agent_world/graph.py:735-742`). There is no issue-list/aggregate validation artifact on the rejected path.

The reviewed compilers are fail-fast too: Design helpers raise at the first bad text/object/array (`agent_world/design.py:110-155`), the architecture compiler evaluates fields and collections sequentially (`agent_world/design.py:958-1207`), and Candidate compilers raise from their first failed shape/bound/path check (`agent_world/candidate.py:361-466`, `469-538`). Focused tests cover one packet and two calls, not a multiple-independent-issue frontier (`tests/test_graph_contracts.py:768-814`, `881-919`).

That conflicts with the source requirement to aggregate a shard's safe issues at one validation frontier, retain every field-level issue, and compact only the correction brief (`docs/agent-world-environment-generation.zh.md:340-344`, `428-445`, `601-603`).

### 2. Second-invocation input and feedback guarantee

**No, not as the full conjunctive guarantee in the question.** There are two narrower guarantees:

- For Direct Design nodes, the second call reuses the closure-captured `visible_projection` and `shape` and sends the one packet in the same JSON envelope (`agent_world/design.py:599-641`, `561-582`). `CorrectionPacket` itself has the exact four safe fields: `code`, `path`, `violated_condition`, and `expected_category` (`agent_world/contracts.py:95-101`).
- Design and Candidate Agent wrappers append that same serialized packet to the instruction (`agent_world/design.py:540-555`; `agent_world/candidate.py:708-746`). Candidate inputs are materialized before the call and removed only after successful candidate compilation (`agent_world/candidate.py:810-846`, `857-886`).

But the code does not establish that every rendered `shape`/Agent instruction is a complete executable mirror of every compiler rule. `shape` is a separately authored string parameter to `_direct_commit`, while the compiler is an independent callable (`agent_world/design.py:599-637`). More concretely, the Candidate Agent instructions name only a draft and broad outcome (`agent_world/candidate.py:821-824`, `871-875`, `1036-1039`) while their compilers impose closed nested shapes, bounds, and path safety (`agent_world/candidate.py:361-538`, `1044-1150`). A second call therefore receives the exact packet for the *first surfaced issue*, but is not proven to receive a complete original output contract nor the other safely discoverable blockers.

### 3. Safe live second-attempt classification

The classifications below use only persisted safe paths/conditions and terminal states, never raw provider content. “Not classifiable” means the stored second-attempt packet was insufficient to distinguish A from B under the documented `path+code+condition+expected` key.

| Safe record | Classification | Evidence |
| --- | --- | --- |
| `shared-tool-to-first-tool-live-proof.md` | **A -> success** | Luna received one bounded `$.error_policy` correction and committed the SharedTool work; the immediate ToolSemantics consumer then passed (`:12-18`). |
| `diagnosis-direct-proof-5-undisclosed-architecture-contract.md` | **A -> B** | Attempt 1 was the environment-name identifier issue; attempt 2 was the distinct tool-name identifier issue (`:13-21`). |
| `world-architecture-text-bound-live-proof.md` | **A -> A** | Attempt 2 failed the same path and exact text-bound condition after the stated correction (`:11-17`). |
| `diagnosis-shared-tool-ordering-bound-too-small.md` | **A -> A** | Both healthy calls failed the same `$.ordering` bound; call two received the exact bound (`:10-16`). |
| `diagnosis-shared-tool-policy-bound-too-small.md` | **A -> A** | Both healthy calls failed only `$.error_policy` at the disclosed bound, including the complete replacement after the exact correction (`:11-15`). |
| `diagnosis-design-text-correction-collapsed.md` | **A -> A** | Two Luna calls failed `$.ordering` with the same persisted correction text (`:19-33`). |
| `diagnosis-direct-proof-3-spark-contract.md`; `diagnosis-direct-proof-4-terminal-feedback.md` | **Not classifiable** | They preserve first-attempt feedback and a second terminal code, but not the exact terminal packet/path/condition needed to label B (`proof-3:14-33`; `proof-4:12-30`). |
| `diagnosis-direct-non-json-feedback-gap.md` | **No second attempt** | It records one non-JSON invocation; the separate replay was not an authorized correction attempt (`:20-35`). |

No other persisted safe record establishes an additional A -> success second attempt. One-attempt/zero-correction proofs were not relabelled as correction successes.

### 4. Can perfect Luna instruction following still fail?

**Yes.** A model can satisfy the one visible packet perfectly and still lose the only correction turn to an independent blocker that fail-fast validation withheld. The safe A -> B record above is direct evidence of that failure mode. It can also follow an exact condition and still be unable to satisfy a bad declared compactness bound; the stored A -> A records for 160- and 280-code-point SharedTool limits demonstrate that category.

This does **not** claim that the historical bounds remain wrong today: later one-call and bounded-correction proof records show some repaired bounds can pass. It establishes that model adherence alone cannot compensate for incomplete feedback or a producer/consumer contract that has not been proven congruent.

### 5. Immediate recommendation and minimality

**Do not start the next full E2E until the fail-fast same-object correction frontier has a reviewed repair plan.** The required defect is narrow: the existing compiler-to-`GraphRunner` handoff can expose only one issue, even though the one-correction policy requires the first attempt to disclose the whole safely discoverable local frontier.

The smallest repair hypothesis is confined to the current node transaction:

- At the existing Design/Candidate compiler boundary, collect a bounded tuple of independently safe `code/path/violated_condition/expected_category` issues for the one submitted object instead of throwing on the first one.
- Persist that complete tuple with the first failed attempt, then render one bounded, deterministic compact brief for the existing second call. Preserve frozen input/output projection, the same node/shard, `local_corrections=1`, and the two-call ceiling.
- If a condition cannot be safely disclosed or the set cannot form an understandable local brief, terminal-block it; do not send a blind retry.
- Add one focused two-invalid-fields test proving that call two sees both safe blockers, retains no raw provider data, and cannot produce a third call.

This explicitly **rejects a parallel generic feedback framework**: no new scheduler, graph nodes, repair policy, retry budget, provider fallback, generic prompt/schema platform, Agent Skill, candidate repair flow, or public Observe surface. The reviewed plan must use only the smallest source-of-truth-compatible aggregate/persistence needed for this one node transaction; it must not turn the repair into a new generic control plane. The plan must nevertheless pass the normal diagnosis -> critic gate because it changes validation and feedback behavior.

#### Diagnosis record

- Expected outcome: one parsed proposal is validated once as a same-object frontier; the sole authorized correction receives every safely actionable blocker for a complete replacement (`docs/agent-world-environment-generation.zh.md:384-389`, `428-445`).
- Observed boundary: `GraphRunner.execute` carries one exception packet only; reviewed compilers stop at the first exception (`agent_world/graph.py:486-515`; `agent_world/design.py:110-155`; `agent_world/candidate.py:361-466`).
- First causal deviation: the deterministic compiler/feedback handoff, not Luna, routing, an Agent Skill, or the candidate process.
- Five lenses: project-execution view **supported** by the task-local safe records; Direct effective input **supported only for frozen projection + one packet**; Direct no-Skill invariant **supported**; code/execution boundary **weakened** by fail-fast collection; feedback/observability **weakened** because B is unavailable before the bound is spent.
- Rejected strategies: increase correction count, retry/model-switch, loosen validators/bounds, truncate output, convert Direct to Agent, or add a broad feedback subsystem.
- Smallest proof after an approved repair: a real isolated Direct node with two independent safe invalidities in attempt 1, followed by Observe; stop at its first new terminal. What remains unproven: complete Design, Candidate, Integration, Judge, Registry, and E2E.

### 6. Role-separation audit

The correction path is mostly correctly separated; the issue is framework feedback completeness, not role confusion.

- **Hardcoded framework:** Node ownership/execution types and the ordinal-one correction authority are fixed in `agent_world/graph.py:119-327` and `462-595`; compilers, Work/Finding persistence, and release decisions remain code-owned. This matches the execution-map framework responsibilities (`docs/direct-rewrite-execution-map.zh.md:66-88`) and the source-of-truth authority split (`docs/agent-world-environment-generation.zh.md:374-389`).
- **Direct LLM:** World semantic nodes are `direct_llm` (`agent_world/graph.py:152-211`). The wrapper explicitly supplies no tools, Skill, workspace, or release authority and carries only node/input/shape/packet (`agent_world/design.py:561-582`), matching the Direct boundary (`docs/direct-rewrite-execution-map.zh.md:20-24`, `114-115`).
- **Tool-enabled Agent:** Research, BuildPlan, VerifierIntent, and CandidateBuild are `agent` nodes with an explicit Skill; CandidateBuild alone is writable (`agent_world/graph.py:119-130`, `232-266`; `agent_world/candidate.py:708-730`, `815-877`). Its text response remains advisory and framework-compiled, not an authority transfer.
- **Untrusted candidate:** Integration and Judge are `candidate_process` nodes (`agent_world/graph.py:268-283`). Framework prepares/runs the candidate and validates integration/judge output (`agent_world/candidate.py:955-1020`, `1242-1341`); the candidate cannot decide repair, validation, or release.

No role-separation change is recommended for this correction defect.

### 7. Mechanical `response_format` repair remains separate

Keep the mechanical Direct JSON-object request repair closed and separate. Its diagnosis places it before semantic compilation: a non-JSON response is a framework/output-format terminal, not a semantic correction (`research/diagnosis-direct-json-response-contract-missing.md:15-35`; `research/direct-json-response-format-probe.md:8-20`). The current audit begins only after a parsed object reaches the compiler. There is no conflict and no basis here to reopen `response_format`, parser behavior, route choice, or retry policy.

## Evidence Index

### Files found

- `AGENTS.md` — project authority and cross-layer gate requirements.
- `docs/agent-world-environment-generation.zh.md` — controlling validation-frontier, exact-feedback, one-correction, and role rules.
- `docs/direct-rewrite-execution-map.zh.md` — derived Direct/Agent/framework/candidate role map.
- `agent_world/graph.py` — fixed graph declarations and the two-attempt correction loop.
- `agent_world/contracts.py` — safe correction fields and execution-kind types.
- `agent_world/design.py` — Direct/Agent wrappers and Design compilers.
- `agent_world/candidate.py` — Agent wrappers, Candidate compilers, integration, and Judge execution.
- `tests/test_graph_contracts.py`, `tests/test_design_semantics.py`, `tests/test_direct_release.py` — focused correction coverage.
- The seven live/diagnosis records cited in finding 3 — safe persisted evidence for classification only.

### Related specs and references

- `.trellis/spec/agent_world/backend/index.md` — backend/InvocationBackend and live-proof rules.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — Direct versus Agent context and feedback attribution.
- `.trellis/spec/guides/foundry-product-alignment.md` — product-goal guardrails.
- External references: none; this was an internal code-and-safe-record audit.

## Caveats / Not Found

- The task exposes only `implement.jsonl` and `check.jsonl`; research-role isolation forbids opening either. I used `task.json` plus the relevant persisted safe diagnosis/live-proof records instead.
- No product code, plan, task JSONL/PAC, provider invocation, live retry, test run, or git operation was performed.
- Historical classifications describe the documented runs at their time; they do not assert that later bound/prompt repairs regressed.
