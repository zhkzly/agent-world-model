# Minimal plan — retain complete boundary-purpose semantics

- Lineage: `world-architecture-purpose-normalization`, revision 2/2
- Diagnosis: `diagnosis-world-architecture-purpose-policy-mismatch.md`
- Addresses: `cross-layer-review-5bf0e4ba-purpose-normalization.md`
- Scope: one local WorldArchitecture compiler block, its disclosed shape, one
  task-contract wording clarification, and focused regressions

## Product target and ownership

The target remains an arbitrary natural-language `EnvironmentRequest` becoming
an evidence-grounded executable environment, independently verified in an
untrusted process and atomically published as an immutable Registry
`EnvironmentPackage`; Observe exposes only safe durable facts. This repair only
unblocks the WorldArchitecture proposal boundary and proves none of the later
Design, Candidate, Judge, Registry, Repair, Expand, or Consumer path.

The Direct LLM owns the business meaning of `boundary.purpose`. Designer owns
closed shape validation, whitespace normalization, Artifact commit, and the
single authorized correction. The framework continues to own every identity,
schema, route, retry, Gate, release, hash, size, and provenance field.

## Authoritative non-lossy policy

Use the existing task-wide text ceiling from `node-contracts.md`: after one
Python `str.strip()`, purpose must be nonempty and contain at most **4096 Python
Unicode code points**. The phrase “4096 UTF-8 characters” in that task document
will be clarified to this exact unit; bytes and user-visible grapheme clusters
are not counted. Python `len(stripped)` is the check. Because over-limit text is
rejected rather than sliced, a combining sequence or ZWJ sequence is never
split by framework storage.

Every accepted purpose is stored completely after stripping. There is no
first-160 truncation, summarizer, second field, raw-text side channel, or lossy
projection. A 161-character nonempty purpose is valid and reaches all consumers
unchanged. The unchanged 160-code-point limits apply only to `boundary.name`,
`system_of_record`, and `authority`.

This is the non-lossy alternative required by the revision-1 critic. It avoids
an arbitrary display/storage policy while retaining a finite task-contract
safety bound. It does not generalize or change shared `_text`.

## Exact local change

1. In only `_direct_architecture.compile`, require `boundary.purpose` to be a
   `str`, strip it once, reject an empty result, reject more than 4096 Unicode
   code points, and store the complete stripped result.
2. The exact purpose-related shape fragment becomes:

   ```text
   boundary:{name|system_of_record|authority:stripped_text[1..160],purpose:stripped_text[1..4096_unicode_code_points],actors[1..8]:stripped_text[1..80]:unique_after_stripping}
   ```

   The full current sparse `Field` grammar and every entity/tool/divergence
   fragment remain byte-for-byte unchanged. The shape does not describe a
   framework projection because accepted text is not transformed beyond strip.
3. The exact correction tuple for a non-string or whitespace-only value is:

   ```text
   code = world_architecture_invalid
   path = $.boundary.purpose
   violated_condition = value must be text with nonempty content after stripping
   expected_category = string
   ```

   The exact correction tuple for more than 4096 code points uses the same
   code/path/category and:

   ```text
   violated_condition = stripped value must contain at most 4096 Unicode code points
   ```

   Both remain ordinary proposal defects under the existing one-correction
   policy. A valid 161+ proposal makes one Direct call and receives no
   correction.
4. Clarify only the ambiguous unit sentence in `node-contracts.md`; do not
   change any dataclass, Artifact kind, NodeSpec, Edge, route, model, retry,
   helper, module, or shared validator.

## Consumer and identity closure

The committed `WorldArchitecture.boundary.purpose` remains a `str`, but now
contains the complete accepted semantic description. Its canonical payload and
digest therefore bind exactly that full stripped text. Existing consumers stay
on the same field and receive the same committed value:

- `world_rules` and `curriculum_plan` receive `json_value(architecture)`;
- Candidate Build receives the full architecture projection inside the frozen
  Design input;
- Package persists the same value in `world/world_spec.json` and Registry
  cold-read rechecks those bytes;
- ModelingGate and downstream Artifacts bind the changed Architecture ref and
  digest.

No deterministic Runtime or Judge branch executes this prose. Identity and
execution fields remain strict and unnormalized. The WorldArchitecture
semantic material already includes the rendered `output_shape`, and
`GraphRunner.semantic_revision` hashes that material; changing the accepted
shape therefore rotates semantic identity. An Architecture accepted under the
old 160 rule cannot be silently reused under this revision.

## Deterministic checks

Add or update focused tests proving:

1. the recipient sees the exact split boundary shape above and all sparse-field
   and non-purpose limits are unchanged;
2. a non-string and whitespace-only purpose produce the exact correction tuple,
   then an unchanged invalid second proposal produces one failed WorkRecord;
3. a stripped 161-character ASCII purpose commits in one call with no
   correction and is persisted in full;
4. multibyte and combining-code-point input is counted by Python code points,
   stripped first, retained exactly when at or below 4096, and a 4097-code-point
   value receives the exact bounded correction without truncation;
5. the changed shape produces a new WorldArchitecture semantic revision while
   NodeSpec, edges, route, and one-correction policy remain unchanged;
6. the Artifact payload plus representative WorldRules/Curriculum, Builder,
   and package projections all receive the same full committed value, never the
   raw surrounding whitespace or a 160-character prefix;
7. all identity/execution-field rejection and sparse SourceDraft regressions
   remain green.

Run focused and full pytest, Ruff format/check, mypy, compileall, inspect the
diff, and recount production Python. Production Python must remain at or below
10,298 lines; delete obsolete local condition text rather than adding an
abstraction.

## True-boundary proof

After a fresh matching critic `allow` and independent implementation check:

1. invoke WorldArchitecture once with the same real 28-claim/6-citation
   evidence class;
2. inspect its exact WorkRecord, committed Artifact and Observe scene, proving
   the full accepted purpose and absence of correction/truncation;
3. only then run one fresh public Direct CLI request toward Registry and inspect
   terminal Observe.

Any different terminal begins a new Observe-driven diagnosis. No retry,
fallback model, extra correction, node split, or broader child implementation
is authorized by this plan.
