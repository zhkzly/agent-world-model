---
name: research-world-evidence
description: Research real workflows, tool ecosystems, state rules, errors, permissions, and constraints for Agent World environment design. Use for direct requirement research or non-blocking Discovery when outputs must be grounded in fetched source content and expressed as v2 evidence/coverage artifacts.
---

# Research World Evidence

Collect evidence that lets the Foundry turn a human need into a faithful executable world.

1. Read only the request and framework-provided research inputs.
2. Plan queries across workflows, systems of record, tools, APIs/SDKs/CLIs/MCP, state rules,
   errors, permissions, time, concurrency, and rollback.
3. Treat search hits and snippets as leads. Cite a claim as observed only when the supplied
   fetch/extraction record contains supporting body text and provenance.
4. Separate observed claims, inference, product decisions, and bounded assumptions. Preserve
   conflicts and unknowns instead of guessing.
5. Update coverage by dimension; do not collapse it into one score.
6. Return exactly the requested structured output. Do not write runtime code, alter release
   state, request sealed artifacts, or invent a provider success.

## Bounded source reading

- When the prompt embeds an `EvidencePassagePack`, the node is tool-free. Use only that pack and
  return the typed artifact; do not look for workspace files.
- Never print a complete source body into the conversation. Read the catalog first, then use
  narrow line ranges or bounded searches such as `rg -n -m 8 -C 1`.
- Use at most 12 shell calls for one synthesis artifact and request at most 1,500 output tokens per
  call. Batch related source checks when that reduces round trips.
- Stop using tools while at least 16,000 rollout tokens remain, then return the requested typed
  artifact. Preserve missing coverage as an unresolved question instead of spending the output
  budget on exhaustive reading.

If evidence is unavailable, return the unresolved question or failure explicitly.
