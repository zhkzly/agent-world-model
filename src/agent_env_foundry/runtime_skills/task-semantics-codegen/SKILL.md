# TaskSemantics Code Author

Checkpoint A has not yet activated this revised author contract. Do not run this
Skill until the Host models/decoders and `TASK_SEMANTICS_CONTRACT.md` schema have
landed together and passed their contract tests.

You write only the standalone release-local semantic project in the assigned
workspace. The Framework already created the uv project and immutable inputs.

Read completely before editing:

1. `EXPECTED_TASK_SEMANTICS.json`
2. `PUBLIC_SURFACE.json`
3. `TASK_SEMANTICS_CONTRACT.md`
4. the read-only `candidate-view/` needed to decode native state

Implement `generated_task_semantics.release:make_semantics` plus diagnostic
tests. Own the release-specific native decoder, deterministic StartCases,
CapabilitySpecs, binding enumeration and atomic/condition evaluation logic.

Do not write manifests, digests, verdicts, Tasks, rewards, witnesses or package
receipts. Do not import/call actor business code as an oracle. Do not encode the
authoring `candidate-view` path into runtime code. Do not weaken an expected
Requirement because implementation is inconvenient.

You may edit semantic source, tests and dependency declarations. Framework code
runs lock/sync/build/tests, validates the frozen catalog, checks import
separation and later performs physical Qualification. A final response has no
authority; finish after the project bytes are complete.
