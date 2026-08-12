# Static diagnosis — GraphRunner failure cannot cold-read ZIP input

## Trigger

The focused Registry mismatch regression fails before a Registry WorkRecord is
committed. This is a deterministic test terminal, not a real product run; no
Observe scene exists or is invented.

Registry correctly raises `registry_physical_package_mismatch` inside its
existing `graph.execute` operation. `GraphRunner.execute` catches it and calls
`GraphRunner.fail` with the exact resolved dependencies, including the
`application/zip` physical package. `fail` then unconditionally calls
`ArtifactStore.read_json` for every dependency and raises
`artifact_not_json` before writing Validation, Finding, or failed WorkRecord.

## Cause and boundary

`GraphRunner._resolve_inputs` already supports exactly two closed media types:
JSON (with envelope validation) and ZIP (byte integrity read). The failure path
duplicated only the JSON half of that existing policy. This is a GraphRunner
persistence bug, not a Registry contract, model, Prompt, Skill, retry or ZIP
format problem.

## Smallest repair

Make only `GraphRunner.fail` cold-read each existing input by the same closed
media-type rule: JSON through `read_json` plus envelope validation, ZIP through
`read_bytes`, every other type rejected. Keep input order, semantic material,
Finding ownership, failure subject, evidence and all success behavior
unchanged. Add one focused ZIP-failure regression and retain the Registry test
that proves no publication plus a terminal failed Registry record.

No helper framework, new media type, Artifact, node, edge, schema, compatibility
path or retry is needed. This diagnosis does not prove any live Direct or E2E
boundary.
