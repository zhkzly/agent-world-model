# Goal-First S2 Design Audit

Status: planning review, not implementation evidence

Branch reviewed: `s2-task-foundry`

## Verdict

`CONDITIONALLY IMPLEMENTABLE`

The redesigned S2 can be expressed as ordinary typed Python, real release-local
code generation, deterministic compilers and physical execution gates. It is not
credible if implemented only on top of the current actor API and public docs.
The essential condition is the clean S1 v2 handoff described in the PRD/design:
an independently qualified protected SemanticsBundle containing parameterized
capability atoms, deterministic starts, state inspection, binding enumeration
and atomic evaluation.

The strongest unsupported claim remains:

> S2 can inspect an arbitrary opaque post-hoc environment and automatically
> recover all natural Task meanings and reliable native verifiers.

The plan does not make that claim. It fails closed on worlds whose Task truth
cannot be independently qualified.

## Why the design is code-realizable

| Concern | Concrete implementation mechanism |
| --- | --- |
| user intent | Brief Requirement IDs and qualified capability intent/workflow anchors |
| concrete Task parameters | release-local `start_cases` + `enumerate_bindings` |
| non-trivial start | frozen checker evaluates false before planner execution |
| solvability | public-only model planner, Host trace, provenance-closed recipe, fresh replay |
| outcome truth | release-local atomic evaluator physically qualified by S1 |
| composed truth | deterministic bounded GoalProgram checker compiler |
| wording | canonical typed renderer plus leakage/round-trip audit |
| false acceptance | atomic physical negatives plus S2 composition/answer/process challenges |
| diversity | semantic AST/facet/state/binding/difficulty fingerprints and corpus budgets |
| training value | independent actor trials and matched-budget held-out downstream evaluation |

No item requires a universal state schema, a hard-coded domain branch or an LLM
Judge as final truth.

## Required implementation interpretations

### 1. Extend existing Qualification; do not create an Agent organization

`Semantic Author` means an extension of the current Builder-independent S1
Qualification authoring route. It is not a new chain of Researcher, Critic,
Reviewer and Arbiter Agents.

The existing Qualification already freezes expected relations before exposing a
read-only candidate view and already separates model-authored semantic probes
from Host-owned identities, execution and verdict. S1 v2 should reuse that
mechanism to emit a reusable semantics package rather than duplicate it.

### 2. Capability composition needs an explicit workflow contract

`CapabilitySpec` must include an environment-local, Brief-anchored
`workflow_anchor` or equivalent composition contract. Sharing an actor or having
non-conflicting write scopes is not enough to prove that two goals form one
natural user request.

The deterministic compiler may compose different capabilities only when the
qualified semantics explicitly license their relation. Otherwise it may create
multiple atoms of the same capability over different bindings, or reject the
composition.

This field is semantic metadata, not a framework domain category. S1
Qualification must verify that its anchor maps to accepted Brief relations.

### 3. Conditional Tasks require qualified public conditions

An `If` node may use only a `ConditionSpec` declared by the release and proven
publicly observable. A business refusal seen accidentally in one reference trace
cannot be promoted into Task semantics.

### 4. Checker compilation must remain closed

Every supported GoalProgram node must have one Host-owned compiler rule. If a
candidate needs arbitrary generated Python to express its success condition, the
Blueprint is unsupported under the current contract rather than admitted through
an ad hoc verifier.

### 5. Public planning failure is not a proof of impossibility

A successful witness proves existence. `NoPublicWitness` records bounded search
failure only. Corpus yield and planner sensitivity must be reported separately
from logical Task validity.

## Good Task quality audit

### Public solvability

Satisfied by public-only planner visibility, machine-addressable argument
provenance, checker success and fresh recipe replay. Protected state is allowed
to choose a Task but cannot supply an action operand.

### Reliable verification

Satisfied conditionally by S1 physical qualification of each atomic evaluator,
checker-before-witness ordering and the S2 challenge matrix. This remains the
highest technical risk: weak semantic qualification would make every downstream
checker look precise while checking the wrong relation.

### Well-posedness

Satisfied by typed public instruction frames, deterministic rendering, unique or
explicitly set-valued selection semantics, leakage checks and independent actor
trials. Natural-language paraphrases are optional and carry no semantic
privilege.

### Non-triviality and stability

Satisfied by reset-only starts, initial checker failure, start-case replay and
semantic-key alignment across fresh instances.

### Naturalness and value

Need/Requirement/workflow anchoring prevents accidental tool-chain Tasks. It does
not mathematically prove that users will value every composition, so independent
actor behavior and downstream held-out utility remain required evidence.

### Corpus diversity

Structural fingerprints and semantic deduplication are implementable and avoid
counting paraphrases or parameter swaps as new Task types. Internal coverage is
only a sampling/accounting measure; training benefit is the external test.

## Main risks

1. **Semantic authoring burden.** Automatically creating discriminating
   capability contracts may cost nearly as much as current independent
   Qualification. This is acceptable only if the resulting atoms are reusable
   across many Task instances and compositions.
2. **Correlated semantic error.** Need interpretation, environment code and
   semantics may still share a wrong assumption. Separate contexts, frozen
   relations, physical near misses, cross-domain evidence and held-out transfer
   reduce but do not eliminate this risk.
3. **Start-space bottleneck.** Reset-only starts improve trust but make Task yield
   depend on S1's start generator. Poor start diversity must be reported as an S1
   capability limitation, not repaired by S2 native writes.
4. **Planner yield.** A capable public planner is needed to find witnesses for
   valid Blueprints. Planner failure must not silently bias conclusions about
   which Task meanings exist.
5. **Training utility.** Structural variety may still fail to improve learning.
   Matched-budget downstream results are therefore a fatal acceptance gate, not
   optional paper decoration.

## Overdesign check

Necessary new semantic concepts:

```text
qualified capability atom
bounded GoalProgram
```

Necessary support mechanisms:

```text
prepared isolated release
protected semantics bundle
checker-before-witness
public provenance/replay
challenge and corpus evidence
```

Deleted concepts:

```text
mandatory Graph lane
mandatory Programmatic lane
persistent universal tool graph
hidden setup program
per-Task unrestricted verifier generation
QuarantinedCandidate product lifecycle
LLM final judge
universal State IR
custom Registry/service protocol
```

The design should be rejected as overdesigned if implementation introduces
additional Agents, workflow engines, registries, plugins or generic DSLs without
a failing real cross-domain case that requires them.

## Planning gate

No product code or Trellis activation has been performed by this review. The
GitHub connector cannot execute the repository-local `alignment-patrol` script;
a fresh `plan-document-write` Patrol must run in the checked-out branch before
this planning package is treated as activation-ready.
