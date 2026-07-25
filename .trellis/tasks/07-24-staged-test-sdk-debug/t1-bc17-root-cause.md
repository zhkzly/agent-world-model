# BC-17 root-cause analysis — repeated permission actor set

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Bug Analysis: duplicated `PermissionRuleSourceDraft` actor representation

### 1. Root Cause Category

- **Category**: B — Cross-Layer Contract, with an E — Implicit Assumption component.
- **Specific Cause**: The Agent-facing source contract required one permission actor set twice:
  once as `allowed_actors`, and again as the keys of
  `required_scopes_by_actor`. The compiler then rejected any non-identical
  repetition with `permission_scope_actor_coverage`. The compact prompt also
  said the scope map had to cover every frozen actor even though the core
  contract permits a permission to exclude an actor.

### 2. Why Fixes Failed (if applicable)

1. **Physical batch cap and frozen context**: correctly reduced the BC-17
   workload, but could not remove a duplicate source-contract choice.
2. **Scalar-observation Engineer skill**: correctly addressed the earlier
   scalar-shape frontier, but does not own permission actor-set mechanics.
3. **Timeout/transport diagnosis**: established bounded Direct execution and
   safe terminal categories, but did not alter the successful proposal's
   deterministic compiler contract.

Bayesian update for the current frontier:

| Hypothesis | Prior | Discriminating evidence | Updated confidence |
|---|---:|---|---:|
| H1: repeated source representation is causal | 60% | completed real turn reached only the two actor-coverage paths; source, protocol, and compiler duplicate the set | 90% |
| H2: frozen actor context is absent | 25% | batch prompt supplies the frozen boundary and explicitly discusses actor maps | 5% |
| H3: provider/model variability alone | 15% | proposal completed and failed deterministically after transport | 5% |

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Make scope-map keys the sole Agent-authored allowed-actor set; derive the core tuple deterministically. | DONE |
| P0 | Contract versioning | Bump the compact protocol and ToolSemantics validator revisions. | DONE |
| P0 | Test coverage | Reject old duplicate source input and empty maps; compile the derived core actor tuple. | DONE |
| P1 | Documentation | Record the source/core distinction in the backend specification. | DONE |
| P1 | Live evidence | Run one fresh, diagnostic-only BC-17 target after deterministic gates pass. | PENDING |

### 4. Systematic Expansion

- **Similar Issues**: `ObservationSemanticsSourceDraft` already follows the
  desired pattern: Agent authors visibility while framework derives redaction.
  The remaining `allowed_actor_ids` fields describe task semantics and have no
  duplicated map-key representation, so this evidence does not justify a
  broader redesign.
- **Design Improvement**: Agent-facing contracts should expose each business
  choice once. Mechanical core projections belong in compilers and retain
  defense-in-depth validation at the Runtime/Judge ABI.
- **Process Improvement**: A completed real proposal that reaches a new
  deterministic frontier is an **advance**, not permission for an immediate
  fourth identical request. Inspect the source/protocol/compiler path first.

### 5. Knowledge Capture

- [x] Update `.trellis/spec/agent_world/backend/index.md`.
- [x] Add deterministic source/protocol/compiler regressions.
- [x] Bind the changed contract to a new validator/protocol revision.
- [ ] Record the next fresh single-node result in the BC-17 minimum report.

`src/templates/markdown/spec/` is absent in this repository, so there is no
template mirror to synchronize. No commit was created because user approval is
required before committing.

## Follow-on v3 frontier — operator-specific Rule field closure

- **Classification**: constraint/context underdefinition in the compact
  protocol and `environment-engineer` skill, not a provider or runtime bug.
- **Evidence**: a new Grok Direct single-node proposal completed with one
  actual Agent turn and reached only safe `schema_extra_forbidden` paths where
  equality clauses carried `ordering`; the earlier permission actor-coverage
  frontier was absent. The accompanying transition-length error is plausibly a
  parser cascade from the rejected transition clauses, so it is not treated as
  an independent root cause yet.
- **Causal repair**: compact protocol v4 now states the mutually exclusive
  ordinary-vs-ordered clause fields, and the Engineer skill contains the same
  operator-specific final check. The source schema remains closed and
  unchanged; validator revisions advance with the protocol.
- **Next discriminating evidence**: one fresh Grok diagnostic run. If
  equality-ordering returns, stop v4 as an A→B→A/repeated-shape failure; if it
  disappears, classify the next precise frontier before any further run.

## Follow-on v4 frontier — lookup-key sub-ADT closure

- **Classification**: the same compact-contract/role-context class, but a
  distinct sub-ADT boundary. A lookup key is a business choice only between a
  constant and a frozen reference alias; it is not an arithmetic or nested
  expression hole.
- **Evidence**: the v4 Grok proposal removed every equality-ordering issue and
  reached one safe `schema_union_tag_invalid` lookup-key path plus the
  dependent transition-length report. The prompt mentioned the allowed forms
  but did not give the key its own closed object form; the Engineer skill had
  no lookup-key final check.
- **Causal repair**: protocol v5 names `LOOKUP_KEY` and enumerates its exact
  two object forms; the role skill mirrors the same closed-sub-ADT check.
  Deterministic schema/Pydantic regressions reject arithmetic in a lookup key.
- **Bounded stop rule**: v5 receives one fresh Grok diagnostic run. Any
  remaining compact Rule-shape blocker in that run stops BC-17 for a broader
  source-representation diagnosis rather than another local wording change.

## Follow-on v5 stop — nested lookup-key representation

- **Observed result**: the fresh v5 `tool-batch-3` request completed but retained
  `schema_union_tag_invalid` at one nested lookup key plus its dependent
  `schema_too_short`. The source `RuleDraft` still admitted more branches than
  the compact ToolSemantics protocol, so prompt prose was the only owner of the
  narrower contract.
- **Stop decision**: the v5 bounded stop fired. No further wording-only edit or
  identical request was allowed.
- **Structural repair**: v6 introduced a ToolSemantics-only closed Rule wire
  model. Raw reference/lookup terms and nested arithmetic lookup keys cannot
  inhabit it; framework code materializes its frozen choices into the existing
  general `RuleDraft` and executable core Rule IR. General WorldRules/task
  contexts retain their legitimate raw Rule vocabulary.
- **Deterministic evidence**: the causal and adjacent suite passed 111 tests;
  full-package Ruff and mypy passed. A full test run reached 691 passed and 2
  skipped with one stale Engineer-skill text assertion; the assertion was
  updated to the v6 contract and its last-failed rerun passed.

## Follow-on v6 live advance — split lookup/key alias

- **Diagnostic root**:
  `.agent-world-live/test-node-20260725T052920Z-435df16ae8de`
- **Frozen input**:
  `.agent-world-staged/semantic-prefix-20260725T022137Z-708c81ebe415`,
  scope `generate-job:694e0a1855cbbce587404d55`, target
  `design|world_behavior|tool_semantics_batch|tool-semantics-batches|tool-batch-3`.
- **Real execution**: `grok-4.5`, profile
  `sha256:6e5552a9c284ea299eb08c4b74c70ee657843e8e307b577112c2e3f57c5bc23b`,
  one completed proposal in 179,188 ms. Actual usage was 1 turn / 24,621
  tokens; unknown upper bound 8,147 tokens; reserved 1 turn / 32,768 tokens /
  2,710 seconds.
- **Terminal result**: honest diagnostic-only failure, non-releasable, with no
  retry, fallback, RepairAction, Build, Judge, Registry, or commit.
- **Frontier transition**: `2 shape issues -> 8 binding issues` is **advance**,
  not regression. Both v5 schema issues disappeared. The eight reports are four
  unknown reference-key selections plus one dependent
  `tool_rule_lookup_key_binding_required` report for each.
- **Credential audit**: actual values of `OPENAI_API_KEY` and
  `OPENAI_BASE_URL` each had zero matches in the diagnostic root.
- **Next discriminating repair**: replace the independently selected lookup
  alias plus key-reference alias with one framework-derived composite binding.
  Derive only pairs whose primary-key field and direct-reference terminal field
  have the same name and value type. This removes the second inventable alias
  without inferring business semantics or widening the prompt.

## Follow-on v7 structural repair — composite lookup/reference binding

### 1. Root Cause Category

- **Category**: B — Cross-Layer Contract, with D — Test Coverage Gap.
- **Specific cause**: v6 correctly removed recursive lookup-key shapes but still
  exposed two independently selectable aliases. Each alias was locally valid,
  while their pair was not a frozen schema fact. The source type therefore
  represented an invalid state that the materializer could reject only after a
  real Agent turn.

### 2. Why earlier fixes moved rather than closed the frontier

1. v3–v5 constrained prompt prose while the broader source union still admitted
   invalid nested forms.
2. v6 made nested shape errors uninhabitable, but flattened the same two-choice
   coupling instead of eliminating it.
3. Existing alias tests proved one-to-one alias resolution separately; they did
   not prove that a lookup and its reference key formed one indivisible choice.

### 3. Prevention mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Derive one `FrozenRuleLookupReferenceBinding` only for same terminal field name and same frozen value type. | DONE |
| P0 | Compile-time | Remove `key_binding_id` from `ToolRuleBoundLookupByReferenceDraft`; one alias selects the complete pair. | DONE |
| P0 | Contract versioning | Advance compact Rule protocol to v7 and current ToolSemantics output/transform/validator revisions. | DONE |
| P0 | Test coverage | Reject split wire objects; prove composite expansion and exclude field/type-mismatched pairs. | DONE |
| P1 | Live evidence | Rerun exactly the frozen batch-3 coordinate once through `InvocationBackend`. | PENDING |

### 4. Systematic expansion

- **Similar issues**: constant-key lookup remains intentionally two-part because
  the literal value is Agent-owned business data; its declared type is checked
  against the frozen primary-key type by the unchanged executable Rule validator.
- **Design improvement**: whenever two aliases are legal only as a relation,
  expose the relation as one frozen choice rather than asking the Agent to satisfy
  a join constraint.
- **Process improvement**: alias round-trip tests must cover relational closure,
  not only independent catalog membership.

### 5. Knowledge capture and deterministic evidence

- [x] Backend spec records the composite-binding invariant.
- [x] Focused causal and adjacent tests pass (`88 passed`).
- [x] Full mypy passes (`138 source files`); focused Ruff and `git diff --check`
  pass.
- [ ] One fresh Grok single-node result and credential-value audit.

The Trellis template mirror is absent. No commit was created because the user
explicitly requires approval before any commit or push.
