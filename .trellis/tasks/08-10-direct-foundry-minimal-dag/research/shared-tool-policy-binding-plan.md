# Plan — bind one shared policy to frozen tool coordinates

- Diagnosis: `diagnosis-shared-tool-policy-coordinate-echo.md`
- Revision: 1/2
- Scope: local Direct source/compiler projection simplification

## Minimal implementation

1. In `agent_world/design.py`, change only SharedTool source
   `error_policy` from an exact `group_size` string array to one stripped
   nonempty shared-policy string of at most 280 code points. Compile it by
   pairing the same model-authored text with each member of the existing frozen
   ordered group.
2. Preserve the compiled `SharedToolContract.error_policy` tuple, digest
   payload, exact partition checks, graph, route and one-correction/two-call
   bound. A wrong source type still fails at `$.error_policy` as `string`.
3. Align only the SharedTool source card in `node-contracts.md` and focused
   existing tests/helper proposals. Prove source has no frozen coordinate echo,
   compiled per-member pairs remain present, ToolDraft/ModelingGate/Candidate/
   Registry consumers remain compatible, and semantic revision changes.

## Authority

- Direct LLM: one shared policy's business meaning plus all other shared
  semantic fields.
- Framework: frozen member coordinates, deterministic repetition/binding,
  validation, digest, Work/Artifact, Judge and release.
- Agent/candidate: unchanged; no Skill, tool, workspace or candidate process at
  this Direct node.

Do not add optional overrides, union shapes, normalization, a helper/module,
new field, retry, Agent, graph node, compatibility path or later-child code.
Per-tool semantic errors remain in existing ToolSemantics `errors[]`.

## Checks and proof

Run focused/full pytest, firewall, Ruff, mypy, compileall, diff check and the
production-line ceiling; then obtain an independent implementation allow. Run
only the same immutable-parent Luna SharedTool plus first ToolSemantics suffix
and read Observe. A pass permits one fresh public Direct E2E; a failure starts a
new diagnosis.

Non-claims remain complete Design, Candidate, Judge, Registry, E2E, Repair,
Expand and Consumer/SFT/RL until separately proven.

