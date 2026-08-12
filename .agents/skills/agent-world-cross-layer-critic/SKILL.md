---
name: agent-world-cross-layer-critic
description: "Review an Agent World implementation or repair plan after it is written and before any logical change. Use for a real failure's repair plan or for changes to node contracts, model input, wiring, artifacts, retries, runtime, Judge, package, Registry, or Observe; decide whether the plan is local, coordinated cross-node, or a larger slice, give allow/block/needs_human, and prevent node-local fixes from breaking the natural-language-need-to-EnvironmentPackage path."
---

# Agent World Cross-Layer Critic

Use this as a development gate, not as a Foundry runtime component. It never
becomes a CriticNode, Judge, release authority, Artifact ABI, retry loop, or
second control plane. An `allow` only permits the next implementation step; it
is never a Gate, Finding, RepairAction, Judge result, or release evidence.

## Preserve the product target

Start every review by restating this target:

> Turn an arbitrary natural-language EnvironmentRequest into an
> evidence-grounded executable environment, independently verify it in a real
> isolated boundary, publish an immutable Registry EnvironmentPackage, and
> expose only safe facts through Observe.

For system-level plans, preserve the two additional product paths: Expand uses
real evidence and one or more exact released parents to produce diverse new
packages through the same Design/Build/Judge/Release path; Consumer turns exact
released packages into isolated public Episodes for SFT/RL without gaining
environment, reward, or release authority.

The relevant chains are:

EnvironmentRequest -> Research -> Design/WorldSpec -> Task/Verifier/
Implementation -> Builder -> isolated Runtime -> independent Judge -> Package
-> Registry -> Observe.

Registry parents + technical evidence -> ExpandCampaign -> the same Design/
Build/Judge/Release path -> new Registry package -> Observe.

Exact Registry package -> Suite -> private materialization + isolated Episode
-> public trajectory -> SFT/RL + Observe.

A committed graph node, green unit test, provider smoke, or package-shaped file
does not prove this target by itself. Direct remains the required first-package
path. Expand and Consumer are separate child paths: include them when the plan
changes their shared handoffs, but never pull them into a node-local Direct
repair merely to make the review look comprehensive.

## Use the correct order

This skill reviews a plan. It does not diagnose a raw failure.

- For a real failure: Observe -> agent-world-debugging -> persisted Diagnosis
  Record -> repair-plan revision -> this critic -> implementation only after
  allow -> agent-world-real-execution-proof -> Observe.
- For a requested change with no failure: write or update the implementation
  plan -> this critic -> implementation only after allow.
- A role-play trace may help agent-world-debugging reconstruct chronology, but
  it does not replace diagnosis or this post-plan gate.
- After every real proof terminal, successful or failed, read Observe. A new
  failed scene begins a new diagnosis; do not carry its predecessor's
  hypothesis into another repair.
- Read-only investigation needs no critic. If investigation requires a
  semantic, permission, route, persistence, public-entry, validation, or
  control-plane behavior change, create a plan and review it before editing.
  Formatting, spelling, or comment-only changes do not need a new gate.

Do not convert a failed scene directly into a patch or a retry. If diagnosis
cannot establish a causal hypothesis, plan only the smallest observability
improvement and submit that plan here.

## Read the plan and its real boundaries

Read task JSONL context, prd.md, design.md, implement.md, AGENTS.md, the
source-of-truth document, relevant specs, and the latest Diagnosis Record or
Observe scene when applicable.

Trace both directions of the changed boundary:

producer -> changed handoff -> immediate consumer -> later consumers -> package
-> Registry -> Observe

Also trace the upstream assumptions that created the changed value. Check the
actual model-facing projection, NodeContext inputs, in-memory reads, persisted
artifacts, owner capabilities, dependency closure, package entries, Registry
receipt, and safe Observe facts. Type or ref closure alone is not proof that a
downstream model or program can consume the required semantics.

List every affected domain graph/subsystem before reviewing. Review all of
those graphs together when a shared contract crosses them; for an unaffected
graph, require concrete compatibility evidence instead of forcing edits. The
Critic itself is never one of those graphs or nodes.

Classify the smallest coherent scope:

- Local: the external meaning is unchanged and each relevant consumer is proven
  compatible.
- Coordinated cross-node: a producer/consumer schema, semantic meaning,
  ownership, evidence, or lifecycle changes; include all affected nodes in one
  plan.
- Larger slice: core product truth or release behavior changes; split into
  honest vertical slices with explicit non-claims.

Do not approve a local patch merely because it makes the current node pass. Do
not create a new general framework component when an existing boundary, task
record, or test expresses the necessary plan.

## Review questions

Answer all of these against the proposed plan:

1. Which part of the product target does it advance?
2. Which producer, consumer, downstream node, owner, and Artifact change or
   stay unchanged? What exact compatibility evidence supports every unchanged
   consumer?
3. Is the new output semantically consumable, not merely structurally valid?
4. Does each changed field, evidence, gate, retry, and release decision retain
   one framework owner? Can a model falsely claim downstream completion?
5. Are request, revision, dependency, evidence, secrecy, and authority
   preserved through the downstream chain?
6. Is the scope honest? For a Direct-only repair, does it preserve future
   Repair/Expand/Consumer handoffs without implementing them? For an approved
   multi-child plan, does it coordinate every actually affected graph while
   leaving unrelated children unchanged?
7. What is the smallest deterministic regression check, smallest true-boundary
   proof, and the honest remaining non-claim?

Keep deterministic regression evidence, provider/live node evidence, and
end-to-end product proof distinct.

## Persist a bounded decision

Derive a plan digest from the complete written plan revision. Write one task
research record named research/cross-layer-review-<short-plan-digest>.md. It is
a development record, not a runtime CriticReport. Include:

- Decision: allow, block, or needs_human.
- Plan digest, plan revision, scope classification, and revision count.
- Trigger, Diagnosis/Observe evidence, and affected trust boundary.
- Repeated product target, impact chain, owners, compatibility facts, and
  unproved consumers.
- The smallest allowed implementation and proof plan.
- Deterministic checks, true-boundary proof, explicit non-claims, and next
  permitted gate.

Never record Prompt bodies, credentials, sealed data, or runtime control
fields. The main planner adds a current allow record to both implement.jsonl
and check.jsonl before dispatching implementation or checking. A chat claim of
approval is not enough.

An allow expires when its plan digest, affected trust boundary, or latest
relevant real scene changes. Re-submitting the same plan digest after block is
no progress. New evidence or a broadened scope starts a new plan lineage.

## Decide and feed back

Return exactly one result:

- allow: the plan is the smallest coherent scope and makes the required
  downstream compatibility/proof explicit.
- block: the plan is node-local despite a cross-boundary change, lacks a
  consumer/owner/evidence fact, or hides a failure without advancing the
  product target.
- needs_human: an unresolvable product, credential, risk, or release-policy
  decision is missing.

For block, give the plan writer actionable feedback: failed criterion, missing
or contradictory fact, affected producer/consumer/downstream chain, smallest
scope change or alternative, forbidden shortcut, and the next test/proof.
The plan writer revises the plan only, links the feedback it addressed, then
submits it again. Do not dispatch an implementation agent while blocked.

Allow at most two plan revisions for the same Diagnosis Record and plan
lineage. If it remains blocked, record the unresolved contract and return
needs_human rather than cycling.

Use an independent fresh, read-only trellis-research subagent when the plan
crosses a Controller, Scheduler, Repair, Budget, or Release boundary; changes
the public composition root; spans two or more of FoundryController,
EnvironmentDesigner, EnvironmentBuilder, EnvironmentJudge, and
EnvironmentRegistry; or follows a failed real Direct/E2E run. The main session
may perform a local review only when the scope is demonstrably local. The
reviewer never edits the plan or production files.
When the task declares a reviewer model, every spawn must pass provider and
model explicitly; never rely on inheritance from the main session.

## Guardrails

- Do not add a runtime CriticNode, CriticReport ABI, extra Registry artifact,
  second Judge, or second ReleaseKernel.
- Do not force unrelated nodes into a patch; coordinate only real contract
  dependencies.
- Do not substitute prompts, retries, fixtures, compatibility paths, or a
  weakened validator for a framework-owned invariant.
- Do not let implementation broaden the approved plan. Stop, update the plan,
  and review again when a new producer/consumer impact appears.
- At a key node/child/proof/release boundary, append the required Product
  Alignment Checkpoint. It records what the evidence proves and does not turn
  partial progress into product completion.
