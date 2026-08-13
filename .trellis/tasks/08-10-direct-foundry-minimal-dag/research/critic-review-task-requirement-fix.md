# Cross-Layer Critic Review — TaskRequirement feedback + corrections fix

- **Reviewed plan**: `repair-task-requirement-feedback-and-corrections.md` (this dir)
- **Scope**: internal (code read-only verification)
- **Date**: 2026-08-12
- **Verdict**: **allow**

## Decision

**allow** — both changes are safe to implement. Fix A is a message-text-only edit
to a shared validator; Fix B is a one-line retry-budget raise inside the range
the code already permits. Neither touches the
`EnvironmentRequest -> Research -> Design -> Task/Verifier -> Builder -> Runtime
-> Judge -> Registry -> Observe` path.

## Verification matrix (each plan claim vs. real code)

### Fix A — `_array` message text (`agent_world/design.py:179-187`)

| Plan claim | Code evidence | Result |
|---|---|---|
| `_array` is a shared array validator | Used by `_compile_rules` (design.py:363,373,440,515), `_compile_task_rules` (555), `_field` (294), and directly by `_direct_architecture`/`_direct_curriculum`/`_direct_tasks` compilers — i.e. all 6 `direct_llm` design nodes | CONFIRMED |
| Only `violated_condition` string changes; reject condition unchanged | Current: `if not isinstance(value, list) or not minimum <= len(value) <= maximum` (design.py:180). Proposed keeps the identical boolean. `expected_category` stays `"array"` (design.py:185). | CONFIRMED |
| No logic / contract / Artifact ABI / routing / persistence change | `_object` (design.py:166), `_compile_task_rules` (537-573), `RuleDraft`/`TaskRequirement` contracts all untouched. `DesignError` ctor and `CorrectionPacket` shape unchanged (design.py:76-97). | CONFIRMED |
| Message is rendered as opaque feedback text, not parsed | `_direct_feedback` (design.py:111-137) interpolates `correction.violated_condition` into a string at line 116. No regex/parse on it. | CONFIRMED (with caveat below) |

### Fix B — `task_requirement` `local_corrections` 1 -> 2 (`agent_world/graph.py:209-218`)

| Plan claim | Code evidence | Result |
|---|---|---|
| `local_corrections=2` is code-legal for `direct_llm`+`direct` | `NodeSpec.__post_init__` (graph.py:69-75): `local_corrections in {0,1,2}` and `==2` requires `(execution_kind,route)==("direct_llm","direct")`. `task_requirement` is `direct_llm`+`route="direct"` (graph.py:210-217). | CONFIRMED |
| Sibling node already uses 2 | `curriculum_plan` uses `local_corrections=2` (graph.py:207); `tool_semantics` also uses 2 (graph.py:185). Two precedents, not one. | CONFIRMED |
| No new retry platform / second control plane | Retries flow through the existing bounded loop `for ordinal in range(1, node.local_corrections + 2)` in `GraphRunner.execute` (graph.py:494). Fix B only changes a dataclass field value. | CONFIRMED |

### Zero test breakage

| Check | Evidence | Result |
|---|---|---|
| Old string referenced in tests | `grep -rn "array must use the declared cardinality" tests/` -> no hits (only at definition site design.py:184) | CONFIRMED no breakage |
| Tests asserting `_array` message via a variable | Parametrized test `test_world_architecture_invalid_source_is_typed_and_persisted` (test_design_semantics.py:2201-2206) sets expected `"violated_condition": error.correction.violated_condition` — self-referential, binds to whatever the error actually produced. A text change cannot break it. | CONFIRMED no breakage |
| `expected_category:"array"` assertion sites | All 14 sites pair `expected_category:"array"` with custom post-`_array` messages ("entity names and references must be closed", "family tools must be unique frozen indexes", "use every input tool_indexes member exactly once...", etc.) — none bind to the `_array` cardinality text. | CONFIRMED no breakage |

### Minimality (no over-design)

| Check | Evidence | Result |
|---|---|---|
| No strict JSON schema bundled | Plan section 6 defers it explicitly as a backstop-only non-goal. | CONFIRMED |
| No input slimming bundled | Plan section 6 defers it to a separate follow-up. | CONFIRMED |
| Smallest coherent scope | Two edits, both node-local, no cross-node contract change. | CONFIRMED |

### Diagnosis grounded in real artifact

The plan cites `run_9ab2d5fe14fb4584b86d1c85d96ef744`. That run artifact lives in
a gitignored state_root outside the repo, so it cannot be independently
re-verified from tracked files (grep for `9ab2d5fe` hits only the plan itself).
However the diagnosis is internally consistent with the code: `effects` arrays
are validated `[1..6]` (design.py:440; `_TASK_RULE_DRAFT_SHAPE` line 347), the
`task_requirement` node defaults to `local_corrections=1` (graph.py:49 + 209-218),
and the failure mode (fix one error then exhaust budget on the next) matches the
bounded loop semantics. Acceptable for a node-local repair.

## Caveats (non-blocking — implementer should note)

1. **`violated_condition` is compared, not just rendered.** The plan states the
   message "is not parsed by any downstream code". It is in fact compared for
   equality inside `GraphRunner._eligible_local_correction` (graph.py:713-723) as
   one field of a 4-tuple used to detect no-progress (identical consecutive
   corrections). This is benign under Fix A: two genuinely identical array
   errors (same min/max/actual) still yield an identical message so the dedup
   still fires; two different array errors now yield different messages and are
   correctly treated as progress-eligible (an improvement over the old behavior
   where two different cardinality violations collapsed to the same opaque
   string and could be falsely deduped). No regression — but the plan's
   blast-radius wording should be read as "not semantically parsed", not "never
   read".

2. **Preserve type annotations in the Fix A snippet.** The plan's code block
   drops the existing annotations (`value: object`, `minimum: int`, etc. and
   `-> list[Any]`). The implementer should keep the current signature at
   design.py:179. The `actual = len(value) if isinstance(value, list) else None`
   line is safe — `len()` is only evaluated inside the `isinstance` guard.

3. **Two sibling precedents, not one.** The plan cites only `curriculum_plan` as
   the precedent for `local_corrections=2`; `tool_semantics` (graph.py:185) also
   uses 2. Strengthens (does not weaken) the consistency argument.

## Files inspected (read-only)

- `agent_world/design.py` — `_array` (179-187), `_object` (166-176), `_direct_feedback` (111-137), `_compile_rules` (351-534), `_compile_task_rules` (537-573), `DesignError` (76-97)
- `agent_world/graph.py` — `NodeSpec` + `__post_init__` (38-82), `task_requirement` NodeSpec (209-218), `GraphRunner.execute` loop (494-569), `_eligible_local_correction` (684-723)
- `tests/test_design_semantics.py` — parametrized assertion sites (654-657, 769-772, 1369-1372, 1422, 1714-1718, 2096-2098, 2125-2186, 2201-2206, 2377-2378, 2519-2552)
- `.agents/skills/agent-world-cross-layer-critic/SKILL.md` — review standard
