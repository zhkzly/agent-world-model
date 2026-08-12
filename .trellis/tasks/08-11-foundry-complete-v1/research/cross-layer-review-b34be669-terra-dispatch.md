# Cross-layer review: complete-v1 Terra dispatch amendment

- Decision: block
- Plan digest: `b34be66905d2e1f1690278da03aeddcd1d24191581ff44a6c24619c67462fd69`
- Plan revision: release-public-handoff R1; proposed development-dispatch amendment is not yet written into the 16 canonical plan inputs
- Scope classification: coordinated development-gate dispatch contract across the parent and all child implementation/check dispatches; no runtime product route change
- Revision count: 1 for the release-public-handoff lineage. This is a new bounded dispatch amendment, not a retry of the resolved package/public handoff.
- Date: 2026-08-11

## Trigger and Scope

The requested review asks whether dispatching development workers explicitly as
`gpt-5.6-terra` preserves the complete-v1 target and the Direct -> Repair ->
Expand -> Consumer sequencing/contracts. This is a planning change, not a real
runtime failure, so no Diagnosis Record or failed Observe scene applies.

The canonical target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
Complete v1 additionally requires bounded repair, evidence-grounded single- and
multi-parent expansion through the same Design/Build/Judge/Release path, and
public-only Consumer Episodes for SFT/RL without environment, reward, or release
authority.

The affected trust boundary is development-worker selection and review
attribution only. Product `direct` and `agent` InvocationBackend routes remain
separate runtime configuration and must not be changed by this amendment.

## Evidence and Plan Digest

The prescribed 16 raw plan inputs reproduce aggregate digest
`b34be66905d2e1f1690278da03aeddcd1d24191581ff44a6c24619c67462fd69`, matching
`plan-digest-release-public-r1.md` and its current allow. That allow expires if
any of those inputs change.

The R2 ABI gaps are closed in this current plan: Direct emits inert durable
`WorkRecord`, route-free framework `Finding`, and exact
`EnvironmentPackageRef` handoffs; Repair re-verifies and appends invalidation;
Campaign freezes inputs and separates execution/hard-gate/release facts; Suite
admits exact released refs and keeps reset state private. The sequencing remains
Direct -> Repair -> Expand -> Consumer, each child requiring its own exact
upstream commit/contracts and fresh critic allow.

The clean baseline commit `9562c058b61562c11f76d8127f56b68b0f5be2d9` is the
tip of `foundry-direct-graph`. Its worktree is currently dirty with task and
development-document changes, so this review treats the commit as the clean
baseline and makes no claim about the live worktree being clean.

## Blocking Dispatch-Contract Gap

The requested all-development-worker Terra selection is not represented by the
current frozen plan:

- Parent PRD R9 says ordinary implementation/check use
  `gpt-5.3-codex-spark`, with Terra only after a recorded capability/availability
  failure.
- The parent development-worker table assigns ordinary implementation and check
  to Spark; its dispatch rule likewise mandates Spark for implement/check.
- The Repair, Expand, and Consumer plans each explicitly dispatch their check
  worker with Spark. The Direct child relies on the conflicting parent dispatch
  rule.

The lineage record documents one Spark check dispatch rejected by an inherited
`reasoning.effort=max` setting and one replacement Terra check. That evidence
does not rewrite the general future-dispatch policy, identify which future
roles are covered, or establish a durable provider/model attribution rule for
all children. Treating it as an implicit blanket escalation would make worker
selection depend on chat/history rather than the frozen plan, and would leave
the parent and child directives contradictory.

## Impact Chain and Compatibility

```text
parent dispatch policy
  -> child critic / implement / check spawn identity
  -> attributed plan, check, and real-proof evidence
  -> parent child-admission and sequencing gate
  -> Direct -> Repair -> Expand -> Consumer integration evidence
```

Changing the development worker model does not alter Artifact producers,
`NodeSpec.execution_kind`, runtime AgentRoute, CandidateProcess isolation,
Finding ownership, Registry eligibility, PackageUseAdmission, release facts, or
Consumer public/private records. The framework continues to own commits,
gates, routing, invalidation, reward, termination, ReleaseKernel, Registry and
Observe. A model can never claim downstream completion merely because it is
Terra.

The existing Direct/Repair/Expand/Consumer producer-consumer contracts remain
compatible only if the amendment stays limited to explicit development dispatch
selection. No child may use the model change to skip its fresh critic, exact
upstream digest/commit binding, deterministic tests, real-boundary proof, or
Product Alignment Checkpoint.

## Required Plan Revision

Revise planning artifacts only, then derive a replacement 16-input digest and
request a fresh independent review. The smallest coherent revision is:

1. State one unambiguous development-worker matrix in the parent PRD/design and
   dispatch rules: research/critic, implementation, and check are all spawned
   with `--provider codex --model gpt-5.6-terra`, or explicitly name any
   intentionally excluded role. Preserve the required resolved model identity
   in spawn/review/proof evidence.
2. Replace the conflicting parent implement/check Spark rule and the child
   Repair/Expand/Consumer Spark check instructions. Make the Direct child
   explicit or state that it inherits the parent rule by exact reference, so no
   child relies on ambient selection.
3. Retain a clear separation between this development-time choice and runtime
   product routes (`direct`/`agent`); do not change Runtime models, agent
   Skills, permission semantics, Artifact identity, proof criteria, or release
   policy.
4. Record the Spark rejection only as capability/availability evidence for this
   amendment, not as proof of Direct, Repair, Expand, Consumer, or product
   completion. Update the plan digest record and obtain a new review before any
   implementation/check dispatch under the changed policy.

Forbidden shortcut: changing a channel/agent manifest or relying on a prior
chat failure while leaving the parent/child written instructions at Spark; using
Terra selection as a reason to relax a child-specific allow, an exact upstream
binding, or a real-boundary proof; or changing product runtime routes as part of
this development-only amendment.

## Smallest Tests and Proof

Deterministic development-gate checks after the revision:

- Parse every parent/child dispatch instruction and require an explicit Codex
  provider plus `gpt-5.6-terra` for every declared development worker role.
- Reject inherited/omitted model selection and reject any remaining Spark
  instruction in the complete-v1 parent/child dispatch surface unless an
  explicit exception is documented and reviewed.
- Verify that the runtime route table remains byte-for-byte unchanged by this
  dispatch-only revision.
- Verify each child context contains the current parent allow and then its own
  fresh exact-digest allow before its implementation/check dispatch.

No provider call or product proof is needed merely to validate the written
development dispatch rule. The next actual proof remains ordered: fresh real
Direct release; separate negative-to-repaired lineage; real documentation-
grounded single-parent Campaign; useful real two-parent child; then an
unknown-seed public Episode with one SFT export and one RL reset/step result.
Observe must be read at each real terminal.

## Non-claims and Next Permitted Gate

This block does not claim a Direct package, repair success, Campaign,
multi-parent behavior, Episode, SFT row, RL result, runtime model capability,
or end-to-end product completion. It does not authorize code, manifest, runtime
route, registry, or child-plan implementation changes.

Next permitted gate: revise the parent/child planning dispatch instructions as
above, derive a new canonical 16-file digest, and obtain a fresh independent
cross-layer review. No implementation or check worker may be dispatched under
the proposed Terra-wide policy until that review returns `allow`.

