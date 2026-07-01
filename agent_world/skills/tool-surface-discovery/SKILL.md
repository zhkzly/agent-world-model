# Tool Surface Discovery

Plan logical tools and concrete tool surface candidates for generated environments.

Rules:

- Keep logical tools separate from concrete surfaces.
- Tool ids must match accepted environment operations.
- Reads and writes must reference known state entities.
- `parameters` is a flat catalog list, not a map keyed by tool id.
- Every graph edge must declare `dependency_type` as `strong`, `weak`, or `independent`.
- Every tool must include input/output schemas, reads, writes, side effects, errors, and idempotency.
- Prefer python callable as the required first-slice surface unless evidence demands another surface.
- Do not use a generic shell executor as an environment tool surface.
- MCP, CLI, HTTP, API/SDK, database, and Python callable surfaces are allowed when justified.

Accepted output target: `LogicalToolGraph` or surface-related fields only.
