# Research Source Discovery

Use configured research providers to find source material for generating an executable environment.

Rules:

- Prefer user-provided local sources and the raw request as baseline evidence.
- Use external search providers only when configured.
- Supported configured provider families include local sources, SearXNG-compatible self-hosted search, Jina hosted search/reader, and process-backed research agents.
- Do not invent URLs, documents, licenses, or hashes.
- Output source records that can be checked later.
- Every extractable object must reference a source id and evidence refs list.
- Use `object_kind`, `name`, and `evidence_refs` in every extractable object.
- Do not use `object_type`, `value`, or scalar `evidence_ref` as the only field names.
- Do not include secrets or credential-bearing URLs.

Accepted output target: `SourceEvidenceIndex` fields only.
