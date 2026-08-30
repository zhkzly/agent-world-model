# S2 Candidate Proposal, Semantic Freeze and V0

## 1. Scope / Trigger

Use this contract between sealed S1 Requirement obligations and public binding/
witness search. It owns the common proposal boundary, parameterized semantic
freeze and bounded V0 plan. It does not own concrete binding, instruction,
PublicClosureEvidence, witness, challenge, TaskPack or S3 reward.

## 2. Signatures

```python
compile_direct_proposals(
    *, release_id, capabilities, obligations, task_goals
) -> tuple[CandidateTaskProposal, ...]

compile_task_semantic_section(
    proposal, *, capabilities, obligations
) -> TaskSemanticSection

compile_verifier_bundle(
    semantic, *, capabilities, obligations
) -> VerifierBundle
```

## 3. Contracts

`CandidateTaskProposal/1` contains exactly sampler kind/version, Release,
Requirement/obligation IDs, objective, Goal shape, capability IDs, optional
CompositionRule/Condition, public slots and public evidence references. It never
contains a protected binding, answer value, checker result, reward or verdict.

The compiler recomputes the potentially applicable obligation set from sealed
S1 handles. Proposal IDs bind sampler/evidence lineage; `TaskSemanticSection`
identity deliberately excludes sampler and discovery evidence, so direct,
Graph and Programmatic proposals with the same meaning freeze to the same truth.

Multi-capability proposals require one exact sealed CompositionRule. V0 is a
bounded axis plan over qualified TaskSemantics:

```text
applicability
required_effects
collateral
answer
process/refusal
initial_non_vacuity
```

It contains obligation and qualified-operation IDs, never Python source or a
reference trace.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| missing or invented obligation | `applicable_obligation_coverage_mismatch` before witness |
| unknown capability/Requirement mismatch | proposal rejection |
| multi-capability without exact CompositionRule | composition rejection |
| public slots do not cover selected capabilities | proposal rejection |
| colliding AnswerField IDs | semantic freeze rejection |
| V0 catalog differs from semantic section | verifier compilation rejection |
| sampler/evidence lineage differs but truth is equal | different proposal ID, same semantic digest |

## 5. Good / Base / Bad Cases

- Good: direct and Graph evidence propose the same anchored objective and obtain
  the same semantic digest.
- Base: one qualified capability, one public slot and all potentially applicable
  obligations compile before Start or witness bytes exist.
- Bad: omit a persistence obligation because one successful trace happened not
  to test it.
- Bad: use executed adjacency as a CompositionRule or process obligation.

## 6. Tests Required

- real-derived three-obligation omission and invented-obligation rejection;
- sampler/evidence mutation changes proposal identity but not semantic truth;
- semantic identity binds objective, obligations and answer operations;
- V0 maps each obligation kind to its bounded axis;
- direct baseline emits the same `CandidateTaskProposal/1` used by later samplers;
- real cold Release direct compile repeats to an identical semantic digest.

## 7. Wrong vs Correct

Wrong:

```text
successful witness -> infer Task meaning -> build checker
```

Correct:

```text
sealed S1 obligations -> proposal coverage -> semantic freeze -> V0
-> later Start/binding -> later public witness
```
