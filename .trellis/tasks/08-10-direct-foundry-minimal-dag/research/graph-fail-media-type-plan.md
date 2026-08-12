# Minimal plan — GraphRunner failed-work ZIP dependency support

- Plan lineage: `graph-fail-media-type`, revision 1/2
- Diagnosis: `diagnosis-graph-fail-zip-dependency.md`
- Scope: local persistence correction used by the existing Registry node

## Exact change

1. In `agent_world/graph.py`, replace the unconditional `read_json` loop in
   `GraphRunner.fail` with the same closed JSON/ZIP cold-read branches already
   used by `_resolve_inputs`:
   - JSON: `read_json`; if it is an envelope, `read_envelope`;
   - ZIP: `read_bytes`;
   - otherwise: `graph_input_media_type_invalid`.
2. Do not refactor `_resolve_inputs`, add a helper, broaden accepted media
   types, change failure authority/semantic identity, or touch success routing.
3. In `tests/test_graph_contracts.py`, prove `fail` accepts an integrity-valid
   ZIP dependency and commits the existing Validation/Finding/failed
   WorkRecord shape. Keep the Registry physical-mismatch regression unchanged.

## Bounds and checks

Only `agent_world/graph.py` and `tests/test_graph_contracts.py` may change.
Production growth is capped at five lines and the combined semantic/release
repair must remain at or below its existing 10,299-line ceiling. Run the two
focused suites, full pytest, Ruff, mypy, compileall, diff check and legacy
firewall.

After deterministic success, repeat the independent whole-diff review before
any live proof. This plan adds no real call, Retry/Repair, Expand, Consumer or
release claim.
