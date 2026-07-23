# AI Implementation Plan — Direct Hotel RELEASED

**Audience:** Any coding agent (Codex / Claude / Cursor) implementing this task cold.  
**Task:** `.trellis/tasks/07-19-feedback-control-plane-topology-refactor`  
**Repo:** `/home/kelong/pycodes/agent-world-model`  
**Status:** Binding handoff for individually admitted Direct gates. The 2026-07-23 calibration at
`docs/plans/refactor-plan-calibration.md` controls evidence classification, model preflight,
cross-scope reuse, and final task completion; it supersedes conflicting informal plan claims.  
**Language:** Follow existing code style. Prefer English for code/commits; this plan is bilingual where helpful.

---

## 0. How to use this document

1. Read **§1 Purpose**, **§2 Architecture lock**, **§3 Absolute bans** before any edit.
2. Read listed files for the Gate you are on — do not invent a parallel control plane.
3. Execute **exactly one causal Gate per commit/PR**. A session may finish that Gate's code,
   regressions, review and log, but must not mix two Gates merely to create apparent progress.
4. Append a Gate log to `implement.md` (template in §12).
5. Do not mark the task done until **Gate E1** (live `RELEASED`).

Required reading before Gate J1:

- `docs/agent-world-environment-generation.zh.md` §1–2, §3.5–3.7, §6
- `design.md` (this task)
- `bad-cases.json`
- This file end-to-end

---

## 1. Purpose (single success metric)

Convert natural-language need into a **programmatic** Agent environment:

```text
NL need → research/design (bounded Agents)
       → code-owned state transition Runtime
       → independent verification
       → directed repair
       → EnvironmentPackage RELEASED
       → later rollout / RL / veRL
```

**Gate E1 exit =** one fresh Direct run for `用户预订宾馆` reaches Registry status **`released`**, with retained:

- package Artifact ref + content hash
- Reset + at least one successful invoke evidence
- telemetry (turns / tokens / repairs / unknowns)

**Not done:** unit tests green, Design-only commit, hand-patched Candidate, diagnostic-only success, Expand success, mock backend.

Training is **not** a precondition. Evolve is not a precondition for claiming the **Direct**
milestone, but this refactor task cannot be archived while Expand still has a legacy semantic
retry/control path: F1 plus its shared-graph live acceptance is a required task-completion gate.

---

## 2. Architecture lock (do not redesign)

### 2.1 Production Direct path (HEAD)

```text
FoundryController.generate
  → DirectWorkRunner
       bootstrap (diagnostic, non-releasable):
         ResearchPlan → Acquisition → EvidenceSynthesis → Architecture
       design (keeps bootstrap commits):
         SharedToolSemantics? → ToolSemanticsBatch* → WorldRules
         → TaskCurriculum → ModelingBoundary → VerifierPlan
       final (only releasable epoch):
         VerifierBatches ∥ Build → Integration → ReleaseAssurance
         → Observability → Package(ReleaseDossier) → RegistryPublication
  → DirectWorkRun {released|blocked}
```

Key symbols:

- `agent_world/controller.py` — `generate`, `_execute_scheduler_direct_locked`
- `agent_world/control/direct_runner.py` — `DirectWorkRunner`
- `agent_world/control/work_scheduler.py` — sole retry/commit authority
- `agent_world/control/leaf_executor.py` — one-attempt leaf kernel + `AgentCorrectionBrief`
- `agent_world/control/work.py` — WorkDefinition / Attempt / ValidationReport / FeedbackEvaluation / WorkCommit / RepairAction

### 2.2 Authority layers (never mix)

| Layer | May do | Must not do |
|---|---|---|
| Agent (Researcher / Engineer / Challenger) | Bounded semantic proposal / codegen | Emit Finding, Budget, RepairDirective, release, owner/jump |
| Framework compilers / Judge / Supervisor | Schema/Rule IR/protocol/real probes | Invent workflow jumps |
| Scheduler / Release / Registry | Attempt, RepairAction, invalidate, publish | Invent business rules |

`AgentCorrectionBrief` projects only blocker `(code, path, violated_condition, expected_category)` — never RepairAction/policy.

### 2.3 Evolve (important)

- **Product design already exists** (source doc §2.2 / §11): Source → Policy → Operator → full Design rebuild → same Builder/Judge/Registry.
- Genotype = tool surface / semantics / state constraints / task scope — **not** source patches.
- **HEAD Expand is legacy** (`ExpansionDesignDraft`, component reworks; BC-10/11) — not on shared WorkGraph.
- **Do not redesign Evolve.** Do not claim Evolve works on legacy Expand.
- **Do not implement Evolve cutover until Gate E1 PASS** (optional: BC-10/11 topology tests only, no live Expand campaign).

### 2.4 Live config / frozen evidence

| Item | Path |
|---|---|
| Live config | `.agent-world-live/workgraph-hotel-v2/config.toml` |
| State root | `.agent-world-live/workgraph-hotel-v2/state` |
| Historical Integration fail (legacy path) | `run:5eb0ddffdf7843b1b2f3b6efeb82e501` / request `hotel-booking-stable-workgraph-20260719-01` |
| Design-stop corpus | `.agent-world-live/batched-hotel/` |
| Bad cases | `bad-cases.json` BC-01…BC-18 |

Treat live trees as **read-only evidence** unless starting a new request_id under that config.

For a new live acceptance, do not reuse the historical ChatGPT-auth configuration as an implicit
provider choice. Create an ignored, local Spark configuration whose profile explicitly records
`model = "gpt-5.3-codex-spark"`, API-key authentication via the approved `OPENAI_API_KEY`
handle, and the credential-free base URL from the approved `OPENAI_BASE_URL` handle. Record only
the profile/config digest, model and environment-variable *names* in task evidence; never commit
the URL value or any credential.

---

## 3. Absolute bans

1. Raise any repair/retry ceiling (`maximum_local_corrections`, progress bonus, Expand `maximum_structured_reworks`, job repair budget) to pass hotel.
2. Hand-edit Design/Candidate Artifacts and claim success.
3. Silently normalize digests / tool_ids / state shapes to make gates pass (typed fail + repair packet only).
4. Dual-write legacy FeedbackContract/NodeAttempt **and** WorkCommit on Direct success path.
5. Touch Expand/Evolve/Discovery/skills before **J3 PASS** (skills only after J3 if typed issue proves instruction gap; Evolve code after **E1**).
6. Treat pytest green as RELEASED.
7. Skip Gates or batch multiple Gates in one PR.
8. Call a BC “closed” without a failing-then-passing regression named in the Gate log.
9. Spend Agent repair turns on generic / non-actionable diagnostics.
10. Reintroduce per-entity microsharding or model-authored JSON Schema graphs.

---

## 4. Critical path (strict order)

```text
PRE → J1 → J2 → J3 → S1 → S2 → B3 → C1 → C2 → D0 → E0 → E1
                                                    └→ (optional after E1) F1 Evolve cutover
```

No skipping. Stop on FAIL.

---

## 5. Prep (Gate PRE)

```bash
cd /home/kelong/pycodes/agent-world-model
uv sync
CFG=.agent-world-live/workgraph-hotel-v2/config.toml
uv run agent-world --config "$CFG" doctor
uv run agent-world --config "$CFG" doctor --production
uv run ruff check agent_world tests/agent_world
uv run mypy agent_world
uv run pytest -q tests/agent_world
```

**PASS:** doctor --production OK (fix real deps — SearXNG/Bing/auth/uv — do not mock). Baseline tests recorded.  
**FAIL:** cannot start J1 until production doctor passes.

---

## 6. Gates (binary Must-ship)

### Gate J1 — Persist Runtime crash coordinates in Judge evidence

**Why (code + live):**

- `RuntimeSupervisor._crashed_error` already sets `details={exit_code, stderr}` (`agent_world/judge/supervisor.py`).
- `_candidate_failure_summary` can enrich messages (`judge/service.py` ~235–254).
- `_integration_protocol_gate` fail record copies `ProtocolViolation.details` but **not** `RuntimeProcessCrashed.details` (~1804–1815).
- `_task_materialization_gate` fail record omits message/details entirely (~2179–2185). Live: `framework_call_count=72`, `runtime_reset_count=0`.
- Live protocol evidence was only `{failure_class, message, status}` (103 bytes).

**Edit:**

| File | Change |
|---|---|
| `agent_world/judge/supervisor.py` | Before `_crashed_error`, refresh stderr; include `argv`, `failure_mode`, truncation flags in details when available |
| `agent_world/judge/service.py` | Protocol + materialization fail branches: write `exit_code`, bounded `stderr`, `failure_mode`, enriched `message` via `_candidate_failure_summary` |
| `tests/agent_world/test_runtime_process_integration.py` | Real crashing child → evidence JSON contains required keys for **both** protocol and materialization shapes |

**Required evidence keys on crash fail:**  
`status`, `failure_class`, `message`, `exit_code` (nullable only with explicit `failure_mode`), `stderr` (bounded), `argv` (if known), `failure_mode` ∈ {crash, timeout, protocol_hang, …}

**Commands:**

```bash
uv run ruff check agent_world/judge/supervisor.py agent_world/judge/service.py tests/agent_world/test_runtime_process_integration.py
uv run mypy agent_world/judge
uv run pytest -q tests/agent_world/test_runtime_process_integration.py -k 'crash or protocol or materialization or stderr or RuntimeProcess'
```

**BC:** BC-02, BC-03  
**Dispatch header:**

```text
Active task: .trellis/tasks/07-19-feedback-control-plane-topology-refactor
Purpose: Direct hotel RELEASED only
Gate: J1
Read: ai-implementation-plan.md §6 J1; judge/supervisor.py; judge/service.py fail branches
Forbidden: fingerprint changes; repair policy; Expand; skills; raise retries; Gate J2+
Exit: J1 Must-ship checklist PASS/FAIL in implement.md
```

---

### Gate J2 — Finding fingerprint must include causal evidence coordinates

**Why (proven):**  
`_finding` fingerprint = `sha256({category, owner, summary})` where `_record_gate` sets `summary=f"{gate_id} did not pass."` (`service.py` ~3596–3709).  
Recomputed fingerprint for `runtime_protocol`+`build`+`runtime_protocol did not pass.` == live `sha256:d637eb453c…996198`.  
Evidence improvements cannot change progress identity. Live attempt1==attempt2 fingerprints.

**Edit:**

| File | Change |
|---|---|
| `agent_world/judge/service.py` `_finding` | Fingerprint must include stable digest of **safe causal coords** from evidence (e.g. `failure_class`, `exit_code`, `stderr_exception`, `missing_module`, `protocol_code`, `mismatch_paths`, and/or evidence `content_hash`). Do not fingerprint raw secrets. Keep category/owner. |
| `agent_world/judge/service.py` `_record_gate` / deployment branch | `clean_deployment` inconclusive because upstream failed: **do not** create a blocking Finding that participates in progress identity (skip Finding, or `blocks_release=False` / exclude from claim set — pick one + test) |
| New/extended tests | (a) different exit_code/missing_module ⇒ different fingerprints; (b) inconclusive deployment not in blocking set; (c) document old formula obsolete |

**Commands:**

```bash
uv run pytest -q tests/agent_world -k 'finding_fingerprint or fingerprint or integration_finding or blocking_claim'
uv run ruff check agent_world/judge tests/agent_world
uv run mypy agent_world/judge
```

**BC:** BC-02, BC-04  
**Forbidden:** raise retries; Expand.

---

### Gate J3 — IntegrationLeaf ValidationIssues must read evidence

**Why:**  
`judge/leaf.py` `_report_issues` uses `gate.summary[:512]` / `finding.summary[:512]`. Design path already preserves `StructuredSemanticIssue` → `AgentCorrectionBrief`. Integration must meet the same bar on HEAD Scheduler path.

**Edit:**

| File | Change |
|---|---|
| `agent_world/judge/leaf.py` `_report_issues` | Load evidence Artifact; populate code/path/condition/expected from evidence fields |
| Same + WorkRepair path | Summary-only / incomplete diagnostics → `retryable=False`; non-retryable-only sets must not authorize Agent repair |
| Tests | `test_integration_feedback_quality.py` (new) + scheduler leaf tests |

**Commands:**

```bash
uv run pytest -q tests/agent_world/test_integration_feedback_quality.py tests/agent_world/test_scheduler_leaf_executor.py tests/agent_world/test_runtime_process_integration.py
```

**BC:** BC-02, BC-03  
**After J3:** skills may be touched **only** if a typed issue proves an instruction gap code cannot close.

---

### Gate S1 — Scheduler parent-repair + no-op Builder detection

**Why:**  
HEAD Direct uses `LeafValidationFailure.parent_repair_target` → `control.parent_repair_route` → `WorkRepair`, not legacy RepairDirective.  
Live legacy repair: same `completion_hash`, only `tests/test_runtime.py` changed, fingerprints unchanged — burned a turn.

**Edit:**

| Area | Change |
|---|---|
| Builder/repair compare | Define runtime closure paths from CandidateManifest (runtime/materializer/entrypoints — **exclude tests/**) |
| WorkRepair / leaf envelope | Unchanged runtime-closure digests + unchanged J2 blocker set ⇒ `unchanged` / deny further Agent repair |
| Tests | Scheduler-path reconstruction of no-op pattern |

**Commands:**

```bash
uv run pytest -q tests/agent_world/test_work_repair_ledger.py tests/agent_world/test_scheduler_leaf_executor.py tests/agent_world/test_work_control_contracts.py -k 'parent_repair or noop or unchanged or progress or integration'
```

**BC:** BC-04

---

### Gate S2 — Enforce Builder first-write SLA

**Why:** `work_graph.py` declares `first_progress_seconds` / `first_write_seconds`; enforcement was missing in `work_runtime.py` (BC-07).

**Edit:** Wire deadlines in Scheduler/runtime; silence → typed terminal before wall timeout. Test with stub Builder that never journals first-write.

**Commands:**

```bash
rg -n "first_progress_seconds|first_write_seconds" agent_world/control/work_runtime.py agent_world/control/work_scheduler.py
# Must show enforcement call sites (not only work_graph definitions)
uv run pytest -q tests/agent_world -k 'first_write or first_progress or builder_silence or sla'
```

**BC:** BC-07

---

### Gate B3 — Diagnostic CLI (non-releasable)

**Why:** `design.md` §10; `cli.py` has `run inspect` / `run resume` only.

**Edit:**

- `agent_world/cli.py` + app/controller glue: `run diagnose --from … --until … --no-rework`
- Mode = WorkGraph `diagnostic`; `releasable=false`; no RepairAction when `--no-rework`
- Tests: cannot Registry publish

**Commands:**

```bash
uv run agent-world --help | rg diagnose
uv run pytest -q tests/agent_world/test_app_cli.py -k diagnose
```

---

### Gate C1 — WorldRules / TaskCurriculum diagnostic parity with ToolSemantics

**Why:** BC-14/15/17 — ToolSemantics has bound catalogs + correction briefs; Rules/Curriculum lag → next stall after batches.

**Edit:** Bring `final_design_leaves.py` WorldRules/Curriculum to same structured issue / brief quality. Keep BC-15 array-pointer rejection. **Do not change retry maxima** (`rg maximum_local_corrections agent_world/control/work_graph.py` must not increase).

**Commands:**

```bash
uv run pytest -q tests/agent_world/test_designer_world_composition.py tests/agent_world/test_designer_rule_ir.py tests/agent_world/test_scheduler_leaf_executor.py
```

**BC:** BC-14, BC-15

---

### Gate C2 — Live / checkpointed Design → ModelingBoundary (real backend)

**Why:** BC-17 / BC-01 precondition. No “file BC and pass”.

```bash
CFG=.agent-world-live/workgraph-hotel-v2/config.toml
uv run agent-world --config "$CFG" doctor --production
REQUEST_ID="hotel-booking-c2-$(date -u +%Y%m%d)-01"
uv run agent-world --config "$CFG" generate \
  --need '用户预订宾馆' \
  --request-id "$REQUEST_ID" \
  --no-discovery
uv run agent-world --config "$CFG" run inspect "$REQUEST_ID" --metrics
```

**PASS:** ModelingBoundary / EnvironmentDesign **WorkCommit** exists under `state/work-control` (Scheduler path), repair ceilings unchanged, refs recorded in `implement.md`.  
**FAIL:** ToolSemantics no_progress without commit; manual Artifact edits; raised retries → stay on C1 compiler/binding fixes; do not open D0/E0.

---

### Gate D0 — Delete dead Direct legacy entrypoints

```bash
rg -n "def _run_design" agent_world/controller.py
rg -n "FeedbackContract|PRODUCTION_FEEDBACK" agent_world/control/direct_runner.py agent_world/control/leaf_executor.py agent_world/builder/leaf.py agent_world/judge/leaf.py
```

Delete caller-less Direct helpers (e.g. `_run_design` if still dead). Ensure default `generate` cannot enter Expand legacy loops.  
Expand WorkGraph unification = **Gate F1 after E1 only**.

**BC:** BC-18 subset

---

### Gate E0 — Real diagnose Build → Integration

```bash
CFG=.agent-world-live/workgraph-hotel-v2/config.toml
# Flags must match B3 implementation
uv run agent-world --config "$CFG" run diagnose \
  --from "$REQUEST_ID" \
  --until integration \
  --no-rework
```

If fail: evidence must satisfy J1/J2; ≤1 Scheduler Build repair only with strict_progress; re-diagnose; **no Registry write**.

---

### Gate E1 — Live Direct RELEASED (Direct milestone)

```bash
CFG=.agent-world-live/workgraph-hotel-v2/config.toml
REQUEST_ID="hotel-booking-released-$(date -u +%Y%m%d)-01"
uv run agent-world --config "$CFG" doctor --production
uv run agent-world --config "$CFG" generate \
  --need '用户预订宾馆' \
  --request-id "$REQUEST_ID" \
  --no-discovery
uv run agent-world --config "$CFG" run inspect "$REQUEST_ID" --metrics
uv run agent-world --config "$CFG" registry list
# registry inspect PACKAGE_ID VERSION from list
```

**PASS checklist:**

- [ ] inspect/result shows released
- [ ] `registry list` shows package
- [ ] Reset + invoke evidence refs recorded
- [ ] No manual Candidate/Design edits
- [ ] Telemetry recorded in `implement.md` / journal
- [ ] BC-01 `required_regression` satisfied

**This Gate proves the primary Direct product milestone only.** It does not close this refactor
task while F1's legacy Expand path exists, nor does it turn historical/diagnostic evidence into
an Evolve result.

---

### Gate F1 — Evolve cutover (required after E1, before task archive)

Do **not** start before E1 PASS.

1. `ExpansionSeed` adapter → same WorkDefinitions as Generate (`design.md` §4.2).
2. Delete `ExpansionDesignDraft` success path; all Expand semantic retries via `WorkRepairLedger`.
3. BC-10/11 regressions green.
4. Run a bounded real campaign through the shared graph: one proposal must have a real semantic
   delta with Runtime/Rule-IR evidence and reach Registry; a separate candidate may honestly end
   `rejected` or `needs_human`. Record lineage, usage, repair depth and ask/tell checkpoints.

Until F1: Expand CLI may remain but must not be claimed as Evolve success. Task completion is
blocked until the legacy expansion success path and component-local semantic retry are deleted
after this shared-path acceptance passes.

---

## 7. Optional Gate B2 (after E0 or with E1 prep) — Integration evidence reuse

**BC-08:** ReleaseAssurance must not blindly re-run Integration-class probes on identical candidate+policy+toolchain digest (`design.md` §9).  
Implement digest key + skip-on-match + fail-closed on mismatch + call-count test.  
May run after E0 if Integration passes once; do not block J1–J3.

---

## 8. Bad-case → Gate map

| BC | Status intent | Gate |
|---|---|---|
| BC-01 | still_open until E1 | E1 |
| BC-02 / BC-03 | Integration/Design diagnostics | J1, J2, J3 |
| BC-04 | progress / no-op | J2, S1 |
| BC-05 | no microshard return | ban + C1 |
| BC-06 / BC-09 / BC-18 | dual authority | D0; F1 for Expand |
| BC-07 | first-write SLA | S2 |
| BC-08 | evidence reuse | B2 |
| BC-10 / BC-11 | Evolve same graph | F1 |
| BC-12 | infra | out of critical path |
| BC-13 | closed_in_code | keep regression |
| BC-14 / BC-15 / BC-17 | Design convergence | C1, C2 |
| BC-16 | continuation | only if restart blocks E1 |

---

## 9. Historical smoking-gun facts (do not mis-attribute)

`run:5eb0ddff…` used **legacy** Feedback/RepairDirective path (`work-control` mentions = 0).  
HEAD Direct uses `DirectWorkRunner`. Shared Judge evidence bugs still matter because `IntegrationLeaf` calls `evaluate_integration`.  
Do not plan against removed failure_summary strings; plan against current `WorkRepair` + Judge evidence.

---

## 10. Commit / PR rules

- One Gate per PR when possible.
- Message names Gate id + BC ids, e.g. `fix(J1): persist RuntimeProcessCrashed details in integration evidence (BC-02/03)`.
- Do not commit secrets, `.env`, or live credential files.
- Do not `git push` unless human asks.
- Do not amend unless human asks and amend rules allow.

---

## 11. Standard dispatch preamble (copy for every Gate)

```text
Active task: .trellis/tasks/07-19-feedback-control-plane-topology-refactor
Repo: /home/kelong/pycodes/agent-world-model
Plan: .trellis/tasks/07-19-feedback-control-plane-topology-refactor/ai-implementation-plan.md
Purpose: One Direct 用户预订宾馆 → Registry RELEASED (real backend, no mocks)
Gate: <ID>
BC: <ids>
Read first: plan §1–3, this Gate section, cited source files
Forbidden: raise retries; hand-edit Artifacts; silent ABI normalize; Expand/Evolve before E1;
  skills before J3; skip gates; dual-write Feedback+WorkCommit on Direct
Work: implement ONLY this Gate
Validate: run the Gate Commands
Exit: append Gate log to implement.md with PASS/FAIL; stop if FAIL
```

---

## 12. Gate log template (append to `implement.md`)

```markdown
### Gate <ID> — <UTC date> — PASS|FAIL
- Agent/session:
- Diff files:
- Commands + results:
- New/updated tests:
- BC advanced:
- Live request_id (if any):
- Still blocks RELEASED?:
- Notes:
```

---

## 13. Immediate next action for the implementing AI

1. Run **Gate PRE**.  
2. If PASS, execute **Gate J1 only** using §11 preamble.  
3. Stop after J1 log. Do not open J2 until human or plan says continue.

---

## 14. Traceability index

| Gate | Primary code | Primary BC |
|---|---|---|
| J1 | `judge/supervisor.py`, `judge/service.py` | BC-02, BC-03 |
| J2 | `judge/service.py` `_finding` / `_record_gate` | BC-02, BC-04 |
| J3 | `judge/leaf.py` | BC-02, BC-03 |
| S1 | `control/work_repair.py`, builder digests, leaf_executor | BC-04 |
| S2 | `control/work_runtime.py` / scheduler | BC-07 |
| B3 | `cli.py`, diagnostic WorkGraph mode | design §10 |
| C1 | `designer/final_design_leaves.py`, `rule_context.py` | BC-14, BC-15 |
| C2 | live Direct Scheduler Design epoch | BC-17, BC-01 |
| D0 | `controller.py` dead helpers | BC-18 |
| E0 | diagnose CLI + Candidate | J1–J3 proof |
| E1 | full Direct → Registry | BC-01 |
| F1 | `expansion_service.py` → shared WorkGraph | BC-10, BC-11 |
| B2 | `ReleaseAssuranceLeaf` + evidence key | BC-08 |
