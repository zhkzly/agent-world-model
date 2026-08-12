# Cross-layer review: 32647757 live route

- Query: Independent pre-implementation review of the frozen OpenCode Direct-route repair plan.
- Scope: mixed (task evidence, repository contracts, and current official provider documentation)
- Decision: block
- Date: 2026-08-11
- Plan digest (SHA-256): `32647757d10db7df352b2104843d485d52156b614fef87e266220384d01c5945` (independently recomputed; matches the requested digest)
- Plan revision: unlabelled current `direct-live-route-repair-plan.md`
- Revision count: 0 documented prior revisions for this diagnosis/plan lineage
- Scope: coordinated provider-route/configuration behavior change plus a deterministic configuration regression; no graph, Artifact, owner, or release-contract change is authorized.

## Product target and trigger

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, atomically publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

Trigger: real Direct proof `run_f661a25e29be4764a6bcacc0c778c9a4` terminated at `world_architecture` with HTTP 403 before a model response. The persisted diagnosis correctly limits the observed failure to the Direct provider/configuration boundary and records that Prompt/input, Direct's no-Skill/no-tool/no-workspace surface, compiler, Candidate, Judge, Registry, and later consumers were not reached.

## Independent evidence and failed criterion

The plan's asserted root cause is not supported by the current official documentation. It says `/zen/go` is an extra invalid segment, but the current official OpenCode pages list `deepseek-v4-flash` on **both** of these OpenAI-compatible endpoints:

- Zen: `https://opencode.ai/zen/v1/chat/completions`.
- Go: `https://opencode.ai/zen/go/v1/chat/completions`.

The two pages describe distinct offerings and model/account contexts. Therefore the observed 403 does not establish that the checked-in Go route is malformed, nor that changing it to the Zen route will restore the same credential's Direct proof. It may instead reflect entitlement, credential product, account state, or another provider-side condition. A test that merely pins the replacement literal would preserve the new chosen default, but cannot validate the causal claim.

External references checked on 2026-08-11:

- [OpenCode Zen endpoints](https://opencode.ai/docs/zen) (DeepSeek V4 Flash: `/zen/v1/chat/completions`).
- [OpenCode Go endpoints](https://opencode.ai/docs/go/) (DeepSeek V4 Flash: `/zen/go/v1/chat/completions`).

## Impact chain, ownership, and compatibility

`config/agent-world.example.toml:6` -> `load_settings` / immutable `ChatRoute` (`agent_world/config.py:125`) -> `DirectChatBackend._chat_endpoint` (`agent_world/invocation.py:62`) -> real `world_architecture` Direct LLM invocation -> Designer validation/WorkRecord -> later Design/Build/Integration/Judge/Package/Registry/Observe.

- The proposed edit stays inside the existing Direct route contract: `ChatRoute` and `DirectChatBackend` retain the sole transport ownership; it introduces no provider discovery, retry/fallback change, profile, graph node, or new framework authority.
- C8 provenance is unchanged by a configuration literal alone. The C8 whole-diff record's Package/Registry bindings, the five existing component owners, and later Repair/Expand/Consumer seams remain structurally compatible **if** a correct route is established.
- This is not nevertheless a local text correction: it changes the actual external request target for every consumer of the checked-in example. The real Direct node is the immediate consumer; all later children remain unproved because the direct semantic transaction has not committed.

## Actionable feedback to the plan writer

1. Withdraw the claim that `/go` is malformed. Preserve the observed fact as only `HTTP 403 before model output`.
2. State which OpenCode product the checked-in example is intentionally configuring (Zen or Go) and give evidence that the configured credential is entitled to that product. Do not infer entitlement from the shared model id.
3. Before editing the checked-in default, make the smallest same-host, credential-safe diagnostic control explicit: compare the documented Zen and Go endpoint variants with the identical minimal Direct request shape, record only safe terminal facts/statuses, and read Observe. This is a provider-boundary diagnosis/proof, not a prompt, schema, retry, or graph change.
4. If the control establishes one endpoint as the intended reachable product, revise the plan to change only that literal and add the exact example-load assertion. If neither is authorized, terminate `needs_human` for credential/account entitlement rather than patching route logic. If both work, require an explicit composition/default-selection rationale before changing the example.
5. Keep the current anti-overdesign constraints: no provider discovery, route framework, profile/permission/capability system, fallback/retry alteration, compatibility path, or Repair/Expand/Consumer work. The subsequent frozen `world_architecture` proof must still be run only after the revised configuration decision and must read Observe at its terminal state.

## Smallest tests and proof after revision

- Deterministic regression: load the checked-in example and assert the selected primary model and exact endpoint literal; retain existing route validation and C8 quality checks.
- True-boundary proof: run the bounded, same-host documented-endpoint diagnostic with the configured credential, then the unchanged frozen `world_architecture` node only for the evidenced intended route; inspect its Observe scene. Treat a new terminal failure as a new diagnosis.
- Do not count the literal assertion, provider control, or one node commit as proof of CandidateBuild, isolated Runtime/Integration/Judge, Package/Registry publication, safe Observe release projection, Repair, Expand, Consumer, or end-to-end `EnvironmentPackage` completion.

## Next permitted gate

Revise the repair plan only to close the endpoint-product/credential causal gap above, retain this feedback, and submit the new plan digest for a fresh independent cross-layer review. No implementation is permitted under this decision.
