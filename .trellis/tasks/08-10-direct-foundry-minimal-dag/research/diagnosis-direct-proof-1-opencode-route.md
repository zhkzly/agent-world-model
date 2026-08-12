# Diagnosis — first Direct proof stopped at the OpenCode route

## Expected behavior

The real `world_architecture` Direct node should send its committed request and
research-synthesis inputs through `DirectChatBackend`, receive one JSON object,
compile it, and commit a WorkRecord. No Skill, candidate process, Judge or
release authority participates at this boundary.

## Observed chronology

1. Deterministic C8 provenance checks and the independent whole-diff review
   passed.
2. Run `run_f661a25e29be4764a6bcacc0c778c9a4` entered the real
   `world_architecture` node with the configured primary route.
3. The provider returned HTTP 403 in 0.661 seconds, before any model output.
4. The node committed terminal `direct_http_failure`; Observe reported a failed
   Direct-LLM WorkRecord, no outputs and `release=not_published`.
5. One smaller provider control reproduced HTTP 403. The credential handle was
   present and had no surrounding or embedded whitespace.

## First deviation and attribution

The first deviation is the external provider/authentication boundary, not a
malformed path. Independent review corrected the initial diagnosis: current
official OpenCode documentation lists `deepseek-v4-flash` on both the Zen and
Zen Go endpoints. A credential-safe control sent the same minimal request to
both documented paths; both returned HTTP 403 with the same response size in
about 0.5 seconds. The current `OPENCODE_API_KEY` therefore proves neither Zen
nor Go availability for this run.

- Prompt/input: correctly assembled; no evidence that the provider processed it.
- Skill/tools/workspace: absent by contract, therefore not causal.
- Model/compiler: no model response existed, therefore not reached.
- Framework/Observe: failed closed and preserved the causal node/dependencies.
- Provider/configuration: supported failure boundary; the exact external cause
  is credential/account entitlement or provider-side authorization and is not
  repairable from repository code.

Official contracts:
<https://opencode.ai/docs/zen#endpoints> and
<https://opencode.ai/docs/go/#endpoints>

## Rejected strategies

- Do not change prompts, schemas, compiler or graph provenance: none was reached.
- Do not make authentication failures retryable or silently widen fallback
  policy: that is unrelated to the malformed route.
- Do not add provider discovery, profiles or a route framework: one checked-in
  URL is wrong.

## Smallest repair and proof

The user explicitly selected localhost `gpt-5.3-codex-spark`, then
`gpt-5.6-luna`, when DeepSeek is unavailable. Credential-safe controls
against `http://localhost:8317/v1/chat/completions` returned HTTP 200 for both
models. Select that order in the checked-in example without changing
adapter or fallback logic, then repeat the same frozen `world_architecture`
proof and read Observe. OpenCode remains an external credential/account issue;
do not keep probing or patching it.
