# Plan — enforce the existing Direct JSON contract at the wire boundary

- Diagnosis: `diagnosis-direct-json-response-contract-missing.md`
- Prior block: `cross-layer-review-f1cbad92.md`
- Revision: 2/2
- Scope: one mechanical Direct request-body field

1. Add `response_format: {type: json_object}` to the fixed request body in
   `DirectChatBackend._call`. Both configured local-8317 Direct routes passed a
   profile-matched exact-failed-input probe with this field.
2. Add focused adapter coverage that decodes the outgoing request and proves
   the field is present with the existing model/messages/temperature/token
   settings. Preserve strict parsing and existing tests that a malformed model
   response is terminal, gets no semantic correction or fallback, commits no
   output and blocks release.
3. Change no Prompt/output shape, compiler, `NodeSpec`, correction budget,
   route/model/base URL/key, timeout, fallback policy, parser, SDK, Skill,
   Agent/candidate process, Artifact ABI, graph/edge, Registry, Repair, Expand
   or Consumer code. Do not add capability negotiation or a compatibility path:
   the two checked-in configured routes are the supported Direct profile.

This is framework-owned mechanical JSON enforcement. Direct LLM still owns
only bounded business semantics and remains tool-/Skill-/workspace-free. Agent
and candidate boundaries are unchanged. Malformed content despite the wire
contract remains `direct_response_not_json`, terminal and non-correctable; no
extra invocation or unrecorded usage is introduced.

The Direct Prompt/input/output contract and graph declaration stay unchanged;
the field enforces their already-declared object transport rather than changing
semantic meaning. Actual route model and usage continue to be persisted as
OperationEvidence, while fresh model output and Artifact digests may differ.

Run focused/full tests, firewall/release, Ruff, mypy, compileall, diff and the
10,320 production-line ceiling, then an independent implementation check. The
smallest live proof calls the actual product Direct backend on the exact failed
ToolSemantics input and verifies only a parsed four-key object plus reported
usage; raw content is not persisted. If that passes, run one fresh public
Direct E2E and read terminal Observe. Any new failure starts a fresh diagnosis.
