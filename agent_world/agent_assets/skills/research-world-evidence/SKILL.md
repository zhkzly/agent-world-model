---
name: research-world-evidence
description: Working method for a tool-enabled Codex Researcher turn that gathers or inspects source material for Agent World. Direct LLM evidence synthesis does not load this Skill.
---

# Research World Evidence

This Skill is mounted only for an actual Researcher Agent with granted tools.
Direct evidence nodes receive their bounded CitationCatalog in the node Prompt
and use no Skill or workspace tools.

1. Start with the current node Prompt: it defines the research question,
   permitted sources, output artifact, and budget/authority boundary.
2. Plan narrow checks across the facts that matter to the requested workflow:
   users, systems of record, public actions, state rules, errors, permissions,
   time, concurrency, and rollback.
3. Treat search results and snippets as leads. Ground an observed claim only
   in supplied or fetched body text with usable provenance. Keep inference,
   product decisions, bounded assumptions, conflicts, and unknowns distinct.
4. Use targeted reads/searches; do not dump full source bodies into the
   conversation or artifact. Stop when the Prompt's required coverage is
   supported or the remaining gap is genuinely unresolved.
5. When the Prompt supplies a citation catalog, copy only its permitted
   identifiers/indexes exactly. Never mint, rename, or infer an opaque evidence
   identity from a source title or business meaning.
6. Return only the requested structured research artifact. Do not write
   runtime code, alter release state, fabricate a provider/tool success, or
   request sealed artifacts.
