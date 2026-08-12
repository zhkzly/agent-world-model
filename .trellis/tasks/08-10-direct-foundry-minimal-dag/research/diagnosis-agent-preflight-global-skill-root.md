# Diagnosis — Codex inherits the cross-agent user Skill root

## Expected behavior

The product Agent adapter should expose exactly its one selected Runtime Skill
inside an ephemeral SDK session. Neither project Skills nor user-level
cross-agent Skills may enter the model-visible surface.

## Observed chronology

1. The approved two fixed SDK overrides removed bundled `.system` Skills and
   plugin startup state. The final real Luna preflight retained an unchanged
   target bundle, one session close, a non-ambient temporary `CODEX_HOME`, and
   cleanup.
2. The model nevertheless reported the target Skill plus 24 `arkcli-*` Skills.
   The adapter therefore returned `agent_skill_surface_unverified`.
3. A no-model `skills/list` probe against the same pinned SDK attributed every
   extra Skill to `/home/kelong/.agents/skills` with `user` scope.
4. Calling the typed `skills/extraRoots/set` method with an empty list did not
   remove them; that API does not control the built-in user root.
5. Running the same pinned SDK with only its child-process `HOME` redirected to
   the existing ephemeral home returned exactly the mounted target Skill. No
   RPC, prompt, model, Skill, graph, or validator change was involved.
6. The proof fixture and all probe directories were deleted. This preflight is
   outside the product graphs, so there is no Observe scene to read or mutate.

## Attribution

- Model, route, marker and target bundle: not causal. The singleton failed
  because the runtime constructed a larger Skill discovery surface.
- Bundled/plugin controls: working as intended and still required.
- `skills/extraRoots/set`: not a repair; it cannot remove the built-in user
  root.
- Ambient child-process `HOME`: causal. The pinned runtime derives
  `~/.agents/skills` from it independently of `CODEX_HOME`.
- Existing fail-closed singleton validation: correct and unchanged.

## Smallest repair

Pass `HOME` only to the Codex child process, pointing at the already-created
ephemeral Codex home. Keep `CODEX_HOME`, the selected credential, both fixed
SDK isolation overrides, the prompt, Skill bundle, route, session lifecycle,
and before/after physical checks unchanged.

## Rejected strategies

- Do not call private SDK internals or add a `skills/extraRoots/set` lifecycle.
- Do not hide or delete the user's real `~/.agents/skills` directory.
- Do not filter model output, weaken singleton validation, add a denylist, or
  introduce profiles, permission systems, callbacks, dynamic SDK discovery,
  graph nodes, retries, or downstream changes.

## Smallest next proof

After a fresh independent critic allows the exact one-line environment change,
run focused and full deterministic checks, then one final real nonce preflight.
It must return exactly the selected Skill and marker while preserving digest,
session-close, temporary-home cleanup, and no bundled/plugin/user Skill leaks.
