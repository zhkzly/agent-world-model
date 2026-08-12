# Minimal repair plan R1 — select the proven Direct routes

## Goal

Restore the already-approved real Direct proof using the user-authorized,
locally proven models while preserving all C8 graph provenance, node contracts
and fallback semantics.

## Exact implementation

1. In `config/agent-world.example.toml`, set Direct primary to
   `gpt-5.3-codex-spark` and Direct fallback to `gpt-5.6-luna`; both use the
   existing localhost `8317` chat-completions endpoint and `OPENAI_API_KEY`.
2. Update only the two existing route tables/text in
   `docs/direct-rewrite-execution-map.zh.md` and the complete-v1 parent design
   so documentation describes the same runtime selection. This changes no
   node role: both remain Prompt-only Direct LLM routes.
3. Add one focused assertion in `tests/test_agent_route_config.py` that the
   checked-in example loads those exact Direct routes.
4. Run the focused test and existing deterministic quality gate, then repeat
   the same frozen `world_architecture` proof and read Observe.

## Explicit non-goals

No adapter/code-path change, fallback-policy change, retry, profile/provider
discovery, new schema, node, graph, compatibility behavior, Repair, Expand or
Consumer implementation. The inaccessible OpenCode routes are not retained as
a nominal fallback and are not probed again in this repair.

## Acceptance

- The example selects the two localhost routes already proven HTTP-reachable.
- Existing deterministic checks remain green.
- The exact Direct node either commits valid output or stops honestly with a
  newly observed failure.
