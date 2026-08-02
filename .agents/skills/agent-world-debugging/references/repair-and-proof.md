# Repair Strategy and Proof

## Select the smallest coherent repair

Use evidence, not a symptom table:

- Weak orientation → improve project Agent view.
- Weak recipient story → improve Feedback/observability.
- Missing or misleading Direct requirement → change rendered Prompt/input,
  then generate fresh output.
- Missing reusable Code Agent method/self-check → change the one mounted
  Runtime Skill bundle, then run a real Agent boundary.
- Coherent parsed candidate with localized precise rejection and repair
  authority → bounded correction turn, preserving valid work.
- Route/response mode/profile/adapter/parser/compiler/validator/scheduler bug →
  deterministic code repair.
- Explicit closed transient Provider/transport fact → recorded bounded retry
  or model fallback according to policy.

Malformed JSON, wrong envelope, missing fields, timeout, and test failure may
support several of these. Do not hard-code the symptom to one route.

Use deterministic code for deterministic ownership: framework IDs, ordering,
wrappers, serialization, leases, capability enforcement, and release facts.
Do not use code to fill in business meaning merely because a sample was
incomplete.

## Audit homologous surfaces

Once the cause is credible, inspect every live sibling using the mechanism:

- all rendered Direct Prompt/input projections;
- mounted Agent Skill versions and full bundle identities;
- Direct no-Skill request shapes;
- profiles and model/route/response mode;
- parser/compiler/validator/scheduler paths;
- Feedback renderers and project Agent view pointers.

One observed omission often means the same omission exists elsewhere. Complete
the audit before another expensive live call; do not fix siblings that lack the
same causal mechanism.

## Prove the claim

State before testing:

> Before the change, X happened at boundary Y for frozen input Z. After the
> change, observation Q must differ. This test proves A and does not prove B.

Then:

1. Preserve or construct the smallest credible failing input.
2. Run the real local boundary before/after deterministic changes.
3. Run one real isolated model/Agent node when Prompt, Skill, profile, route, or
   model behavior changed.
4. Run the normal Scheduler for repair-authority or multi-turn claims.
5. Run immediate Integration only after the changed point passes.
6. Run broader downstream and E2E only after Integration passes.

At the first new failure, stop and create a new attribution. A different failure
is new evidence, not permission to continue the old repair strategy.

For a Runtime Skill change, also follow
[runtime-skill-bundle-design.md](runtime-skill-bundle-design.md): validate the
package and scripts, prove complete-bundle hashing/discovery, then run the real
Codex Agent node with its mounted Skill and tools before Integration.
