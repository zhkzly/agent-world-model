# T0 SDK routing diagnostic design

`docs/plans/staged-test-and-debug-plan.md` takes precedence over this design note.

The test-node path copies the original scope state, preserves committed ancestors as inputs, supersedes only the target coordinate, and calls the actual scheduler leaf. Its output is permanently diagnostic-only and non-releasable.

The current failure is classified as provider-routing/configuration infrastructure: the builtin Codex `openai` provider did not authenticate against the configured OpenAI-compatible endpoint. The repair candidate stays inside the existing `CodexSdkBackend -> private worker -> AsyncCodex -> app-server` path. It uses the SDK's per-thread `config` object to supply a custom provider definition in process memory, with `env_key = "OPENAI_API_KEY"`; the endpoint value is read only from `OPENAI_BASE_URL` in the worker and is never written to materialized config, command arguments, telemetry, state, or artifacts.

The candidate is admissible only because the exact bundled SDK/app-server source establishes that per-thread config is loaded as request overrides and `ephemeral=true` bypasses thread persistence and state DB. The runtime still receives a post-run value scan. If the next true target run finds a value leak, routing is reverted/fail-closed and T0 remains blocked.
