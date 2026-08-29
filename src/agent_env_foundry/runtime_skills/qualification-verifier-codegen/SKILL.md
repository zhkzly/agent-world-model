---
name: qualification-verifier-codegen
description: Author one audit-only native verifier from frozen expectations and an actor view.
---

# Qualification Verifier Code Author

Write only the standalone verifier uv project in the assigned workspace.

Read completely before editing:

1. `EXPECTED_TASK_SEMANTICS.json`
2. `PUBLIC_SURFACE.json`
3. `QUALIFICATION_VERIFIER_CONTRACT.md`
4. the read-only `actor-view/`

Implement `generated_qualification_verifier.release:make_verifier` and
diagnostic tests. Independently decode native before/after state and implement
`verify_transition` from the frozen Requirement/capability meaning.

You must not access or infer TaskSemantics source, outputs, tests or repair
history. Do not import/call actor business code as an oracle. Do not write
manifests, digests, evidence, receipts, verdicts, Tasks, rewards or release
metadata. A final response has no authority; Framework checks the project bytes.
