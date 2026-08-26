# S1 Execution Contract
## Initial contract (frozen)
Goal: implement the approved Need -> real EnvironmentRelease path, never a demo-shaped substitute.
Invariant 1: a positive result requires real Codex-authored project code, real tools, and independently observed native state.
Invariant 2: every stage consumes only its documented context and produces its documented handoff; no hidden fallback or compatibility path.
Invariant 3: tests must distinguish semantic correctness from schema/startup green, and every implementation slice needs RED plus mutation/physical-negative evidence.
Do not: modify canonical PRD/design/implement without user approval; hard-code a domain, dict response map, custom sandbox/protocol/workflow, or speculative abstraction.
Gold: official Codex SDK Python contract, live SearXNG JSON at 127.0.0.1:8080, and the first production-generated release (never a hand-authored positive environment).

## 追加

- 2026-08-26: Research Search uses configurable SearXNG with the verified local default `http://127.0.0.1:8080`; Fetch/Extract remain independent real operations.
- 2026-08-26: Research/Builder Agent route uses the verified local OpenAI-compatible endpoint `http://127.0.0.1:8317/v1`, model `gpt-5.6-luna`, and invocation-only `OPENAI_API_KEY`; credentials are never persisted.
- 2026-08-26: Initial runtime Skills are exactly Research method guidance and environment code generation; a new Skill requires observed repeated need and user-approved canonical change.
- 2026-08-26: Task activation used `OVERRIDDEN(ASK)` after repeated `PATROL_UNAVAILABLE`; this authorizes activation only, not later commit/release transitions.
