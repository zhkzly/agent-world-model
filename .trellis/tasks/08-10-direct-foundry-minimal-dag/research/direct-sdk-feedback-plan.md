# Plan — official Direct SDK and conversational Feedback

- Diagnosis: `diagnosis-direct-sdk-feedback-boundary.md`
- Research: `prompt-feedback-observe-retry-principles.md`
- General research: `general-context-prompt-skills-feedback-research.zh.md`
- Revision: 2/2
- Scope: one coordinated Direct adapter, operation-evidence and existing
  node-local feedback repair; no graph topology or downstream ABI change.

## Product target and unchanged authority

Advance natural-language need -> evidence-backed Design -> executable Candidate
-> isolated independent Judge -> immutable Registry `EnvironmentPackage`.
Framework remains the sole owner of contracts, validation, correction count,
fallback, routing, commits, Judge and release. Direct remains Prompt-only;
Agent remains generic Codex + one Runtime Skill + allowed tools/workspace;
Candidate remains an untrusted process.

Feedback is the next user wish for the same logical task. It carries observable
safe facts and asks the same recipient for a complete replacement. It never
grants authority over retry, owner, route, budget, invalidation, Gate or release.

## Minimal implementation

### 1. Official SDK and API-root configuration

1. Add and lock `openai==2.54.0`. Delete the Direct `urllib`, `_chat_endpoint`
   and raw envelope compatibility path. Research Search/Fetch HTTP and the
   existing Codex SDK adapter are unrelated and stay unchanged.
2. Treat `ChatRoute.base_url` as an API root. Continue accepting valid HTTP(S)
   provider roots, but reject a value ending in `/chat/completions`; update the
   example from `http://localhost:8317/v1/chat/completions` to
   `http://localhost:8317/v1`. Do not silently strip or append the legacy
   endpoint suffix.
3. For each physical Direct call, use a bounded context-managed
   `OpenAI(api_key=..., base_url=..., timeout=300, max_retries=0)` client and
   close it deterministically. Call `client.chat.completions.create` with only
   the model, messages and `response_format={"type":"json_object"}` needed by
   this adapter. Pass neither `max_tokens` nor `max_completion_tokens`; do not
   add an application output-size or first-progress limit.

### 2. Closed result and error classification

For a typed first choice, classify in this order:

1. no choice/message or structurally unusable SDK result ->
   `direct_response_invalid`, terminal;
2. nonempty refusal -> `direct_response_refused`, terminal;
3. `finish_reason == "length"` -> `direct_response_truncated`, terminal;
4. `finish_reason == "content_filter"` -> `direct_response_filtered`, terminal;
5. any finish other than `stop` (including tool/function calls or unknown) ->
   `direct_finish_invalid`, terminal;
6. empty/non-string content -> `direct_response_empty`, terminal;
7. complete nonempty `stop` content that is not one strict JSON object ->
   `direct_response_not_json`, locally correctable only on node attempt one;
8. parsed object -> unchanged deterministic node compiler.

Map SDK failures without raw body/message persistence:

- missing credential/configuration, authentication or permission -> existing
  safe `needs_human`/non-retryable category;
- `APIConnectionError`, `APITimeoutError`, 408, 429 and 5xx -> retryable
  transport/HTTP category eligible only for the existing primary-to-fallback
  transition;
- bad request, not found, unprocessable and other non-retryable SDK/API status
  -> safe terminal provider-request category.

The SDK performs zero hidden retries. Malformed content, refusal, incomplete
finish and compiler rejection never trigger provider fallback.

### 3. Complete safe operation evidence

1. Extend the existing invocation result/error handoff only enough to carry an
   ordered tuple of safe physical-attempt facts: resolved model, measured usage
   or `None` for unknown, and closed safe outcome code. This tuple accounts for
   a failed primary plus a successful/failed fallback as separate real calls.
2. Let existing `OperationEvidence` persist those facts before compiler
   correction or terminal handling. Unknown usage stays `None`, never zero.
3. For an eligible malformed `stop` result, keep the rejected content only in
   the in-memory node transaction so it can be the prior assistant message.
   Never write it to Artifact, attempt evidence, Observe, Skill, Registry,
   task docs or OpenViking.
4. No new event store, trace subsystem, operation service or public Observe
   schema is introduced.

### 4. One deterministic Feedback renderer

Use one small renderer for an already framework-authorized safe packet. Its
message has exactly four semantic sections:

1. same objective, frozen input and complete output contract remain unchanged;
2. previous proposal was rejected for the listed observed issues;
3. return one complete replacement, not a patch, diff or explanation;
4. fix every matching occurrence and recheck the whole replacement.

It may render only safe issue fields. It must not include raw exceptions,
provider bodies, secrets, route/model choice, correction budget, owner,
coordinate, invalidation, Judge or release information.

For Direct attempt two, reconstruct the logical conversation through the
existing message surface:

```text
system:    unchanged stable Direct role
user:      byte-identical original node task/input/output contract
assistant: immediately rejected output, ephemeral and low-authority
user:      rendered Feedback
```

Do not also paste the rejected output into Feedback. Direct receives no Skill,
tools, workspace, provider-owned `instructions`, ambient profile or retained
server session.

Existing Agent wrappers use the same rendered Feedback wording with their
unchanged original instruction. This repair does not change Codex route,
thread/session lifecycle, mounted Skill, tools, workspace, writable scope or
malformed-Agent-output terminal policy; it does not persist or inject rejected
Agent output. A future Agent-conversation change requires its own real failure
and plan.

### 5. Bounded safe validation frontier

1. Replace the single-item `CorrectionPacket` payload with a bounded tuple of
   `1..12` existing safe issue records. Each issue keeps the current fields:
   `code`, exact JSON path, violated condition and expected category. This is a
   small evolution of the existing packet, not a new Feedback service.
2. At each currently correction-capable Design/Candidate compiler's existing
   natural independent sections or item loop, collect safely discoverable
   issues from the submitted object before raising once. Do not synthesize
   placeholder values, rerun a compiler with invented data, add a second
   validator, or inspect downstream nodes. If a safe coherent frontier cannot
   be formed or exceeds the bound, terminal-block instead of sending blind or
   truncated Feedback.
3. Persist the complete bounded issue tuple in the failed attempt. The renderer
   groups identical condition/category issues only for readability while
   retaining their count and affected paths. Framework no-progress identity is
   the sorted full issue tuple; the model never sees or controls that policy.
4. Keep `local_corrections=1` and exactly two semantic calls. A second invalid
   replacement is terminal even if its issue set differs. Do not add a third
   call, evaluator model or outer Repair.

### 6. Coordinated contract files

Update only the files required by the above behavior:

- `pyproject.toml`, `uv.lock`, `agent_world/config.py`,
  `config/agent-world.example.toml`;
- `agent_world/invocation.py`, the existing safe contracts and `GraphRunner`
  evidence/correction handoff;
- existing Design/Candidate wrappers and their correction-capable compilers;
- `docs/agent-world-environment-generation.zh.md`,
  `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md`, and the
  concise Agent/LLM debugging guide.

The source changes state the same minimal rule: Feedback is a next user wish;
the malformed-root exception is only completed nonempty `stop` model content;
the complete bounded safe frontier remains framework evidence; and no new
runtime component is created. Add Product Alignment Checkpoints before
implementation proof and at the real terminal.

## Compatibility and explicit non-scope

- No legacy endpoint-suffix compatibility, raw Direct HTTP, output-token cap,
  parser heuristic, alternate SDK, Responses migration or capability
  negotiation.
- No graph/node/edge, Artifact payload ABI, Candidate runtime protocol, Judge,
  Registry, package or public CLI change.
- No new Skill, context manager, feedback service, validator Agent, scheduler,
  memory/RAG layer, prompt registry, generic schema platform or retry budget.
- No automatic workflow Repair, Expand, multi-parent, Consumer, SFT or RL work
  is hidden in this repair.

## Deterministic checks

1. SDK adapter doubles prove API-root routing, legacy suffix rejection,
   `max_retries=0`, 300-second physical timeout, context-manager close,
   JSON-object mode, absence of output-token arguments and strict parse.
2. A table test proves every finish/refusal/empty/envelope and SDK exception
   maps to the closed safe category, with fallback only for the declared
   replay-safe transport/HTTP set.
3. A primary-failure/fallback-success test proves two ordered operation evidence
   records, measured-or-unknown usage, no hidden retry and no raw content.
4. A malformed-first/valid-second Direct test proves complete first-attempt
   evidence, exact four-message reconstruction, unchanged original task,
   Feedback wording, strict whole-object revalidation, no raw persistence and
   no third call. Second malformed, refusal and non-`stop` cases stay terminal.
5. A two-independent-safe-issues test proves the full tuple is persisted and
   both issues enter one compact Feedback; an Agent-recipient test proves the
   same wording while Agent malformed JSON remains terminal.
6. Run full pytest, Ruff format/check, mypy, compileall, legacy firewall and a
   production-line-count comparison. The implementation must delete raw Direct
   transport code and avoid a net generic-framework expansion.

## Real proof order

1. Independent implementation check.
2. One profile-matched real Direct SDK node proof on Luna. Read Observe and
   retain only safe model/usage/category facts. A deterministic injected
   malformed-first test is not relabelled as a live recovery.
3. If the real node passes, run one fresh natural-language public Direct E2E to
   terminal and immediately read Observe. Stop at and diagnose the first new
   failure; do not stack an unreviewed patch.

## Honest non-claims

SDK, Feedback and one-node proof do not prove Design completion. An E2E terminal
before Registry proves only the reached boundary. Candidate build/install,
Integration, Judge, Registry, bounded Repair, Expand/multi-parent and
Consumer/SFT/RL remain separate required evidence and ordered child tasks.

Next permitted gate: compute the exact plan digest and submit this revision to
a fresh independent cross-layer critic. Only `allow` permits implementation.
