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

1. The controller creates an `AgentProfileSpec` with an explicit model,
   `ReasoningEffort`, output schema, limits, and exactly one Runtime Skill only
   for an Agentic node. A Direct LLM has no Skill, Hook, tool, workspace input,
   or profile-owned instruction surface.
2. `ProfileResolver` creates private SDK state (`HOME`/`CODEX_HOME`) and a
   real Agent workspace. It mounts the content-addressed Runtime Skill through
   Codex's normal local Skill discovery path, while the SDK receives that
   workspace as its actual cwd. Runtime profiles have no base/developer
   instruction fields and no Hook bundle.
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
6. A Direct request reads the same two private environment values only in
   memory, constructs `AsyncOpenAI` inside `direct_llm.py`, and discards the
   response after redaction and local schema-envelope decoding. It has no
   subprocess, tool surface, transcript, session, or durable provider payload.

## Private SDK state, direct-host execution

This layer keeps only the state that genuinely belongs to the invocation:

- one private `CODEX_HOME` with plugins disabled and one verified mounted
  Runtime Skill; it prevents accidental global Skill/Hook/plugin inheritance,
  not host access;
- API-key and optional base-URL values only in the dedicated worker/app-server
  environment; `cli_auth_credentials_store = "keyring"` and a fail-closed
  `auth.json` check prevent credentials from being written to disk;
- `shell_environment_policy.inherit = "none"` so shell commands do not inherit
  the provider credential, while the configured shell has the normal host
  `PATH`, Python, `uv`, and a writable local temporary/cache directory;
- a project-root marker solely to keep Codex from walking up to the Foundry
  checkout and loading unrelated project configuration;
- hash verification of the mounted Skill and generated config, same-profile
  continuation ownership, process cancellation, and recursive result
  redaction.

It deliberately does **not** create a bwrap/unshare sandbox, namespace,
virtual `/workspace` or `/state`, tool facade, generated permission profile,
or path translation layer. The worker explicitly uses SDK
`Sandbox.full_access`; the Code Agent works in its real cwd and can use normal
host commands. Candidate runtime execution remains a separate direct-host
Judge process with framework-owned cwd, temporary state, resource limits,
timeouts, and release gates.

Private materialization may contain session state and must not be copied into
`envpkg v3` or release evidence. This is credential/provenance hygiene, not a
claim that generated code is OS-isolated or trusted.
