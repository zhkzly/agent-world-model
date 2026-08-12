# Diagnosis — Direct requests omit the mechanical JSON response contract

- Date: 2026-08-12
- Supersedes repair attribution in
  `diagnosis-direct-non-json-feedback-gap.md`; its run chronology remains valid.
- Failed run: `run_dc28dcded7fe49ce9a2d9a017511831d`

## Evidence and root cause

The public E2E passed Research, Architecture, SharedTool and seven of eight
ToolSemantics shards. The final shard returned a non-JSON response and was
correctly rejected after one invocation with no output and no release. A fresh
same-input call parsed successfully, showing an intermittent format failure.

The binding source of truth assigns JSON/shape mechanics to code and forbids a
generic root error from consuming semantic correction. Therefore
`DesignExecutor._direct_json(correctable=False)` is intentional; the prior
root-object-correction hypothesis was wrong. The actual gap is earlier:
`DirectChatBackend` tells the model to return JSON only in prose while its
strict consumer requires a JSON object, even though the OpenAI-compatible wire
protocol can enforce that response mode mechanically.

A profile-matched exact-input probe added only
`response_format={"type":"json_object"}`. Both configured routes—primary
`gpt-5.6-luna` and fallback `gpt-5.3-codex-spark` on local 8317—returned the
exact four-key JSON object and usage. Thus no SDK migration, parser heuristic,
semantic correction, retry, prompt expansion or model change is needed.

## Causal boundary

Framework owns the hardcoded response-format request, strict parsing,
transport/fallback policy, compiler, Work and release. Direct LLM still owns
only business semantics. Agents, Skills, workspaces and untrusted candidate
processes are not involved. A malformed response despite the provider contract
remains the same non-retryable terminal failure and cannot cross an edge.

## Non-claims

The probes prove route compatibility and JSON parsing only. They do not prove
semantic compiler acceptance, Design completion, Candidate, Integration,
Judge, Registry, Repair, Expand or Consumer behavior.
