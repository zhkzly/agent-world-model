# Knowledge Extraction

Extract source-grounded environment knowledge from accepted source evidence.

Rules:

- Produce state objects, operations, business rules, verifiable fields, and uncertainties.
- Preserve source references on extracted facts.
- Use `object_id` for state object identifiers.
- Use `operation_id` for operation identifiers.
- Mark inferred rules explicitly with `confidence: inferred`.
- Do not invent live external services, credentials, or hidden state.
- Uncertainties that block implementation should be explicit and marked blocking.

Accepted output target: `KnowledgePack` fields only.
