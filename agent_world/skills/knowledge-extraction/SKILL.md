# Knowledge Extraction

Extract source-grounded environment knowledge from accepted source evidence.

Rules:

- Produce state objects, operations, business rules, verifiable fields, and uncertainties.
- Preserve source references on extracted facts.
- Use `object_id` for state object identifiers.
- Use `operation_id` for operation identifiers.
- Mark inferred rules explicitly with `confidence: inferred`.
- Do not invent live external services, credentials, or hidden state.
- For local executable environments, convert under-specified but safe policy details into explicit deterministic defaults in business_rules or verifiable_fields when they can be fixture-backed.
- Uncertainties that block implementation should be explicit and marked blocking.
- Do not mark fixture-backed local defaults as blocking; blocking is only for missing human permission, credentials, external service access, or ambiguity that cannot be resolved without changing scope.

Accepted output target: `KnowledgePack` fields only.
