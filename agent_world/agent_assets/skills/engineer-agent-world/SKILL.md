---
name: engineer-agent-world
description: Design, implement, or repair an Agent World executable environment from typed Foundry artifacts. Use for WorldSpec/design synthesis, real Runtime and Task Materializer v3 code generation, or same-session candidate repair without evaluator authority or sealed evaluation.
---

# Engineer Agent World

Build a real programmatic environment whose observable behavior is defined by `WorldSpec`.

## Design mode

1. Use evidence claims for real-world facts; mark unsupported choices as bounded product
   decisions or unknowns.
2. Define state, ToolSurface, ToolSemantics, transition constraints, permissions, observations,
   errors, idempotency, transactions, rollback, concurrency, and task distributions together.
3. Keep tasks, runtime behavior, and verification requirements derived from the same WorldSpec.
4. Return exactly the requested structured contract version.

## Closed evidence-claim binding

`evidence_claim_catalog[*].claim_id` is a closed enum for every
`evidence_claim_ids` field. Copy an id byte-for-byte from that frozen catalog only after checking
that it supports the factual statement. Never mint, rename, infer, or describe a claim id from the
business meaning, a field name, a tool name, or a desired policy. Do this final literal check for
every evidence binding before returning the typed artifact.

For a `FidelityStatement` that records a synthetic policy or a bounded choice with no factual
support, do not invent an evidence id merely to populate the field. Leave `evidence_claim_ids`
empty only where that requested schema permits it, and state the required bounded divergence or
unresolved limit. Fields whose requested schema requires at least one evidence id must instead use
one or more exact frozen catalog ids.

## Tool-semantics scalar observations

When authoring `ToolSemanticsBatchSourceDraft`, the following are **one non-empty string**, never
an object, list, Rule, evidence record, or nested explanation:

- `errors.errors[*].observation`
- `access_observation.permission.denied_observation`
- `reliability.idempotency.duplicate_observation`

Write each as one concrete user-visible sentence, then mechanically check its JSON type is a
string before returning. Keep every `errors.errors` array non-empty and return exactly the frozen
one- or two-tool batch; do not compensate for a scalar field by nesting another schema fragment
inside it.

## Tool-semantics Rule clause closure

For every `ToolSemanticsBatchSourceDraft` Rule clause, choose fields from its exact operator branch:

- `equal`, `not_equal`, `contains`, and `not_contains` use `clause_id`, `operator`, `left`,
  `right`, and optional `negate`; they **must omit** `ordering`.
- `greater_than`, `greater_or_equal`, `less_than`, and `less_or_equal` require `ordering` exactly
  once as `number`, `date`, or `date-time`.

Before returning, mechanically inspect each clause: never copy `ordering` from a comparison clause
onto an equality or containment clause. The output objects are closed; a field legal for one
operator is still forbidden on every other operator.

Lookup keys use one flat, closed variant. For a reference key, use
`bound_lookup_by_reference` with the single composite `binding_id` listed in
`lookup_reference_binding_groups`; never combine a lookup alias with a separate reference alias.
For a literal key, use `bound_lookup_by_constant` with one lookup `binding_id`, `key_value_type`,
and `key_value`. Never emit `key_binding_id`, a nested `key`, arithmetic as a key, another lookup
as a key, or raw reference/pointer fields.

## Build mode

1. Read only Builder-visible artifacts. Never search for or infer sealed cases, expected answers,
   case labels, or release decisions.
2. Create a complete project in the assigned workspace with `pyproject.toml`, `uv.lock`, a
   non-empty `LICENSE` declared by `[project].license` and file role `license`, a parameterized Task
   Materializer v3 callable, standalone public-test scripts, and a real Runtime. Do not create candidate,
   Judge, envpkg, SBOM, supply-chain, or release manifests/results; framework code derives those
   only after physical inspection.
3. Keep the uv root virtual and non-installed (`[tool.uv] package = false`); use only locked
   registry wheels that Judge can install offline without source builds or network access.
4. Implement `agent-world.runtime.v2` over stdio JSONL: handshake, reset, invoke, snapshot, close.
   Runtime inputs are task-agnostic; state transitions occur in program code.
5. The materializer returns only the exact v3 call echo, typed `public_goal`, and
   `initial_config`. It never authors an instruction, evaluator goal, answer, expected output,
   solution trace, or evaluation witness; framework code renders/projects/verifies those.
6. Support unseen seeds, entity identifiers, valid parameters, and action sequences. Do not use
   fixed replay maps, environment-id branches, fixture registries, generated `verify()`, mocks,
   stubs, or template-only success.
7. Make every public test directly runnable as `.venv/bin/python relative/test_path.py` with no
   network or writable source tree. Run the real build and public tests. Their results support
   repair and failures block release, but their content never authorizes a PASS verdict.

## Repair mode

Modify the existing candidate in the same workspace and thread. Address disclosed Findings
without weakening contracts, detecting tests, embedding expected values, or bypassing a gate.
