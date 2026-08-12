# Diagnosis — boundary purpose storage policy is assigned to the LLM

## Expected behavior

Luna should propose the business meaning of the environment boundary. Designer
framework should compile storage/schema mechanics and reserve corrections for
semantic invalidity, not spend the only correction on arbitrary prose length.

## Real scene and chronology

Run `run_1b81e19380194e13a406f10dfcf3d0df` reused the same real 28-claim,
6-citation evidence class that triggered the first full-run failure. The revised
shape explicitly disclosed 160 characters and the first correction repeated the
exact bound. Both complete Luna responses nevertheless failed only at
`$.boundary.purpose`; the second exhausted the correction. Observe has a failed
Designer WorkRecord, one blocking Finding, no architecture output and no
release.

## Attribution

The prior hidden-contract diagnosis is no longer sufficient. The model saw the
rule and exact feedback. Provider transport, JSON response, token ceiling and
sparse SourceDraft compiler all operated normally. The remaining mismatch is
ownership: the LLM owns free-form business purpose, while a framework storage
limit of 160 characters is being treated as semantic proposal validity.

Names, categories, finite domains, actor scope and entity references affect
identity/execution and must remain rejected when invalid. Boundary purpose is
descriptive prose; deterministic trim/bounding does not grant the model or
framework new semantic authority and prevents a low-value formatting issue
from consuming the semantic correction budget.

## Repair boundary

Normalize only `boundary.purpose` locally: require a nonempty string, strip it,
and deterministically retain its first 160 Python characters in the compiled
WorldBoundary. Remove the numeric hard-rejection/correction for excess purpose
length and describe the field to the model as concise business purpose with
framework-owned bounded storage. Do not normalize identity fields, touch shared
`_text`, change another node, add retries, split the node or add a schema/prompt
system.

This diagnosis authorizes no edit or provider retry.
