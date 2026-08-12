# Diagnosis — pinned Codex runtime adds non-target bundled surfaces

## Expected behavior

The product Agent adapter should start with exactly one mounted Runtime Skill,
no ambient project/global Skill or plugin surface, and should close the real SDK
session and delete its temporary `CODEX_HOME` after the turn.

## Observed chronology

1. A temporary proof-only Skill contained one public marker absent from the
   prompt. The existing `CodexAgentBackend` mounted it into a fresh home and
   invoked the real pinned Python SDK through the Luna route.
2. The SDK session completed and closed, and the temporary home was deleted,
   but the adapter returned `agent_skill_surface_unverified`.
3. One instrumented diagnostic turn preserved behavior while snapshotting only
   safe path/digest facts before cleanup. Source and mounted bundle digests
   remained identical across every check. Mounted names were the exact target
   before the turn and `(.system, target)` afterward.
4. The SDK had bootstrapped bundled system Skills and a plugin catalog inside
   the isolated home. This was runtime-created state, not inherited user or
   project state. The target Skill was not modified.
5. Both turns cleaned their temporary homes. The proof fixture was also
   deleted. No graph node, run, Candidate or release was created, so there is no
   Observe scene to adopt or mutate.

## Attribution

- Model/route/marker: not causal. The terminal occurred in the adapter's
  post-turn physical singleton check after a real session completed.
- Target bundle: not causal. Its complete physical digest was unchanged.
- Adapter/runtime configuration: causal. A fresh `CODEX_HOME` alone does not
  disable the pinned Codex runtime's bundled Skills or plugin startup.
- The existing post-turn singleton rejection is correct and must not be
  weakened to ignore `.system`.

## Configuration evidence

- Pinned SDK `config/read` accepts
  `skills.bundled.enabled=false` as effective typed state and then creates no
  `skills/.system` directory.
- Adding `features.plugins=false` also creates no plugin cache. The official
  Codex Configuration Reference defines `features.plugins` as the switch that
  pins plugin availability off.
- These are two fixed adapter facts, not a user-facing profile or permission
  system.

## Rejected strategies

- Do not ignore `.system`, delete SDK-created files during a turn, disable each
  bundled Skill by name, add dynamic feature discovery, or parse plugin
  catalogs.
- Do not add profiles, permission matrices, callbacks, a preflight runtime
  node, or configurable sandbox/plugin settings.
- Do not change model routes, fallback, Skill bundles, prompts, graph topology,
  retry policy, Candidate, Package, Registry, Repair, Expand or Consumer.

## Smallest next proof

Add exactly the two fixed isolation overrides to the existing private-provider
override tuple, update its exact tuple regression, rerun deterministic checks,
then repeat one temporary nonce preflight through the real adapter. Require the
exact singleton model result, unchanged bundle digest, one close, non-ambient
home, cleanup, and absence of bundled/plugin startup surfaces.
