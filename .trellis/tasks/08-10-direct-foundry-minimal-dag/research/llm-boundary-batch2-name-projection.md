# LLM Boundary Batch 2 — Name Projection (no indices in LLM I/O)

Date: 2026-08-13
Status: Batch 1 + 2a + 2b IMPLEMENTED & verified (282 tests green, ruff/mypy clean). Batch 2c deferred.
Predecessor: `llm-boundary-redesign-plan.md` (principles) + Batch 1 (rule IR).

## Goal

Apply the single principle — **Domain Model ≠ LLM Interface** — to every remaining
LLM/agent-facing interface that still uses positional integer indices. The internal
dataclasses keep their integer indices (deterministic, framework-owned). Only the
projection (what the LLM sees) and the compile (how the LLM output is parsed) change.

## Principle recap (applied uniformly)

- LLM emits **names** (strings it can reason about). Framework resolves name → index.
- Framework emits **names** in projections. Indices, paths, digests never reach the LLM.
- Shallow (≤2 depth), per-field layout, one concrete example per shape.
- Internal `RuleDraft` / `CurriculumFamily` / `VerifierCommitment` etc. UNCHANGED.

## Inventory of remaining index leaks

| # | Node | File:line | Leaks index to LLM | Name-based replacement |
|---|------|-----------|--------------------|------------------------|
| 1 | `shared_tool_semantics` | design.py:1670 | partition of `tool_indexes` (int arrays) | partition of tool **names** |
| 2 | `curriculum_plan` | design.py:1944 | `actor_index` (int), `tool_indexes` (int[]) | `actor` name, `tools` name[] |
| 3 | `verifier_intent` | candidate.py:1024 | `task_family_index`,`tool_index`,`argument_index` (ints) | `task_family` id, `tool` name, `argument` field name |
| 4 | `_verifier_catalog` | candidate.py:791 | `tool_index`, `task_family_index`, `public_goal_fields`(ints) | `tool_name`, `task_family_id`, goal fields as names |
| 5 | `compile_implementation_contract` | candidate.py:267 | `tool_catalog[].tool_index` (redundant: `tool_id`=name already present) | drop `tool_index` |

Batch 1 (rule IR semantic_index → `field` name) is already covered by the running agent.

## Already name-based (NO change needed)

- `world_architecture`: tools use `actor_names` (strings); actors are declared by name. ✓
- runtime `invoke` protocol: uses `tool_id` (= tool name string). ✓
- `task_requirement.public_goal_fields`: Batch 1 made this name-based. ✓

---

## Batch 2a — design.py (after Batch 1 agent finishes; same file)

### 2a.1 `shared_tool_semantics`

**Projection (input to LLM)** — currently:
```json
{"tool_indexes": [1,2,3], "tools": [<full tool objects>], "citations": ...}
```
**Change to:**
```json
{"tool_names": ["assign_ticket","resolve_ticket","close_ticket"], "tools": [<name+purpose+fields only>], "citations": ...}
```

**LLM output** — currently partitions by index:
```json
{"atomicity": [[1,2,3]], "concurrency": [[1,2,3]], "idempotency": [[1,2,3]], ...}
```
**Change to** partitions by NAME:
```json
{"atomicity": [["assign_ticket","resolve_ticket","close_ticket"]],
 "concurrency": [["assign_ticket","resolve_ticket","close_ticket"]],
 "idempotency": [["assign_ticket","resolve_ticket","close_ticket"]],
 "ordering": ["assign before resolve"], "compensation": ["revert assignment"],
 "error_policy": "reject invalid requests"}
```

**Compile:** build `name→index` map from the group's tools. Each partition sublist of
names → tuple of indexes. Validate: every group name used exactly once. Internal
`SharedToolContract` keeps `members` (int tuple) + partitions (int tuples) — byte-identical.

### 2a.2 `curriculum_plan`

**LLM output** — currently:
```json
{"families":[{"task_family_id":"resolve_ticket","actor_index":1,"tool_indexes":[1,2], ...}]}
```
**Change to:**
```json
{"families":[{"task_family_id":"resolve_ticket","actor":"agent","tools":["assign_ticket","resolve_ticket"], ...}]}
```

**Compile:**
- `actor` (name) → resolve against `architecture.boundary.actors` (name list, one-based) → `actor_index`.
- `tools` (name[]) → resolve against `architecture.tools` (by `.name`) → `tool_indexes` (unique one-based).
- Internal `CurriculumFamily` keeps `actor_index` + `tool_indexes`. Byte-identical artifact.

**Projection input:** already sends full `architecture`; the actor/tool names are visible.
Add a one-line reminder: "Reference actors and tools by NAME, not index."

---

## Batch 2b — candidate.py (independent file; can run in parallel with Batch 1)

### 2b.1 `_verifier_catalog` (projection)

**Currently:**
```json
{"tools":[{"tool_index":1,"surface":{...},"local_rules_digest":...}],
 "task_rule_summaries":[{"task_family_index":1,"public_goal_fields":[1,2], ...}]}
```
**Change to:**
```json
{"tools":[{"tool_name":"assign_ticket","surface":{...},"local_rules_digest":...}],
 "task_rule_summaries":[{"task_family_id":"resolve_ticket","public_goal_fields":["status","assigned_to"], ...}]}
```
Build index→name maps from `design.tools` / `design.curriculum.families` /
`design.architecture.catalog.bindings`. Internal data unchanged.

### 2b.2 `verifier_intent` (the worst offender — the release gate)

**LLM output** — currently the agent must emit 3 positional ints:
```json
{"checks":[{"task_family_index":1,"tool_index":2,"family":"argument_variation",
            "argument_index":1,"risk":"..."}]}
```
**Change to** name-based:
```json
{"checks":[{"task_family":"resolve_ticket","tool":"assign_ticket",
            "family":"argument_variation","argument":"ticket_id","risk":"..."}]}
```
For non-`argument_variation` families, `argument` is omitted (same omission rule as today).

**Compile:**
- `task_family` (id) → `task_family_index` via `design.curriculum.families` (by `task_family_id`).
- `tool` (name) → `tool_index` via `design.tools` (by `.surface.name`).
- `argument` (field name) → `argument_index` via the resolved tool's `argument_fields` (by `.name`), one-based; reject if category == "list" (same scalar-only rule).
- `(task_family_index, tool_index)` must be an existing assurance recipe (same recipe-membership check).
- Internal `VerifierCommitment` keeps the integer indexes. Byte-identical recipe_digest linkage.

This removes the precise cognitive mapping that made `verifier_intent` the historical
release gate failure.

### 2b.3 `compile_implementation_contract` tool_catalog

Drop the redundant `"tool_index"` key from each `tool_catalog` entry (line 269). The
runtime invoke protocol already keys on `tool_id` (the name). The index is pure noise.
No compile change (nothing parses it back).

---

## Execution order

1. **Now (parallel):** Batch 2b (candidate.py) — independent file, dispatch immediately.
2. **After Batch 1 agent finishes + verified:** Batch 2a (design.py shared_tool + curriculum).
3. **Verify:** `uv run pytest -q` (all design + candidate tests) + ruff + mypy.
4. **Node-level E2E:** resume-from each changed node to confirm one-shot success.
5. **Commit** after green.

## What stays unchanged

- All internal dataclasses (`RuleDraft`, `CurriculumFamily`, `VerifierCommitment`,
  `SharedToolContract`, `TaskRequirement`). Indices live here, framework-owned.
- Validator accept/reject semantics (same rules, name-resolved at compile boundary).
- Artifact DAG, byte-identical committed artifacts (name→index resolution is deterministic).
- Pipeline topology, runtime execution, judge/integration deterministic logic.

## Expected impact

Every LLM/agent interface becomes name-based, shallow, example-backed. The cognitive
mapping that caused `verifier_intent` (and earlier `local_tool_semantics_mismatch`,
`candidate_snapshot_projection_mismatch`) failures is removed at the source.
