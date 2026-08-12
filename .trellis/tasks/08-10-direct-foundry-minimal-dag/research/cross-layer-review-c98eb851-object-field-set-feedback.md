# Cross-layer review — expected closed-object fields in Feedback

- Decision: `allow`
- Plan digest: `c98eb85128760cdff40a0b7566dc6090659834b8f59a19bb8899639d347d3238`
- Plan revision: 1
- Scope: local shared compiler-to-Direct-Feedback wording
- Reviewer: independent `trellis-research`, `gpt-5.6-terra`, reasoning `max`

## Trigger and product target

Frozen-parent run `run_16b5772c5d2c45d787ec3057b4b3a96c` produced two
parsed Luna proposals that failed the identical closed-field-set condition at
`$.families[0]`; no Curriculum or release committed. The product target remains
an arbitrary natural-language need compiled into an executable Candidate,
isolated independent Judge pass, immutable Registry `EnvironmentPackage`, and
safe Observe. This repair advances one required Design leaf only.

## Impact and compatibility

`_object` remains the deterministic producer of one correction condition. The
existing Feedback renderer sends that safe condition as the next `user`
message to the same Direct node; the same compiler then revalidates the complete
replacement. Every later compiled Curriculum/Task/Candidate/Judge/Registry
consumer is unchanged because field-set acceptance, error code, path, expected
category, schemas, Artifact payloads and graph edges do not change.

Only sorted framework-owned expected field names enter the condition. Actual
model keys/values, raw output, Provider content and credentials remain
ephemeral and unpersisted. The shared helper is the smaller coherent scope:
all of its callers implement the same closed-object condition, while a
Curriculum-only branch would duplicate diagnostic logic without changing
acceptance.

## Smallest permitted implementation and proof

- Change only `_object`'s existing condition to list sorted expected fields.
- Update exact affected assertions and add one Curriculum family-field
  regression.
- Do not change Prompt/projection/schema/model/route/retry/node/edge or any
  downstream ABI.
- Run focused tests, serial full checks, and an independent implementation
  review.
- Then replay only the exact frozen-parent Curriculum leaf and read Observe.

## Non-claims and next gate

This allow proves no Luna result, Curriculum commit, downstream Design,
Candidate, Judge, Registry, E2E, Repair, Expand or Consumer path. The next gate
is the bounded implementation and deterministic check; only a subsequent
implementation `allow` permits the single live replay.
