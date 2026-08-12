# Minimal repair plan — disable Codex bundled Skill and plugin startup

## Goal

Make the existing ephemeral product Agent adapter expose exactly its one
selected Runtime Skill without weakening its physical fail-closed check or
creating a configurable capability system.

## Exact implementation

1. Append exactly these two fixed entries to
   `_private_provider_overrides(route)`:

   ```text
   skills.bundled.enabled = false
   features.plugins = false
   ```

   Keep provider identity, zero request/stream retries, ephemeral thread,
   constant sandbox, Skill mounting, before/after closure checks, session close
   and cleanup unchanged.
2. Update the existing backend-spy regression's exact `config_overrides` tuple
   assertion. Add no new configuration field, resolver, helper, enum, callback,
   profile, permission or plugin abstraction.
3. Run the deterministic suite and independent check. Then repeat the one real
   temporary singleton-Skill/marker SDK preflight. The proof must verify the
   exact returned Skill list and marker, bundle digest, one session close,
   non-ambient temporary home, cleanup, and no `.system` or plugin cache before
   deletion.

## Cross-layer compatibility

- Changed producer boundary: only the fixed app-server launch overrides inside
  `CodexAgentBackend`.
- Agent nodes and Skills unchanged: ResearchPlan, ResearchSynthesis, BuildPlan,
  VerifierIntent and CandidateBuild continue choosing their existing one Skill
  in code and receiving the same workspace/instruction contracts.
- Direct LLM, graph ports, compiler, Artifacts, WorkRecords, Candidate process,
  Judge, Package, Registry, Observe, Repair, Expand and Consumer are unchanged.
- The model loses unrelated bundled/plugin surfaces; it gains no authority.

## Explicit non-goals

No per-Skill denylist, dynamic SDK introspection, user configuration, profile,
plugin manager, permission matrix, callback lifecycle, sandbox option, hook/MCP
loader, retry/model/route change, new node/graph, or later-child implementation.

## Acceptance

- The exact two overrides reach every product Agent SDK launch.
- Existing backend-spy and full deterministic checks pass.
- One real nonce preflight returns the exact singleton and marker while all
  physical closure/close/cleanup checks pass and no bundled/plugin startup
  surface appears.
- This proves the Agent adapter only; it does not prove a semantic Agent node,
  CandidateBuild, Integration, Judge, Registry release or E2E.
