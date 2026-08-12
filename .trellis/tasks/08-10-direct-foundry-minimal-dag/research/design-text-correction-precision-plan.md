# Plan — make existing Design text corrections precise

- Diagnosis: `diagnosis-design-text-correction-collapsed.md`
- Revision: 1/2
- Scope: common Design validator feedback only; acceptance unchanged

## Minimal implementation

1. In the existing `agent_world/design.py::_text`, preserve the same accepted
   values and stripped return value. Split rejection into exactly three safe
   conditions at the same path/category:
   - non-string -> `value must be a string`;
   - empty after stripping -> `value must be nonempty after stripping`;
   - over limit -> `value must use at most <limit> code points`.
2. Add focused existing-test coverage for the three conditions, unchanged
   normalization and the real SharedTool `$.ordering` overlength correction.
3. Keep the caller-supplied limits, node source shapes, contracts, compiler
   outputs, semantic revision, graph, route, one-correction/two-call bound,
   Agent/candidate paths and every downstream ABI unchanged.

Do not persist actual text/length, add a diagnostic Artifact, helper/module,
schema engine, retry, prompt paragraph, Skill, node, model switch, relaxed
bound or later-child behavior.

## Checks and proof

Run focused/full pytest, firewall, Ruff, mypy, compileall, diff check and the
10,320 production-line ceiling, then obtain an independent implementation
check. Re-run only the same immutable-parent SharedTool plus first ToolSemantics
suffix and read Observe. Any new failure starts a new diagnosis; a suffix pass
only permits one fresh public Direct E2E.

