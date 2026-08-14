# Diagnosis Record 10: integration drives guards-violating arguments

Date: 2026-08-14 (session)
Real event: offline bench + latest resume design. The regenerated design
(8 recipes, new tools) has precondition guards with VALUE CONSTRAINTS, e.g.
search_rate_options "At least one adult is required" (adults >= 1). The
framework's _run_recipe generates argument values via _value (integer -> 0),
so the success path violates the guard -> precondition_guards mismatch.

## Root cause

The integration driver does not construct guard-satisfying arguments: it
cannot drive the success path of tools whose preconditions constrain
argument VALUES. Guards are correct design content; the driver is incomplete.

## Fix direction

Guard-guided argument generation in _run_recipe: start from _value defaults,
then adjust arguments per precondition predicates (eq -> set constant;
ge/gt/le/lt -> shift into range; ne -> vary; exists -> keep non-empty).
Deterministic and bounded (~30 lines).
