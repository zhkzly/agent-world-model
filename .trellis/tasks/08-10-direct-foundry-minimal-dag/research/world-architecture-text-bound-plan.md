# Minimal plan — disclose WorldArchitecture text bounds

- Lineage: `world-architecture-text-bound`, revision 2/2
- Diagnosis: `diagnosis-e2e-world-architecture-text-bound.md`
- Scope: one WorldArchitecture-local purpose precheck, one shape literal, and
  focused tests

## Exact change

1. Keep the sparse Field/actor source protocol unchanged. Add one compact clause
   to the existing WorldArchitecture `output_shape` disclosing only currently
   enforced facts:
   - boundary name/purpose/system-of-record/authority: stripped nonempty text
     <=160 characters;
   - boundary actors: 1..8 stripped nonempty text values <=80 characters,
     unique after stripping;
   - entity names: stripped nonempty text <=64, unique in `entities`; entity
     purposes: stripped nonempty text <=300;
   - tool names: stripped nonempty text <=64, unique in `tools`; tool purposes:
     stripped nonempty text <=300;
   - Field names: stripped snake names <=64; present `entity_ref` values are
     untrimmed snake names <=64, with the existing entity-only closure rule;
   - divergence statements: stripped nonempty text <=500.
   Preserve all existing cardinality, sparse-key, category, relation, actor and
   citation instructions. State no character bound for enum/list `values`,
   because the compiler has none. Do not introduce a rendered schema
   abstraction.
2. Leave shared `_text` unchanged. Replace only the existing
   `boundary.purpose` `_text(..., 160)` call with a local equivalent precheck:
   after confirming a string, strip it, require length 1..160 Python
   characters, and otherwise raise the same `world_architecture_invalid` at
   `$.boundary.purpose`/`string` with the exact condition "stripped value must
   be nonempty text of at most 160 characters". Accepted values and normalized
   output remain byte-for-byte equivalent. No other Agent/Direct correction,
   Prompt, semantic identity or persisted feedback changes.
3. In `tests/test_design_semantics.py`, assert the actual WorldArchitecture
   recipient shape includes all exact current limits/normalization/uniqueness
   facts, explicitly preserves the entity/tool relation distinction and adds no
   enum/list value character cap, while the sparse protocol remains intact. Add
   one first-invalid/second-valid sequence with a 161-character stripped
   `$.boundary.purpose`; prove the single correction names `160`, the second
   call receives the identical frozen shape/projection, and the valid proposal
   commits the existing Artifact/WorkRecord. Do not add a generic schema test
   utility.
4. Preserve every NodeSpec, edge, input projection, dataclass, Artifact kind,
   route/model, retry/correction budget, downstream consumer and configuration.
   Production Python must remain <=10,299 lines; replace text in place rather
   than add helpers or modules.

## Verification

- Focused and full pytest, Ruff format/check, mypy, compileall, diff check and
  exact production line count.
- Fresh independent implementation check.
- First run one fresh WorldArchitecture Direct proof using the same real
  need/evidence class and read its WorkRecord/Observe. Only after it passes,
  run one fresh full CLI natural-language run and read Observe. A different
  failure begins a new diagnosis; a later-node pass/failure is not silently
  attributed to this repair.

No Candidate, Judge, Registry, Repair, Expand, Consumer or E2E success is
claimed by this plan.
