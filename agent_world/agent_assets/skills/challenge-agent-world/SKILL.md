---
name: challenge-agent-world
description: Design independent data-only verification for an untrusted Agent World v2 candidate. Use to derive public, repair, and sealed behavioral cases, properties, and metamorphic checks from WorldSpec without modifying candidate code or making release decisions.
---

# Challenge Agent World

Produce verifier data that the framework Judge can execute through the public runtime protocol.

1. Derive semantic expectations from WorldSpec rules, ToolContracts, task distributions, fidelity claims, and
   declared unknowns; do not accept candidate self-tests as proof.
2. Cover handshake/schema fidelity, unseen seeds, valid and invalid transitions, permissions,
   observation boundaries, errors, idempotency, retries, rollback, concurrency, restart, and
   package-relative deployment where applicable.
3. Prefer properties and metamorphic relations over replaying one authored trajectory.
4. Emit only the requested typed, data-only Verifier IR. Do not emit Python/shell code or
   expressions requiring `eval`.
5. Keep expected assertions inside Judge-owned IR. Runtime requests contain only protocol method,
   tool arguments, seed/config, and idempotency key—never task id, case label, expected answer,
   expected state delta, or verdict.
6. Do not write the candidate, access the Engineer conversation, or claim release authority.

When the requested type is VerifierIntent, every case uses the literal
`expectations` list from the supplied output schema. Do not rename it to `checks`,
`assertions`, `properties`, or another natural-language synonym. Treat the
supplied logical output schema as the authoritative field-level vocabulary.
