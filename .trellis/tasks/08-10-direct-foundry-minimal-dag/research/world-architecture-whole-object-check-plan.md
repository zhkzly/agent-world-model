# Minimal plan — make the WorldArchitecture whole-object contract actionable

- Lineage: `world-architecture-whole-object-check`, revision 2/2
- Diagnosis: `diagnosis-e2e-world-architecture-whole-object-regression.md`
- Real scene: `run_fac8d0b2961842c996837d2f035e3102`
- Addresses: `cross-layer-review-ef4dae84-world-architecture-whole-object.md`
- Scope classification proposed: local Direct prompt-contract clarification

## Product target and role ownership

The target remains an arbitrary natural-language need becoming an
evidence-grounded executable environment, independently exercised as an
untrusted candidate and atomically published as an immutable Registry
`EnvironmentPackage`, with safe facts exposed through Observe. This plan only
repairs the Research-to-WorldArchitecture boundary and proves none of Candidate,
Judge, Registry, repair, Expand, multi-parent evolution, or Consumer/SFT/RL.

The Direct LLM continues to own only semantic choices: boundary, entities,
field meanings expressed through the sparse categories/domains/references, a
coherent tool surface, and cited divergences. Framework code continues to own
all cardinalities, closed keys, IDs, schema compilation, hashes, attempts,
validation, route, Finding, Judge and release. No semantic tool or entity is
hardcoded.

## Exact minimal change

1. In `_direct_architecture`, retain the current input projection, compiler,
   output fields, `1..8` tool policy, one correction, and all downstream types.
   Make the existing model-visible `shape` readable enough to add exactly these
   generation rules:
   - choose a coherent minimal tool surface and emit a JSON array of one through
     eight tools; combine closely related workflow actions rather than exceed
     the bound;
   - for every Field collection, omit `entity_ref` when no relation is intended;
     for `entities[*].fields[*]` only, a present `entity_ref` must copy exactly
     one `entities[*].name` emitted in the same object;
   - for `tools[*].argument_fields[*]` and `tools[*].result_fields[*]`, retain
     the current optional snake-name actual-relation form; it is not required to
     name a declared entity;
   - before returning, and after applying any correction, recheck the complete
     object against every disclosed field, cardinality, uniqueness, reference,
     actor and citation rule.
2. Do not create a prompt builder, schema generator, additional parameter,
   helper, node, retry/progress subsystem, or configuration option. This remains
   one local constant assembled beside the compiler it describes.
3. Update only the WorldArchitecture section of `node-contracts.md` so its
   human-readable source draft names the actual sparse fields and distinguishes
   entity-field declared-name closure from the optional external relation name
   accepted in tool argument/result fields. Do not change the canonical product
   document or claim the task file is runtime input.

The model still returns all business semantics. It never returns IDs, indexes,
hashes, byte sizes, Artifact refs, schemas, WorkRecords, Findings, route choices,
Judge results, or release decisions; those remain deterministic framework work.

## Compatibility and identity

The compiled `WorldArchitecture`, its Artifact kind, all edges, downstream
SharedToolSemantics/ToolSemantics/WorldRules/Curriculum inputs, CandidateBuild,
Package and Registry payloads remain unchanged. The prompt/output-contract text
is part of `semantic_revision`, so old Architecture work cannot be silently
reused under the clarified contract. Repair/Expand can still consume the same
typed Architecture; Consumer remains downstream of an exact released package.

## Verification

Focused tests must prove:

1. both initial and correction requests expose the exact whole-object rules;
2. the existing sparse field grammar and all compiler bounds remain unchanged;
3. an invalid entity reference still receives the same exact correction and a
   second invalid proposal still fails without a third invocation;
4. a valid architecture with eight tools commits, while nine tools remains
   rejected—prompt wording does not weaken framework authority;
5. an external `entity_ref` in a tool argument/result field remains accepted,
   while an external `entity_ref` in an entity field remains rejected;
6. the wording change rotates WorldArchitecture semantic identity while node,
   edge, route and retry topology remain unchanged.

Then run focused/full pytest, Ruff format/check, mypy, compileall, diff check and
the production-line count. Keep production Python at or below the current
10,296 lines; replace wording rather than add an abstraction.

## Real proof

After an independent fresh Terra/max critic `allow` and independent code check:

1. invoke only WorldArchitecture once against the frozen evidence Artifact from
   the failed E2E and inspect WorkRecord/Artifact/operation/Observe;
2. only if it passes within the existing two attempts, run one fresh public
   Direct request through Registry and inspect terminal Observe;
3. any different terminal starts a new Observe-driven diagnosis. No blind
   retry, output editing, model fallback, extra correction, or later-child work
   is authorized here.
