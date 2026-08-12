# Direct live-route R1 check

Date: 2026-08-11
Reviewer: independent `trellis-check`
Decision: allow

## Scope and approval match

The checked R1 changes are limited to the approved configuration, execution-map
documentation, complete-v1 design documentation, and the existing focused
route-config test. They match the R1 digest
`e6449739e5214ec150bbac3f0776493154abb9dedacae3e324f41696738677c0` and its
allow: Direct primary is `gpt-5.3-codex-spark`; fallback is `gpt-5.6-luna`;
both use `http://localhost:8317/v1/chat/completions` and `OPENAI_API_KEY`.

The exact runtime flow remains:

```text
config/agent-world.example.toml
  -> load_settings / immutable ChatRoute
  -> unchanged DirectChatBackend
  -> world_architecture
```

`load_settings` continues to project only the existing three ChatRoute fields.
`FoundryController` continues to construct `DirectChatBackend` from those two
settings. The backend still uses the primary route first and calls fallback
only after a typed retryable failure; no fallback classification, ordering, or
adapter behavior changed. The Direct route remains prompt-only and has no
Agent route, Runtime Skill, tools, workspace, graph/provenance, or later-child
contract change.

The execution-map and parent-design route tables agree with the selected
Direct primary/fallback and preserve the separate Agent-route selection. The
focused regression loads the checked-in example and asserts both complete
Direct ChatRoute values. The retained C8 whole-diff allow remains structurally
compatible because R1 changes none of its Artifact, graph, WorkRecord,
Registry, owner, or release bindings.

## Verification

- `uv run pytest tests/test_agent_route_config.py`: pass (18 passed).
- `uv run pytest`: pass (92 passed).
- `uv run ruff format --check .`: pass.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass (13 source files).
- `uv run python -m compileall -q agent_world`: pass.
- `uv run pytest tests/test_legacy_firewall.py`: pass (2 passed).
- `git diff --check`: pass.

## Non-claims

This deterministic check does not prove a live Direct model response, live
research, Codex Agent Skill surface, CandidateBuild, candidate isolation,
Integration, Judge, Registry publication, Observe release projection, Repair,
Expand, Consumer/SFT/RL, or an end-to-end EnvironmentPackage. The next real
proof remains the already-authorized frozen `world_architecture` invocation
followed by its Observe scene; a new terminal failure requires a new diagnosis.
