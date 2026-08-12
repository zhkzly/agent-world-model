# Independent implementation check — ToolSemantics Feedback progress

- Date: 2026-08-12
- Decision: `allow`
- Reviewed plan digest: `sha256:a8431783859b3875786dc3bdc8320b0100309149372b558aad931db480d241e9`
- Matching critic record: `cross-layer-review-a8431783-tool-feedback-progress.md` (`allow`, revision `1/2`)
- Reviewed real scene: `run_bb8b2474bfd34507b1b73f7856c77ee3`, terminal at `design/tool_semantics[reserve_tool]`; no new provider or E2E run was performed for this check.

## Decision basis

The plan bytes hash to the reviewed digest. The current implementation stays within
the approved local Direct correction boundary:

- `agent_world/design.py` retains the original Direct system message and canonical
  original user task unchanged, including `"correction": null`. For parsed semantic
  correction it keeps only the immediately prior parsed proposal as ephemeral
  canonical JSON and supplies it as the previous assistant message. The next user
  Feedback contains only the safe four-field packet, asks for a complete replacement,
  and requires a whole-result self-check.
- `agent_world/graph.py` permits `local_corrections=2` only for the exact
  `tool_semantics` / `direct_llm` / `direct` node declaration. The static graph sets
  that value only there; all other current Direct and Agent nodes retain their
  pre-existing `0` or `1` budgets.
- The runner executes at most `1 + local_corrections` calls. Its third-call predicate
  requires the same ToolSemantics node, two parsed non-format safe packets, and a
  changed exact `(code, path, violated_condition, expected_category)` tuple. Thus
  A->A stops after two calls; either format position, transport/retryable,
  operation/framework/candidate failure, and a third invalid proposal terminate
  without a fourth call.
- The prior proposal and rendered Feedback remain local variables. Persisted attempt
  evidence contains only the existing safe `CorrectionPacket`; focused tests scan the
  store and exclude rejected proposal markers and Feedback text.

## Actual changed scope and minimality

The observed repair footprint is limited to:

- `agent_world/graph.py` — restricted two-correction declaration and third-proposal
  admission predicate.
- `agent_world/design.py` — reuse of the existing Direct previous-assistant/Feedback
  adapter for parsed semantic correction.
- `tests/test_graph_contracts.py` and `tests/test_design_semantics.py` — focused
  structural, progression, message-shape, terminal, and non-persistence regressions.

The clean worktree has an intentionally untracked implementation baseline relative
to commit `9562c05`, so a normal Git diff cannot isolate this repair. A modification
time audit identifies only the four files above in the implementation window; the
review also verified the actual code paths rather than treating that audit as proof.
No Candidate, Judge, Registry, Artifact/WorkRecord, Observe, compiler, validator,
graph topology, Agent/Skill, downstream WorldRules/Curriculum/Task/Modeling, Repair,
Expand, or Consumer file was changed by this repair. The change adds no Feedback
service, issue aggregation, generic retry/fallback, context manager, node, budget
system, token cap, or validator relaxation.

## Cross-layer compatibility

Successful ToolSemantics still commits the same compiled artifact and WorkRecord
shape, then flows unchanged to WorldRules, CurriculumPlan, TaskRequirement, Modeling,
CandidateGraph, Judge, Registry, and safe Observe. Failure remains an uncommitted
Designer terminal. Semantic identity intentionally remains unchanged because the
accepted prompt/input/output contract and frozen input are unchanged; the bounded
correction presentation/admission is local repair policy.

## Verification

- `uv run pytest -q tests/test_graph_contracts.py tests/test_design_semantics.py` — pass (`100 passed`, 4.81s).
- `uv run pytest -q` — pass (`233 passed`, 13.42s).
- `uv run pytest -q tests/test_legacy_firewall.py` — pass (`2 passed`, 0.22s).
- `uv run ruff format --check .` — pass (`22 files already formatted`).
- `uv run ruff check .` — pass.
- `uv run mypy agent_world` — pass (`13 source files`).
- `uv run python -m compileall -q agent_world` — pass.

## Self-fix

Ruff reported formatting drift in the two scoped test files. I ran Ruff formatting
only on `tests/test_graph_contracts.py` and `tests/test_design_semantics.py`, then
reran the focused suite and all requested static gates. No behavioral change was made.

## Non-claims and next permitted gate

This is deterministic implementation-check evidence only. It does not prove a
corrected Luna leaf, a complete Design, Candidate, Integration, Judge, package,
Registry publication, Direct E2E, Repair, Expand, or Consumer/SFT/RL result.

The next permitted gate is the approved exact immutable-parent `reserve_tool` real
Direct boundary proof followed immediately by Observe. If it reaches a new terminal,
record a new diagnosis before any further repair; do not broaden this allow.
