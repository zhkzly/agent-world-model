# Minimal repair plan — isolate the Codex child-process user home

## Goal

Prevent the pinned Codex runtime from discovering ambient
`~/.agents/skills`, while retaining the existing single-Skill product Agent
contract and adding no configuration framework.

## Exact implementation

1. In `CodexAgentBackend.invoke`, add exactly one fixed entry to the existing
   SDK child environment:

   ```python
   "HOME": str(codex_home)
   ```

   `CODEX_HOME` continues to point at the same ephemeral directory. The chosen
   credential remains the only other explicit environment entry.
2. Update the existing exact backend-spy assertion so it requires
   `HOME == CODEX_HOME` and rejects the ambient home.
3. Add no helper, resolver, config field, profile, RPC, callback, permission
   layer, retry, prompt, Skill, model, route, graph, or downstream change.
4. Run focused and full deterministic checks plus an independent check. Only
   then rerun one real singleton-Skill SDK preflight.

## Cross-layer compatibility

- Changed boundary: only the environment inherited by the pinned Codex child
  process for an existing Agent invocation.
- All Agent nodes retain the same inputs, selected Runtime Skill, SDK adapter,
  workspace, output contracts, and model routes.
- Direct LLM, graph ports, compilers, Candidate process, Integration, Judge,
  Registry, Observe, Repair, Expand and Consumer are unchanged.
- The Agent loses unrelated user Skills and gains no authority.

## Acceptance

- Backend-spy tests prove `HOME` is ephemeral, equals `CODEX_HOME`, and is not
  the ambient home.
- Existing Agent route/isolation tests and all deterministic gates pass.
- A fresh real preflight returns exactly one target Skill plus its Skill-only
  marker; target digest, close count, cleanup, and absence of `.system`, plugin
  cache and ambient user Skills are all verified.
- This proves only the Agent backend surface. It does not prove a semantic
  Research/Build Agent node, CandidateBuild, Integration, Judge, Registry, or
  full E2E.
