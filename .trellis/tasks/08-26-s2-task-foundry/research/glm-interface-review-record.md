# Claude Code / GLM Interface Review Record

Date: 2026-08-28

Harness: Claude Code 2.1.250

Model reported by harness: `glm-5.3`

Trellis channel: `s2-interface-glm-review`

Claude session: `c62c4e7e-f301-4c6d-8f98-fc4376006098`

Review mode: independent, read-only

## Scope

The reviewer received and checked:

- `PROJECT.md`;
- implemented S1 source code;
- both S1 E2E evidence JSON files;
- the current S2 PRD and semantic design;
- `external-ai-interface-review-packet.md`.

It was instructed not to edit files, write code or turn the current S2 proposal
into implementation authority.

## First verdict

`MODIFY` for external publication.

The reviewer found no fabricated implemented S1 interface. It independently
verified signatures, dataclasses, descriptor key sets, digest rules, error
taxonomy, evidence identities/counts and the attachment SHA-256 values.

Required packet accuracy corrections were:

1. describe the Host-frozen/LLM-authored/physical-negative Qualification
   boundary;
2. distinguish Qualification-attested state isolation from loader enforcement;
3. label cross-run framework equality as host-attested;
4. label the generated project tree representative while keeping the outer root
   closed;
5. label broad real ToolSpec output schemas host-observed;
6. name task-truth anti-circularity controls;
7. separate proposed setup rules from rules already in the S2 PRD/design.

## S2 findings to preserve for external discussion

- Public `prepare_release/open` is missing and gates S2/S3/third-party use.
- Fixed generated package names plus `importlib` loading require one isolated
  interpreter/process per prepared release, or strict serialization.
- S2 pilot trials mechanically overlap the future S3 acting loop; ownership and
  reuse must be decided before implementation planning.
- Package-asset identifiers currently have only candidate-authored prose as an
  anchor.
- StartRecipe business-refusal and scarce-state setup semantics are absent.
- Broad output schemas reduce static Graph binding discrimination; executed
  observations must remain truth.

Suggested deletion candidates:

- duplicate StartRecord reload/replay and ToolSpec-surface fields;
- separate `weak` versus `independent` edge labels;
- persisted `state_precondition_candidate` labels before a Task asserts order;
- `QuarantinedCandidate` as a persistent lifecycle unless pilot sealing remains
  an S2 responsibility.

## Follow-up verdict

The reviewer re-read the corrected packet and returned `MODIFY` for two final
local issues only:

1. the physical-negative rule requires at least one matching assertion flip per
   Requirement, not every assertion;
2. setup-refusal/scarce-state rules must be marked packet-proposed amendments,
   not current S2 rules.

Both corrections are applied in the packet. The reviewer stated that no other
content blocks external publication.
