# Qualification Native Oracle Contract

The independent Qualification workspace must keep `native_probe.py`'s existing
actor-qualification behavior and additionally implement:

```text
python -I native_probe.py semantic-check REQUEST.json RESULT.json
```

This is an internal qualification interface, not an Actor tool, Task verifier,
runtime service, or public package API. The oracle must use an independent
standard reader for the Candidate's native SQLite/files/Git representation. It
must not import Actor or TaskSemantics business code, inspect Semantics Author
source/tests, mutate either instance, or emit a release verdict.

`REQUEST.json` is Host-created and immutable. It binds exact Candidate,
ExpectedTaskSemantics, TaskSemantics and oracle-bundle digests; one unique
request/materialization ID and role; the frozen capability/condition ID,
Requirement IDs, task kind and answer field IDs/public labels; one StartCase;
release-relative before/after instance paths and their Host tree-manifest
digests; one Host journal digest plus exact public trace events; the selected
public binding; the final structured answer; and generated answer value schemas.
It never contains a protected binding, TaskSemantics facts/result, expected
answer value, expected boolean, reward, or pass/fail hint.

For the current atom mode the request has exactly these keys:

```json
{
  "format": "native-semantic-request/1",
  "materialization_id": "opaque-host-id",
  "role": "primary",
  "candidate_digest": "host-sha256",
  "expected_task_semantics_digest": "host-sha256",
  "semantics_digest": "host-sha256",
  "oracle_bundle_digest": "host-sha256",
  "capability": {
    "capability_id": "frozen-id",
    "requirement_ids": ["REQ-..."],
    "task_kind": "query",
    "intent_label": "frozen public intent",
    "answer_fields": [
      {"field_id": "frozen-field", "public_label": "Frozen label", "schema": {}}
    ]
  },
  "start_case": {"case_id": "case", "reset_input": null, "regime_tags": []},
  "before_path": "before",
  "after_path": "after",
  "before_manifest_digest": "host-sha256",
  "after_manifest_digest": "host-sha256",
  "journal_digest": "host-sha256",
  "public_binding": {"public_descriptor": {}, "facets": {}},
  "trace_projection": [],
  "final_answer": null
}
```

`before_path` and `after_path` resolve relative to `REQUEST.json`'s directory.
The result binds `request_digest` to SHA-256 of the exact request file bytes; do
not normalize or rewrite the request.

For an atom request, `RESULT.json` contains exactly the bound request and
materialization IDs, capability ID, the independently identified public binding,
one complete `AtomCheckResultDocument`, non-empty structured native observations,
and structured source-use metadata. For a condition request it analogously
contains one complete `ConditionCheckResultDocument`. The Host validates schemas,
IDs, journal references and instance manifests, then compares native result axes
and report values with TaskSemantics. Merely echoing claims, returning constants,
or writing `passed: true` is invalid.

The atom result has exactly:

```json
{
  "format": "native-semantic-result/1",
  "request_digest": "sha256-of-exact-request-bytes",
  "materialization_id": "opaque-host-id",
  "capability_id": "frozen-id",
  "public_binding": {"public_descriptor": {}, "facets": {}},
  "atom_result": {
    "initially_satisfied": false,
    "satisfied": false,
    "required_effects_ok": false,
    "collateral_ok": true,
    "answer_ok": null,
    "process_ok": null,
    "report_values": {},
    "failure_codes": ["release-local-diagnostic-code"]
  },
  "native_observations": [{"structured": "native facts used by this result"}],
  "source_use": {"reader": "standard-library or locked reader", "purpose": "native decode"}
}
```

`public_binding` is not a blind echo: identify the requested public referent in
native state and return the same public document only when it uniquely matches.
For declared answer fields, `report_values` contains exactly those field IDs and
values computed from native facts; compare the submitted `final_answer` to them
to set `answer_ok`. Query results require public read evidence and no successful
state mutation. Process results require the declared trace process. Compute
required effects, collateral, answer and process axes independently.

All paths are supplied by the Host and may use arbitrary opaque directory names.
Never search for the first database/file recursively or assume legacy names such
as `chain`, `repeat-a`, Requirement-number-derived capabilities, or one fixed
tool. Read only the exact before/after paths in the request. Write the result
atomically at the exact requested output path and nothing else.
