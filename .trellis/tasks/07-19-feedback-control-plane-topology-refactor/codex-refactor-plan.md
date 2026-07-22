# Executable Refactor Playbook v3 — Code-Grounded (No Mock)

**Status:** Binding. Supersedes v1/v2 in this file.  
**Purpose:** One real Direct `用户预订宾馆` → Registry `RELEASED`.  
**Honesty rule:** Every Gate cites file:symbol + live Artifact or `rg` proof. Claims that were wrong in v2 are struck below.

---

## 0. Corrections to prior plan (what was wrong)

| Prior claim | Code / Artifact reality |
|---|---|
| Smoking-gun run validates Scheduler/`IntegrationLeaf` | **False.** `run:5eb0ddff…` has **0** hits under `state/work-control/`. Snapshot contains `control.feedback_result`, `control.repair_directive`, `control.repair_ledger_entry`, `control.node_commit` — **legacy Controller + FeedbackContract + RepairRouter**. |
| Current `generate()` still that path | **False for HEAD.** `FoundryController._execute_direct_locked` → `_execute_scheduler_direct_locked` → `DirectWorkRunner` only (`controller.py:864–892`). Live fail is historical; shared Judge evidence bugs still matter because `IntegrationLeaf` calls the same `EnvironmentJudge.evaluate_integration`. |
| Failure text `…not owned by the current Builder revision…` is current code | **Gone from tree** (`rg` empty). Present only in live `generate-result` Artifact from 2026-07-19. Do not plan against that string; plan against **current** `RepairRouter` / `WorkRepair` + Judge evidence. |
| A1 = “supervisor forgot stderr” | **Incomplete.** `RuntimeSupervisor._crashed_error` already puts `exit_code` + `stderr` in `exc.details` (`supervisor.py:1346–1354`). Enrichment exists in `_candidate_failure_summary` (`service.py:235–254`). Live protocol evidence still `{failure_class,message,status}` with **unenriched** message ⇒ details were empty **or** never copied into the evidence dict. Protocol fail branch copies `ProtocolViolation.details` but **not** `RuntimeProcessCrashed.details` (`service.py:1804–1815`). |
| Materialization same bug as protocol | **Worse / different.** Fail record is only `status/failure_class/framework_call_count/runtime_reset_count/candidate_output_authority` — **no message, no details** (`service.py:2179–2185`). `summary=str(exc)` without `_candidate_failure_summary`. Live: `framework_call_count=72`, `runtime_reset_count=0` ⇒ prepared 72 calls, crashed **before any** Runtime reset episode. |
| Progress can see repair improvement via fingerprints | **Structurally impossible today.** `_finding` fingerprint = `sha256({category, owner, summary})` where `summary` is always `"{gate_id} did not pass."` from `_record_gate` (`service.py:3596–3607`, `3678–3685`). Recomputed: `runtime_protocol`+`build`+`runtime_protocol did not pass.` == live `sha256:d637eb453c…996198` **exactly**. Evidence content is not in the fingerprint. Attempt1==Attempt2 fingerprints are guaranteed even if stderr appeared. |
| `integration_repair_build_reject` means Scheduler parent-repair bug | **Legacy router.** Second directive `action=reject` while controller requires `owner_node==build && action==continue_session` (`controller.py:6088–6105` pattern). Current Direct path uses `LeafValidationFailure.parent_repair_target` + `WorkRepair` instead — must be audited separately, not assumed identical. |

**Implication:** Fix shared **Judge evidence + Finding identity** first (used by both legacy and `IntegrationLeaf`). Then verify **Scheduler IntegrationLeaf repair routing** on HEAD. Do not write a plan that only “adds stderr” and declares Integration fixed.

---

## 1. Purpose lock

Done = fresh Direct generate of `用户预订宾馆` → `RELEASED` + package ref + Reset/invoke evidence, real backend, no mocks, no hand edits.

Config: `.agent-world-live/workgraph-hotel-v2/config.toml`  
Frozen read-only evidence: that state tree + `batched-hotel` + `recovery`.

---

## 2. Absolute bans

1. Raise retry/repair ceilings.  
2. Hand-edit Design/Candidate for green.  
3. Silent ABI/state/tool_id normalization.  
4. Dual-write FeedbackContract + WorkCommit on Direct success path.  
5. Expand/Evolve/skills before Gate J3 green.  
6. Treat unit-test green as RELEASED.  
7. One Gate per session; no skipping.

---

## 3. Call chains that matter (read before coding)

### 3.1 Integration evaluation (shared)

```text
EnvironmentJudge.evaluate_integration
  → schema / clean install / supply_chain / static_assurance / public_self_check
  → _integration_protocol_gate   # handshake + tool_id match only
  → _task_materialization_gate   # materializer + Runtime initial-state via _episode_driver
  → clean_deployment OR inconclusive stub
  → _record_gate → Finding(summary="{gate} did not pass.", suggested_repair=<gate summary>)
```

Files: `agent_world/judge/service.py`.

### 3.2 Scheduler path (HEAD Direct)

```text
IntegrationLeaf.execute
  → judge.evaluate_integration
  → _integration_proposal
       ready → commit
       else LeafValidationFailure(issues=_report_issues(report),
                                  parent_repair_target=Build iff all findings owner==build)
  → SchedulerLeafExecutor / WorkRepair
```

Files: `agent_world/judge/leaf.py`, `agent_world/control/leaf_executor.py`, `agent_world/control/work_repair.py`, `agent_world/control/direct_runner.py`.

### 3.3 Legacy path (smoking-gun only)

```text
Controller._judge_and_repair
  → FeedbackContract / Finding / RepairRouter.route
  → RepairDirective(continue_session|reject|…)
  → RepairLedger progress on fingerprint set
```

Files: `agent_world/controller.py`, `agent_world/control/repair.py`, `agent_world/control/feedback.py`.  
Still present for Expand / dead helpers; **not** Direct success path on HEAD.

### 3.4 Crash details path

```text
RuntimeSupervisor.request empty stdout
  → _refresh_stderr → _crashed_error(details={exit_code, stderr})
  → except in _integration_protocol_gate / _task_materialization_gate
  → evidence JSON (today drops details) → Finding.suggested_repair (gate summary)
  → fingerprint ignores suggested_repair and evidence
```

---

## 4. Hard Gates (strict order)

```text
J1 → J2 → J3 → S1 → S2 → B3 → C2 → D0 → E0 → E1
```

(J = Judge shared; S = Scheduler repair; then diagnose/design/delete/live.)

---

### Gate J1 — Persist crash coordinates in evidence Artifacts

**Code targets**

1. `service.py` `_integration_protocol_gate` fail branch (~1804–1815): for `RuntimeProcessCrashed` / `RuntimeRequestTimeout`, write into evidence dict at least:
   - `exit_code`, `stderr` (bounded), `stderr_truncated` if available, `failure_mode`
   - keep enriched `message` via `_candidate_failure_summary`
2. `service.py` `_task_materialization_gate` fail branch (~2179–2185): same coordinates + `message` via `_candidate_failure_summary` (today omits message entirely).
3. `supervisor.py`: before every `_crashed_error`, ensure stderr refresh; add `argv` from launch contract into details if not already present.
4. Prove with a **real child process** test in `tests/agent_world/test_runtime_process_integration.py` that drives supervisor → gate evidence write (not only unit-testing `_candidate_failure_summary`).

**PASS**

```bash
uv run pytest -q tests/agent_world/test_runtime_process_integration.py -k 'crash or protocol or materialization or stderr'
# Assert evidence JSON keys exist on fail for BOTH integration-runtime-protocol and task-materialization shapes.
```

**FAIL if** either gate can still emit live-like 3-field / no-message records for `RuntimeProcessCrashed`.

**Codex packet**

```text
Active task: .trellis/tasks/07-19-feedback-control-plane-topology-refactor
Gate: J1 | BC: BC-02, BC-03
Evidence: service.py:1804-1815, 2179-2185; supervisor.py:_crashed_error;
  live evidence sha256:ac120e… (103B) and sha256:7291da… (no message)
Forbidden: repair policy, fingerprint, Expand, skills, Scheduler-only refactors
```

---

### Gate J2 — Finding identity must include causal evidence digest

**Why (proven):** fingerprint = category+owner+fixed summary ⇒ repair progress is blind. Live attempt1/2 identical fingerprints with identical evidence hashes; Builder still burned a turn.

**Code targets**

1. `EnvironmentJudge._finding` (`service.py:3666–3709`): fingerprint MUST incorporate a stable digest of **causal evidence content** (evidence `content_hash` or sanitized evidence body fields: `failure_class`, `exit_code`, `stderr_exception`, `missing_module`, `protocol_code`, `mismatch_paths`). Keep category/owner. Do **not** fingerprint raw stderr text if policy forbids; use derived safe coordinates already used by `_candidate_failure_summary`.
2. `_record_gate`: stop minting blocking Findings for `clean_deployment` + `inconclusive` + reason `protocol or task materialization failed first` **or** mark `blocks_release=False` / exclude from progress claim set. Live used that third fingerprint in `blocking_claim_ids_*`.
3. Tests: (a) same gate different exit_code/stderr coords ⇒ different fingerprints; (b) inconclusive deployment not in blocking claim set; (c) recompute legacy live formula still documented as obsolete.

**PASS**

```bash
uv run pytest -q tests/agent_world -k 'finding_fingerprint or fingerprint or integration_finding or blocking_claim'
```

**FAIL if** two crashes with different `exit_code`/`missing_module` share a fingerprint.

**Codex packet**

```text
Gate: J2 | Depends: J1 PASS | BC: BC-02, BC-04
Evidence: service.py _finding fingerprint formula; live identical sha256:d637eb… across attempts;
  proven recomputation in playbook §0
Forbidden: raise retries; Expand
```

---

### Gate J3 — IntegrationLeaf issues must read evidence (not summary[:512])

**Code targets**

1. `judge/leaf.py` `_report_issues` (~612–637): for each failed gate/finding, load evidence Artifact via `artifacts.get_json(evidence_ref)`; set `code`, `path`, `violated_condition`, `expected_category` from evidence fields. If evidence lacks typed coords → `framework_diagnostic_incomplete`, `retryable=False`.
2. Ensure non-retryable-only issue sets **cannot** authorize Agent repair in `WorkRepair` / leaf kernel (add assertion test).
3. Do not depend on legacy FeedbackContract for Direct.

**PASS**

```bash
uv run pytest -q tests/agent_world/test_scheduler_leaf_executor.py tests/agent_world/test_integration_feedback_quality.py
# include: summary-only → no Agent repair; typed evidence → retryable once
```

**Codex packet**

```text
Gate: J3 | Depends: J2 PASS | BC: BC-02, BC-03, BC-18(Direct)
Evidence: leaf.py:_report_issues; IntegrationLeaf._integration_proposal
```

---

### Gate S1 — Scheduler Build parent-repair + no-op detection

**Why:** HEAD Direct uses parent_repair_route, not RepairDirective. Live no-op (same runtime closure, only `tests/test_runtime.py`) must be impossible to count as progress under WorkRepair.

**Code targets**

1. Trace `LeafValidationFailure.parent_repair_target` → `control.parent_repair_route` → `work_runtime` / `work_repair` (`leaf_executor.py` ~669+, `work_runtime.py` ~2067+, `work_repair.py`).
2. After Build repair attempt: compare CandidateManifest **runtime closure** digests (runtime/materializer/entrypoints — exclude `tests/`). Unchanged closure + unchanged **J2** blocker set ⇒ `unchanged` / deny further Agent repair.
3. Test on Scheduler path (not legacy RepairLedger-only).

**PASS**

```bash
uv run pytest -q tests/agent_world/test_work_repair_ledger.py tests/agent_world/test_scheduler_leaf_executor.py -k 'parent_repair or noop or unchanged or integration'
```

**Codex packet**

```text
Gate: S1 | Depends: J3 PASS | BC: BC-04, BC-07(partial)
Evidence: live r1/r2 same completion_hash; only tests/test_runtime.py; HEAD DirectWorkRunner
```

---

### Gate S2 — Builder first-write SLA enforced

**Evidence:** `work_graph.py` declares `first_progress_seconds`/`first_write_seconds`; `rg` on `work_runtime.py` was empty.

Wire enforcement; silence ⇒ typed terminal. Test required.

```bash
rg -n "first_progress_seconds|first_write_seconds" agent_world/control/work_runtime.py agent_world/control/work_scheduler.py
# must hit enforcement sites
uv run pytest -q tests/agent_world -k 'first_write or first_progress or builder_silence'
```

---

### Gate B3 — diagnose CLI (diagnostic WorkGraph mode)

Implement `run diagnose --from … --until … --no-rework` per `design.md` §10. Cannot publish.

```bash
uv run agent-world --help | rg diagnose
uv run pytest -q tests/agent_world/test_app_cli.py -k diagnose
```

---

### Gate C2 — Real Design → ModelingBoundary under existing 1+1

Only after J3+S1 (so later Integration repairs are not blind). Real config, real model:

```bash
CFG=.agent-world-live/workgraph-hotel-v2/config.toml
uv run agent-world --config "$CFG" doctor --production
REQUEST_ID="hotel-booking-c2-$(date -u +%Y%m%d)-01"
uv run agent-world --config "$CFG" generate --need '用户预订宾馆' --request-id "$REQUEST_ID" --no-discovery
uv run agent-world --config "$CFG" run inspect "$REQUEST_ID" --metrics
```

**PASS:** ModelingBoundary/EnvironmentDesign WorkCommit exists under **work-control** (not only legacy node_commit).  
**FAIL:** no_progress in ToolSemantics with no commit; or retry ceilings changed.

If Design dies first, stay on C1-class compiler/binding fixes (ToolSemantics/Rules parity — see design leaves); do not open E0.

---

### Gate D0 — Delete dead Direct legacy entrypoints

```bash
rg -n "def _run_design" agent_world/controller.py   # must be gone after
rg -n "5eb0ddff" .agent-world-live/workgraph-hotel-v2/state/work-control  # historical only
# Ensure default generate cannot call FeedbackContract authorize for Direct leaves
```

Expand unification **after E1 only**.

---

### Gate E0 — diagnose Candidate → Integration (real)

```bash
uv run agent-world --config "$CFG" run diagnose --from "$REQUEST_ID" --until integration --no-rework
```

Evidence must show J1 fields. ≤1 Build repair only if J2 fingerprints show strict_progress.

---

### Gate E1 — RELEASED

```bash
REQUEST_ID="hotel-booking-released-$(date -u +%Y%m%d)-01"
uv run agent-world --config "$CFG" generate --need '用户预订宾馆' --request-id "$REQUEST_ID" --no-discovery
uv run agent-world --config "$CFG" run inspect "$REQUEST_ID" --metrics
uv run agent-world --config "$CFG" registry list
```

**PASS checklist:** RELEASED; registry row; Reset/invoke refs; no hand edits; telemetry recorded; BC-01 satisfied.

---

## 5. What not to schedule yet (and why)

| Item | Why deferred |
|---|---|
| Expand WorkGraph (BC-10/11) | Direct RELEASED first; Expand still legacy by design on HEAD |
| Skill/prompt edits | J1–J3 must make mechanical failures typed; skills cannot fix empty evidence / blind fingerprints |
| BC-08 Integration reuse | After E0 proves Integration can pass once; then remove duplicate ReleaseAssurance work |
| Matching old failure_summary string | Removed from code; do not resurrect |

---

## 6. Immediate next step

**Only Gate J1.**  

Read `service.py` `_integration_protocol_gate` + `_task_materialization_gate` fail branches and `supervisor._crashed_error` before writing code.  
Append PASS/FAIL to `implement.md` before J2.

---

## 7. Prep commands (once)

```bash
cd /home/kelong/pycodes/agent-world-model
uv sync
uv run agent-world --config .agent-world-live/workgraph-hotel-v2/config.toml doctor --production
uv run ruff check agent_world tests/agent_world
uv run mypy agent_world
uv run pytest -q tests/agent_world
```
