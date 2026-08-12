# Research: cross-layer review 734a274a

- Query: Fresh independent read-only C2 review of the complete-v1 difficulty
  closure across Direct, Repair, Expand, Consumer, Registry/package, and
  Observe.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `734a274a6b3092f0b526530fd264d105dd65bf068b1aee74fe67984219d7f117`.
- Plan revision: `complete-v1-difficulty-closure` C2, revision 1 after the
  Direct C1 block `baddd746...`.
- Scope classification: coordinated cross-node contract closure across the
  shared Direct producer and its Repair, Expand, package/Registry, Consumer,
  and safe Observe consumers. This is a planning review only; it introduces no
  runtime route, graph node, framework authority, Judge, Registry, or release
  path.
- Trigger: the prior fresh Direct critic blocked C1 because the required
  downstream difficulty selection had no finite framework-owned producer. No
  failed real proof or Observe scene is being repaired.

## Digest And Reviewed Scope

I independently recomputed all sixteen declared raw SHA-256 values and the
newline-terminated aggregate. They exactly reproduce the C2 aggregate above.
The reviewed inputs are the parent `prd.md`, `design.md`, and `implement.md`;
the Direct `prd.md`, `design.md`, `node-contracts.md`, and `implement.md`; and
the PRD/design/implementation documents for Repair, Expand, and Consumer.

The predecessor parent allow `bdb327da...` remains relevant only as a
development-dispatch gate. The predecessor Direct record `baddd746...` is
closed by this C2 plan revision, not reused as authorization.

## Product Target And Impact Chain

The target remains to turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in
an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
expose only safe facts through Observe. Expand must create new packages through
the same Design/Build/Judge/Release path from evidence and exact released
parents. Consumer may use exact released packages only through isolated public
Episodes without environment, reward, or release authority.

The C2 producer/consumer chain is now explicitly closed:

```text
CurriculumPlanSourceDraft
  -> framework DifficultySchema compiler
  -> TaskRequirement (direct dependency and schema digest)
  -> MaterializationRequest / exact MaterializerResult echo
  -> Integration and independent Judge
  -> tasks/curriculum.json + protocol + manifest
  -> Registry cold-read / immutable EnvironmentPackageRef
  -> rebuilt Expand child Design or Consumer EpisodeRequest
  -> safe Observe contract commitments
```

`curriculum_plan` is the sole semantic producer: it proposes 1..6 ordered
dimensions and 2..5 ordered levels per dimension; framework code validates
their finite unique domain and canonical order, then commits one per-family
schema ([node-contracts.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:408)).
The closed `DifficultySelection` rejects missing, extra, reordered, duplicate,
and out-of-domain values before candidate execution
([node-contracts.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:445)).

`task_requirement` consumes the frozen schema read-only; its semantic revision
binds the schema digest and its direct `CurriculumPlanRef` dependency makes a
dimension, level, meaning, or ordering change invalidate that task requirement,
Modeling Gate, EnvironmentDesign, and CandidateGraph descendants while retaining
unaffected task-family coordinates
([node-contracts.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:476)).
This supplies the exact dependency edge that Repair needs to compute its
append-only descendant invalidation from immutable `WorkRecord.dependency_refs`
([08-11-foundry-bounded-repair/design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-11-foundry-bounded-repair/design.md:60)).

The untrusted candidate is only an exact-echo consumer; it cannot author,
widen, coerce, or select the domain. Framework validates both the admitted
request and returned ordered echo, then alone renders the public instruction,
binds the private evaluator goal, and supplies private reset state
([node-contracts.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:657)).
Package bytes carry the exact per-family schemas and digests, and Registry
cold-read revalidates agreement among curriculum, TaskRequirement, protocol,
and manifest ([node-contracts.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:724)).

Expand re-enters the same DesignGraph and requires a newly compiled child
schema; parent schemas are semantic evidence only and cannot be unioned or
inherited ([08-11-foundry-expand-multiparent/design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-11-foundry-expand-multiparent/design.md:88)).
Consumer cold-reads the exact package schema and verifies its digest against
TaskRequirement, protocol, and manifest before Materializer invocation; it
defines no parallel domain ([08-11-foundry-consumer-sft-rl/design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-11-foundry-consumer-sft-rl/design.md:71)).
Observe remains a read-only projection of schema commitments and safe lifecycle
facts, with no private values or control methods
([08-11-foundry-complete-v1/design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-11-foundry-complete-v1/design.md:167)).

## Owners And Compatibility Facts

- The Designer framework owns schema compilation and persistence; Direct LLM
  owns only bounded semantic names and meanings. Candidate code and callers
  own neither schema definition nor validation.
- Integration/Judge and Consumer share the same schema/selection validator,
  while Judge remains the independent release-evidence owner. Package/Registry
  retain their existing cold-read and publication roles.
- Repair re-derives owner and invalidation from immutable subject/dependency
  provenance; this revision neither grants it schema authority nor implements
  its controller early.
- Expand must rebuild a complete child Curriculum/TaskRequirement contract;
  parent source reuse remains Builder-only after child Design commit and does
  not transfer parent verdicts.
- Consumer retains a private Materializer-to-Runtime `initial_config` handoff;
  difficulty is public task selection only, and framework still owns reward and
  termination.

These facts satisfy the prior block without a permissive mapping, fixed
difficulty fixture, candidate-defined level set, Consumer-only schema, extra
schema service, second Judge/Registry, or new runtime authority.

## Smallest Allowed Proof Plan

1. Deterministically prove schema compilation, exact ordered validation,
   duplicate-aware parsing, TaskRequirement dependency/invalidation closure,
   exact Materializer echo, paired-level semantic or initial-state difference,
   package/Registry cold-read, and safe Observe projection.
2. In the Direct true boundary, use a real generated candidate to materialize
   two admitted selections for one task family, reject an invalid selection
   before candidate/release use, then run the existing isolated Integration and
   Judge sequence.
3. In later children, prove one rebuilt Expand child uses its own schema and
   one Consumer Episode accepts that same released schema while retaining the
   private reset handoff. Repair proof remains a separate real negative-to-
   repaired lineage with Observe read after both terminals.

The stated Direct plan includes these deterministic cases and the two-valid/
one-invalid materialization boundary ([08-10-direct-foundry-minimal-dag/implement.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md:295)).

## Non-Claims And Next Permitted Gate

This allow proves only that the C2 written plan is the smallest coherent
producer/consumer closure. It does not prove a real Direct release, a repair,
an Expand campaign or multi-parent child, a Consumer episode, SFT/RL output,
provider availability, or product completion. No product proof, Observe scene,
code change, manifest change, test execution, or runtime-route modification was
performed in this review.

Next permitted gate: add this matching allow record to the appropriate
implementation/check contexts and implement the Direct child only within the
reviewed C2 scope. Any change to the 16-file digest, difficulty trust boundary,
or relevant real execution scene expires this allow and requires a fresh review.

## Caveats / Not Found

- The review is intentionally limited to the written plan and cross-layer
  contract. The exact concrete serialization/code API must still be reconciled
  against the completed Direct implementation before the dependent child
  critics run.
- No external reference was required. The canonical source, execution map,
  parent/child plans, and predecessor decisions supplied the applicable
  authority.
