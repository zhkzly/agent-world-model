# Real Agent invocation layer

## Purpose

The Foundry turns a natural-language need into a real, executable and
framework-verified `EnvironmentPackage`. This directory has one narrow role in
that system: execute an already-authorized Researcher, Environment Engineer, or
Challenger turn through a real backend adapter and return auditable events,
usage, output, failure and continuation state. It does not decide workflow
order, correctness, repair ownership, Gate verdicts, or release.

There are exactly two explicit real adapters behind `InvocationBackend`:

- `CodexSdkBackend` executes agentic, tool-capable, and continuation work
  through the pinned `openai_codex.AsyncCodex` runtime.
- `DirectLlmBackend` executes only an explicitly declared, tool-free,
  session-free structured turn through the official `openai.AsyncOpenAI`
  Responses API. It sends `text.format` with strict `json_schema`, a bounded
  `max_output_tokens`, `store=False`, and `max_retries=0`: Scheduler remains
  the sole retry/budget authority.

`RoutedInvocationBackend` chooses Direct only when all of those conditions are
present; otherwise it chooses Codex. It never retries a Direct failure through
Codex or falls back to a mock, template, replay, arbitrary command, or manual
path. The application-wide semaphore applies across both transports.

## Execution contract

1. The controller creates an `AgentProfileSpec` with explicit model,
   `ReasoningEffort`, instructions, skill/hook bundles, built-in capabilities,
   MCP tool allowlists, network domains, credential handles, output schema and
   limits.
2. `ProfileResolver` creates one private materialization root containing an
   isolated `HOME`, `CODEX_HOME`, stable workspace, content-addressed skills,
   hook configuration and MCP configuration. Ambient user/project Codex config
   is rejected rather than inherited.
3. Authentication and routing are explicit and environment-handle only.
   `CredentialBinding` resolves the allowlisted `OPENAI_API_KEY`; the optional
   `OPENAI_BASE_URL` is another private worker value.  The worker selects its
   framework-owned custom API-key provider through the SDK's per-thread
   in-memory request config; its `env_key` remains `OPENAI_API_KEY`.  It never
   writes either value to materialized `config.toml`, passes either value via
   `--config` or argv, calls `login_api_key()`, scans for a global login, copies
   `auth.json`, or puts either value in profile metadata, worker payloads,
   events, or logs.  The bundled Codex app-server's unavoidable SQLite state
   plane is redirected to a memory-backed directory. A persisted Codex thread
   retains that private directory only while its owning backend instance remains
   live; it is removed when the session is released or the backend exits. A
   durable `InvocationSession` record never exposes the directory, so a
   restarted backend fails closed rather than pretending that a bare thread id
   restores a conversation.
4. Agentic requests selected for `CodexSdkBackend.invoke()` verify the
   materialization, start the fixed
   `_codex_worker.py` in a dedicated process, and that worker calls the pinned
   `openai_codex.AsyncCodex` runtime. A new request uses `thread_start`; a
   repair request with `InvocationSession` uses `thread_resume` only when the
   exact private runtime checkpoint is still owned by that backend; otherwise
   it returns `session_runtime_unavailable`. In both cases profile hash,
   generated Codex-config hash, lineage and absolute workspace must be
   identical. Scheduler policy—not the adapter—may then authorize a fresh
   session with an explicit RepairPacket.
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
7. A Direct request reads the same two private environment values only in
   memory, constructs `AsyncOpenAI` inside `direct_llm.py`, and discards the
   response after redaction and local schema-envelope decoding. It has no
   subprocess, tool surface, transcript, session, or durable provider payload.

## Isolation boundary

This layer enforces:

- no ambient `HOME`, `CODEX_HOME`, Skills, Hooks, MCP config or credentials;
- explicit content-addressed copies of Skills and Hooks;
- explicit MCP server and per-server tool allowlists;
- API-key and optional base-URL values only in the dedicated worker/app-server
  environment; the Agent shell still receives the separately compiled,
  credential-free `shell_environment_policy`;
- `cli_auth_credentials_store = "keyring"` plus a fail-closed check that
  rejects an `auth.json` cache under the isolated `CODEX_HOME`;
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

The isolated materialization directory can contain session state and must be
treated as sensitive runtime state. Authentication files are forbidden there;
the controller rejects any `auth.json` cache. The controller owns the
directory lifecycle and must delete it after the implementation lineage is
closed; it must never be copied into `envpkg v3` or release evidence.
