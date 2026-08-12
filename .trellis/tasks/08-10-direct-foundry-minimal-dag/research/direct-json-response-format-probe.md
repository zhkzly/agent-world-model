# Probe — configured Direct routes support JSON object response mode

- Date: 2026-08-12
- Input: exact failed `route_tool_to_maintenance` ToolSurface, full frozen
  bindings, committed SharedToolContract, citation catalog, system prompt and
  ToolSemantics output shape from run
  `run_dc28dcded7fe49ce9a2d9a017511831d`.
- Only probe change: request field
  `response_format={"type":"json_object"}`.
- Raw provider content was not printed or persisted by the probe.

Results:

- primary `gpt-5.6-luna` at local 8317: HTTP success, JSON object, exact top
  keys `errors/postconditions/preconditions/transitions`, usage reported;
- fallback `gpt-5.3-codex-spark` at local 8317: HTTP success, JSON object,
  exact same top keys, usage reported.

This proves compatibility of both configured Direct routes with the mechanical
JSON-object request contract on the actual failed input. It does not prove the
semantic compiler, a complete Design, Candidate, Judge, Registry or E2E.
