# Diagnosis Record 12: design transition sets scalar into list field

Date: 2026-08-14 (session)
Trigger: cross-layer-review-24da00b3 block + direct frozen-head verification.

## Evidence (verified)

- Frozen search_rate_options result_fields: rate_options category list
  (values [available_rate_option]).
- Frozen transition[0] effects: set rate_options "returned_rate_options"
  (scalar into a list field) — a DESIGN defect, projected into the rendered
  runtime, causing candidate_property_mismatch at integration.
- The materializer is clean; the prior diagnosis misattributed the producer.

## Root cause

The modeling gate validates rule SHAPES but not effect-vs-field CATEGORY
consistency; the Direct LLM can emit scalar values for list fields and the
gate accepts them.

## Fix direction

Modeling-gate category gate in the tool_semantics compile: for every
transition/postcondition effect, verify the value matches the target field's
declared category (set: scalar for scalar fields, list for list fields, enum
membership for enums; increment/decrement numeric; add/remove list targets).
Violation -> tool_semantics_invalid with an actionable violated_condition
naming the field, its category, and the offending value; the node's
local_corrections=2 loop re-prompts the Direct LLM.
Bump tool-semantics prompt id (@3 -> @4) so frozen shards recompile under the
gate on resume.
