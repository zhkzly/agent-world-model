---
name: research-world-evidence
description: Turn a staged request/evidence catalog into citation-backed research — first a bounded query/plan, then a claim/conflict/gap synthesis anchored to one-based citation indexes. Used by the research_plan and research_synthesis nodes.
---

You run in two sequential nodes. Each reads one staged input file and returns
one closed JSON object. Use only the staged files; persist no raw source bodies
and write no extra files. Never claim a gate, release, source hash, manifest,
candidate completion, reward, termination, seed, or verifier result.

## A. `research_plan` — read request.json

### 1. Input

- `request.json` — `{"need": "..."}`, the human-authored environment need.

### 2. What to produce

A closed `ResearchPlanDraft` used to drive evidence acquisition. Validator bounds:

- Object: exactly `{queries, questions_to_resolve}`.
- `queries`: 1..6 items; each is nonempty text ≤240 chars. Make them distinct
  search-shaped strings that target different facets of `need`.
- `questions_to_resolve`: 1..12 items; each is nonempty text ≤240 chars. Each
  question is a single explicit, answerable claim about what the design must
  pin down (a behavior, a bound, an ambiguity), not a topic label.

### 3. Self-verify

- 1..6 queries and 1..12 questions, each nonempty and ≤240 chars;
- queries target distinct facets (no near-duplicates);
- every question is answerable from sources, not a restatement of `need`.

### 4. Deliverable

```json
{
  "queries": ["canal-lock water volume conservation equations"],
  "questions_to_resolve": ["Does closing an upstream gate while a downstream gate is open conserve the upstream pool level?"]
}
```

## B. `research_synthesis` — read evidence.json

### 1. Input

- `evidence.json` — `{"request", "questions", "citations": [{"index", "url",
  "text"}, ...]}`. `citation.index` is the one-based number you cite via
  `citation_indexes`; the largest valid index equals the number of citations.

### 2. What to produce

A closed `ResearchSynthesisDraft` — only what the sources support. Two claim
kinds, strictly separated:

- `observed` — the statement is directly and literally stated by the cited
  source(s); no inference.
- `bounded_inference` — the statement is a deduction that connects two or more
  sources (or one source plus the frozen `request`); state the deduction, not
  the sources alone.

Validator bounds:

- Object: exactly `{claims, conflicts, gaps}`.
- `claims`: 1..32 items; `conflicts`: 0..16 items; `gaps`: 0..16 items.
- Each claim/conflict is exactly `{statement, kind, citation_indexes}`:
  - `statement`: nonempty text ≤500 chars.
  - `kind`: one of `"observed"`, `"bounded_inference"`.
  - `citation_indexes`: 1..6 ints, unique, each an existing one-based citation
    index (1..number of citations).
- `gaps`: each nonempty text ≤300 chars — something no source settles.

State a source disagreement as a `conflict`; state an unresolved question as a
`gap`. Every `observed` claim cites the source that states it; every
`bounded_inference` cites every source the deduction joins.

### 3. Self-verify

- 1..32 claims, 0..16 conflicts, 0..16 gaps within bounds;
- every `citation_indexes` has 1..6 unique ints, all ≤ the citation count;
- no `observed` claim smuggles a deduction; no `bounded_inference` rests on one
  source when it joins several;
- each conflict names the disagreeing sources; each gap is specific.

### 4. Deliverable

```json
{
  "claims": [
    {
      "statement": "Closing the upstream gate isolates the upstream pool from inflow. (<=500 chars)",
      "kind": "observed",
      "citation_indexes": [1]
    },
    {
      "statement": "Pool level is therefore conserved only while the downstream gate is also closed. (<=500 chars)",
      "kind": "bounded_inference",
      "citation_indexes": [1, 2]
    }
  ],
  "conflicts": [],
  "gaps": ["No source quantifies the seepage rate through a closed gate. (<=300 chars)"]
}
```
