# LLM Boundary Redesign Plan — Domain Model ≠ LLM Interface

Date: 2026-08-13
Status: Design (not yet implemented)
Scope: Redesign all LLM-facing input/output interfaces to add a projection layer between
the framework's internal domain model and what the LLM/agent actually sees.

## 1. Root cause (why current design fails)

Every LLM node failure in the E2E has been a variant of the same problem:
**the framework's internal domain model is exposed directly as the LLM's I/O
interface, without a projection layer.**

| Failure | Domain model exposed | LLM-friendly alternative |
|---|---|---|
| public_goal (path,category) | JSON-pointer + category tuple | nested dict with example shape |
| ordering/compensation | field names implying numbers | "STRINGS, not numbers" |
| difficulty_has_no_semantic_effect | difficulty semantics unstated | "difficulty must change goal values" |
| snapshot index vs name | tool_index vs tool_name | "use NAME, not INDEX" |
| local_tool_semantics_mismatch | binding.path vs trace structure | (structural bug, now fixed) |
| rule IR semantic_index | positional index into binding catalog | field NAME reference |

Pattern: each fix was a **tactical patch** (shape template, guidance sentence, scaffold).
The root fix is a **systematic projection layer**.

## 2. Research evidence (2025-2026)

### Anthropic Context Engineering Guide
[Source](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- "Find the smallest possible set of high-signal tokens"
- "Tools define the contract... input parameters must be descriptive, unambiguous,
  and play to the inherent strengths of the model"
- "Return token-efficient information"
- Context rot: every token depletes attention budget; more tokens = worse recall

### DeepJSONEval Benchmark (arXiv 2025)
[Source](https://arxiv.org/html/2604.25359v1)
- Schema compliance ≠ semantic correctness ("gap is real, large")
- Depth ≥3 schemas significantly degrade accuracy
- Model size does NOT predict structured output quality (Phi-4 14B beat GPT-5 on text)

### Context Engineering Guide
[Source](https://www.promptingguide.ai/guides/context-engineering-guide)
- "Transform data into LLM-friendly format before passing to context window"
- "Generate schema from examples rather than exposing internal data structures"
- "Don't assume LLM will correctly interpret complex internal schemas without examples"

### Martin Fowler on Context Engineering
[Source](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html)
- "Build context gradually, not pump too much stuff in right from the start"
- "Don't indiscriminately dump information into context"

## 3. Design principles (from research + user analysis)

### Principle 1: LLM value = semantic uncertainty resolution
LLM handles: fuzzy intent → typed interpretation; cross-text semantic judgment;
information extraction/normalization.
LLM does NOT handle: index assignment, path construction, ID generation, state
machine transitions, deterministic routing.

### Principle 2: Domain Model ≠ LLM Interface
Internal: rich, nested, indexed, general-purpose.
LLM-facing: shallow (≤2 levels), readable field names, task-specific, with examples.
Framework bridges the two with a projection layer.

### Principle 3: Deterministic info = framework-owned
Anything the program can compute (index, path, digest, tool_index, metadata,
default values) should NOT be in LLM output. Framework fills it.

### Principle 4: LLM difficulty ≈ structure complexity × field count × semantic
similarity × conditional dependency × reasoning difficulty
Not just JSON nesting depth. Wide flat schemas with many similar fields are also
hard. Minimize all factors simultaneously.

## 4. Concrete redesign: per-node projection

### Design nodes (LLM generates rules/specs)

**Current rule IR (exposed to LLM):**
```json
{
  "when": [{"left_semantic_index": 3, "operator": "eq",
            "right": {"kind": "literal", "value": "pending"}}],
  "effects": [{"target_semantic_index": 5, "operation": "set",
               "value": "active"}]
}
```
- Depth 3+, abstract index, union types, ~10 semantically similar operators.

**Projected LLM output (shallow + readable):**
```json
{
  "when": [{"field": "status", "is": "pending"}],
  "effects": [{"field": "status", "set_to": "active"}]
}
```
- Depth ≤2, field NAMES (not indices), simple operators.
- Framework compiles: `"status"` → lookup binding catalog → semantic_index →
  build PredicateDraft/EffectDraft with correct internal structure.

### Candidate build (agent writes runtime/materializer)

**Current:** implementation-contract includes full binding catalog (indices, paths).
**Projected:** contract includes only:
- Tool names + their argument/result field names + categories.
- Snapshot expected shape (tool_name → field_name → category).
- Difficulty dimensions/levels (readable names).
- NO binding catalog, NO semantic_index, NO path tuples.

### Integration check (framework evaluates rules)

**Current:** binding.path walks trace (structurally misaligned, now fixed).
**Projected:** resolve by field NAME directly:
- `trace["argument"]["member_id"]` not `trace["argument"]["1"]["member_id"]`.
- Or keep internal path resolution but ensure trace structure matches (already fixed).

## 5. Implementation plan (phased)

### Phase 1: Rule IR projection (highest impact)
1. Add a projection function: `project_rule_for_llm(rule, bindings)` → shallow
   JSON with field names.
2. Add a compile function: `compile_llm_rule(shallow_json, bindings)` → RuleDraft
   with semantic_index resolved from field name.
3. Update design node output_shape to use the projected format.
4. Update `_rule_matches` to work with both formats (backward compatible).

### Phase 2: Binding catalog projection
1. Add `project_bindings_for_llm(bindings)` → readable list of
   `{source, tool_name, field_name, category}` (no index/path).
2. Update implementation-contract to use projected bindings.
3. Update codegen skill to reference field names.

### Phase 3: Simplify tool_semantics/task_requirement schemas
1. Reduce PredicateDraft/EffectDraft to field-name-based format for LLM.
2. Keep internal RuleDraft for judge/integration (deterministic).
3. Framework maps between the two.

## 6. What stays unchanged

- Framework internal: RuleDraft, SemanticBinding, binding catalog, _rule_matches,
  judge, integration logic. These are deterministic and correct.
- Node pipeline: DesignGraph → CandidateGraph structure.
- Artifact DAG: immutable committed artifacts.
- Validator logic: accept/reject decisions unchanged.

## 7. Expected impact

- LLM one-shot success rate: significantly higher (shallow schemas + readable
  references, per DeepJSONEval evidence).
- Debugging: errors reference field NAMES (readable), not indices (opaque).
- Maintenance: projection layer is the single place where domain model ↔ LLM
  interface mapping lives. Changes to either side don't leak.
