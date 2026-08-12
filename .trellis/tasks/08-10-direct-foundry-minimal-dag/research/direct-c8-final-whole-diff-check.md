# Direct R9-C8 final whole-diff check

Date: 2026-08-11
Reviewer: independent `trellis-check`, Codex `gpt-5.6-terra`
Decision: allow

## Authorization and scope

- Recomputed Direct digest:
  `6ffeef3a778a5dacafca58bc5d70e4ad5d015905191d37502a790a86825680d0`.
- Recomputed parent digest:
  `7c3d0bafc67f28abe5eb713849e3c99076e2d44c0bf403f28f4746dcd4207b2f`.
- Both match the two C8 digest records and the current matching independent
  `allow` in `cross-layer-review-6ffeef3a-c8.md`.
- The whole diff was reviewed from baseline
  `9562c058b61562c11f76d8127f56b68b0f5be2d9` in the clean
  `foundry-direct-graph` worktree. The changes remain within the permitted
  Direct R9-C8 provenance closure plus the preceding allowed C5--C7 closure;
  no new runtime authority, graph, scheduler, PortRef, media/plugin system,
  compatibility reader, Repair, Expand, Consumer, public Observe, Judge,
  release-policy, prompt, or Runtime Skill path was introduced.

## C8 and prior-closure review

- `ArtifactEnvelope` commits a nonempty, unique `output_ports` tuple and
  `ArtifactStore.read_envelope` cold-reads the closed persisted shape.
- `GraphRunner` commits the fixed `NodeSpec.output_ports`. For every edge-bound
  input it cold-reads the envelope, requires the exact graph and producer node,
  requires the committed tuple to equal that producer's fixed `NodeSpec` tuple,
  and requires the exact declared `EdgeSpec.source_port`. Its flattened
  dependencies remain duplicate-free, including one valid envelope consumed on
  two logical ports.
- Bindings stay limited to JSON and the existing zip package bytes; malformed
  or unsupported media fails closed. No media registry or compatibility path is
  present.
- `research_synthesis` binds the acquisition `sources` and `citations` ports;
  `task_requirement` binds architecture, all tool semantics, curriculum, and
  rules; and `modeling_gate` binds evidence, architecture, all tool semantics,
  curriculum, task, and rules.
- Package and Registry WorkRecords bind the actual verifier, semantic and
  implementation lineage, exact Design/Candidate WorkRecords, and Registry's
  actual physical package, dossier, and telemetry refs. The false
  `package.dossier -> registry.dossier` edge is absent. Registry still
  cold-verifies the package closure, dossier, telemetry, lineage, Integration,
  Judge, and verifier commitments before publication.
- The C5--C7 deterministic closures remain intact: exact graph inputs,
  correction and Runtime response closure, sealed verifier/candidate isolation,
  supply-chain/package cold checks, secret-safe telemetry/provenance, and the
  legacy firewall. Focused tests cover the hostile wrong-port substitution,
  multi-output fan-out, JSON/zip binding behavior, and complete
  Package/Registry WorkRecord inputs.

## Verification

- `uv run pytest`: pass (`91 passed`).
- `uv run ruff format --check .`: pass.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass (`13 source files`).
- `uv run python -m compileall -q agent_world`: pass.
- `uv run pytest tests/test_legacy_firewall.py`: pass (`2 passed`).
- `git diff --check 9562c058b61562c11f76d8127f56b68b0f5be2d9`: pass.

## Non-claims

This static whole-diff allow does not prove a real Direct LLM or Codex Agent
invocation, live research/provider route, generated CandidateBuild, isolated
candidate/Integration/Judge execution, Registry publication, safe Observe
release projection, or an E2E EnvironmentPackage. It authorizes only the
ordered real Direct proofs already specified by the task; it does not authorize
Repair, Expand, Consumer, training, prompt/Skill, public API, or release-policy
work.
