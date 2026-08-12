# Real proof — isolated singleton Runtime Skill

## Result

`passed`

One fresh proof-only Runtime Skill was copied into a dedicated fixture and
mounted by the real `CodexAgentBackend`. Its public nonce value existed only in
the Skill body, not in the prompt. The pinned `openai-codex==0.144.4` SDK made
one real call through the configured primary Agent route:

- model: `gpt-5.6-luna`
- base URL class: configured local `localhost:8317/v1` route
- credential handle: `OPENAI_API_KEY`; no value was printed or persisted
- returned initial Skill names: exactly `["foundry-preflight-singleton"]`
- returned Skill-only marker: exact match
- SDK usage: present

## Framework and physical checks

- SDK child environment keys were exactly `CODEX_HOME`, `HOME`, and the
  selected credential handle.
- `HOME == CODEX_HOME`, and both differed from the ambient user home.
- The physical Skill set before and after the SDK turn was exactly the target
  singleton.
- The complete target bundle digest matched before and after the turn.
- No `.system`, plugin, or ambient user Skill surface appeared.
- The real SDK session was closed exactly once.
- The temporary `CODEX_HOME` was absent after the adapter returned.
- The separate proof fixture was then explicitly deleted.

The proof was outside both product graphs, so it created no Run, WorkRecord,
Artifact, Registry entry, or Observe scene.

## Claim boundary

This proves only that the product Codex Agent adapter can make a real Luna call
with exactly one selected Runtime Skill and clean isolation/lifecycle facts. It
does not prove ResearchPlan, ResearchSynthesis, CandidateBuild, Integration,
Judge, Registry publication, Repair, Expand, Consumer, or Direct E2E.

## Next proof

Continue through the real Direct graph in order. The next Agent-backed semantic
node must consume its committed graph inputs and produce a framework-validated
Artifact; later proofs must cover CandidateBuild, offline installation,
Integration, independent Judge, immutable Registry publication, and Observe.
