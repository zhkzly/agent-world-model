# Minimal plan — restore the WorldArchitecture SourceDraft boundary

- Lineage: `world-architecture-source-draft-minimal`, revision 2/2
- Diagnosis: `diagnosis-world-architecture-source-draft-overexposed.md`
- Scope: the existing WorldArchitecture Direct output projection, its local
  compiler normalization, and focused tests

## Exact change

1. Keep one Direct LLM call and the current need/evidence input. Render exactly
   this sparse field-source grammar:
   - `name`, `category`, and semantic `required` are always present;
   - `values` is present, unique and nonempty only for `enum`/`list`;
   - `entity_ref` is present and non-null only for an actual relation.
   The closed category set is hardcoded framework policy; the model selects a
   business kind and supplies only domain-specific finite values. Its Boolean
   `required` is the business presence decision retained in
   `FieldDeclaration.required`, not a model-authored JSON Schema `required`
   array. Framework remains the only future assembler of such schema keywords;
   this repair neither adds nor proves a Draft-2020-12 schema artifact.
2. In the existing local field compiler, require the three base keys and allow
   only the two conditional keys. Normalize omitted `values` to `()` and
   omitted `entity_ref` to `None` in the compiled dataclass. Reject an omitted
   finite domain, empty/duplicate/non-text finite values, any scalar `values`
   key including `[]`, any explicit `entity_ref: null`, unknown keys, malformed
   names/categories/Boolean presence, and malformed references through the
   existing path-addressed `world_architecture_invalid` `DesignError`. Preserve
   the current closure distinction: entity-field references must resolve to a
   declared entity; tool-field references remain snake-name-only. No `KeyError`,
   dataclass `ValueError`, compatibility spelling, or generic schema/helper
   layer is allowed.
3. Replace the model-facing tool key `actor_indexes` with `actor_names`: a
   nonempty, unique, ordered list of exact names from the already normalized
   and uniqueness-checked boundary actor tuple. One local deterministic
   transformation maps each name through that frozen tuple to its existing
   one-based `ToolSurface.actor_indexes`, preserving source order. Reject
   numeric `actor_indexes`, unknown names and duplicates through the same
   correction/failure transaction; no source-only key reaches the committed
   Artifact.
4. Preserve `FieldDeclaration`, `ToolSurface`, `WorldArchitecture`, semantic
   catalog, coupling plan, NodeSpec, graph edges, Artifact kinds, downstream
   projections, one-correction limit, Luna/Spark routes and all configuration.
   No compatibility branch accepts the old model-facing shape as a separate
   protocol.
5. Update only focused fixtures/assertions to prove:
   - scalar fields with both `required=True` and `required=False` omit
     `values`/`entity_ref`, compile to `()`/`None`, and preserve the Boolean;
   - enum and list finite values plus one actual entity relation survive as
     business semantics, with entity/tool reference closure unchanged;
   - a two-actor proposal deliberately selecting names in non-index order
     compiles to the matching ordered one-based indexes, while neither
     `actor_names` nor sparse placeholders reach the committed projection;
   - omitted enum/list values, scalar `values` including `[]`, explicit null
     reference, invalid relation, old numeric `actor_indexes`, unknown actor
     name and duplicate actor name all remain typed and persist a failed
     WorkRecord after the existing correction budget;
   - the actual recipient shape contains the sparse conditional grammar, no
     required empty/null placeholders, and no numeric actor-index instruction.

## Minimality and proof

- Prefer deletion/replacement over adding abstractions; add no type, module,
  node, edge, Skill, retry, schema package or config. The measured production
  baseline is 10,297 lines. Run
  `find agent_world -type f -name '*.py' -exec wc -l {} +` before and after;
  the replacement must be net at most two production lines (10,299 total),
  deleting old full-key/index checks as needed. Test lines do not satisfy this
  cap.
- Run focused and full pytest, Ruff format/check, mypy and compileall.
- Obtain a fresh independent implementation check.
- Then run one fresh real Luna `world_architecture` transaction and read its
  WorkRecord and Observe scene. Any different terminal starts a new diagnosis.

This plan does not claim or alter Research, ToolSemantics, Candidate,
Integration, Judge, Registry, Repair, Expand, Consumer or full E2E behavior.
