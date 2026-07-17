# Real Agent invocation layer

## Purpose

The Foundry turns a natural-language need into a real, executable and
framework-verified `EnvironmentPackage`. This directory has one narrow role in
that system: execute an already-authorized Researcher, Environment Engineer, or
Challenger turn through the real Codex SDK and return auditable events, usage,
output, failure and continuation state. It does not decide workflow order,
correctness, repair ownership, Gate verdicts, or release.

There is intentionally no mock, manual, template, replay, arbitrary-command or
fallback backend here. If the pinned SDK, Codex runtime, authentication, or
materialized profile is unavailable, `CodexSdkBackend` returns an explicit
`needs_human` or `failed` result.

## Execution contract

1. The controller creates an `AgentProfileSpec` with explicit model,
   `ReasoningEffort`, instructions, skill/hook bundles, built-in capabilities,
   MCP tool allowlists, network domains, credential handles, output schema and
   limits.
2. `ProfileResolver` creates one private materialization root containing an
   isolated `HOME`, `CODEX_HOME`, stable workspace, content-addressed skills,
   hook configuration and MCP configuration. Ambient user/project Codex config
   is rejected rather than inherited.
3. Authentication is explicit. `CredentialBinding` resolves one allowlisted
   environment value, while `CodexLoginBinding` copies one caller-authorized
   `auth.json` to the isolated `CODEX_HOME` with mode `0600`. It never scans for
   a global login. Login file contents and paths are not put in the profile
   hash, public metadata, worker request, events, or logs.
4. `CodexSdkBackend.invoke()` verifies the materialization, starts the fixed
   `_codex_worker.py` in a dedicated process, and that worker calls
   `openai_codex.AsyncCodex` (`0.1.0b3`). A new request uses `thread_start`; a
   repair request with `InvocationSession` uses `thread_resume` and is rejected
   unless profile hash, generated Codex-config hash, lineage and absolute
   workspace are identical.
5. The worker passes `output_schema` and explicit reasoning effort to the SDK,
   streams typed notifications, records token usage, and redacts credential
   material before writing NDJSON. A soft timeout requests `turn.interrupt()`;
   the parent kills the complete worker/app-server process group if it does not
   stop during the grace period.
6. Codex requires interactive trust for non-managed hooks. When and only when a
   resolved profile contains resolver-vetted, content-addressed hooks, the
   worker launches the exact runtime bundled with the pinned SDK using Codex's
   one-run `--dangerously-bypass-hook-trust` flag. This bypasses hook review,
   not tool approval or sandboxing; no project or ambient hooks are loadable.

## Isolation boundary

This layer enforces:

- no ambient `HOME`, `CODEX_HOME`, Skills, Hooks, MCP config or credentials;
- explicit content-addressed copies of Skills and Hooks;
- explicit MCP server and per-server tool allowlists;
- API-key or ChatGPT-login handles selected by resolver policy;
- API-key removal from the worker environment before app-server startup;
- `shell_environment_policy.inherit = "none"`, so Agent shell commands do not
  inherit SDK/MCP credentials;
- no full-access sandbox profile and no interactive escalation; a generated
  custom permissions profile denies the host filesystem by default, opens only
  the runtime roots and declared bundles for reading, and grants the isolated
  workspace either read-only or write access exactly as requested;
- no undeclared workspace/materialization Agent control files; a custom
  project-root marker plus zero-byte project-doc budget prevents parent
  discovery;
- hash verification of copied bundles, generated `config.toml`, merged
  `hooks.json`, and the complete public resolved-profile marker before each
  invocation;
- same-profile, same-lineage, same-workspace thread continuation;
- process-level timeout/cancellation and recursive result redaction.

It does **not** make generated code trusted and does not replace an OS/container
supervisor. Codex workspace sandboxing does not provide CPU/memory/process
quotas, sealed-verifier isolation, package verification, or release authority.
HTTP MCP servers are pinned to configured URLs and stdio MCP servers are
explicit profile capabilities, but a server's own internal network behavior
still requires ToolBroker/OS network enforcement. The experimental Codex
domain proxy and bundled-runtime hook flag must be checked by `agent-world
doctor` on the actual installed versions. Candidate runtime execution belongs
in the Judge supervisor, not in this SDK worker.

The isolated materialization directory contains authentication/session state
and must be treated as sensitive runtime state. The controller owns its
lifecycle and must delete it after the implementation lineage is closed; it
must never be copied into `envpkg v3` or release evidence.
