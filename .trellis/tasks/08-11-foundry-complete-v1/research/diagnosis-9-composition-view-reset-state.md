# Diagnosis Record 9: composition view missing reset_state source

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, resume after the idempotency
fix. Terminal: rejected / local_tool_semantics_mismatch, failed=composition,
tool preview_lodging, expected status "" vs actual "not_ready".

## Evidence

The regenerated preview_lodging tool bindings are 5-source per tool; name
resolution ("last binding wins") maps information_ready -> reset_state (idx
26), status -> reset_state (27). Its transitions reference those bindings:
[1] when=[information_ready eq False] -> set status not_ready.
The composition checker in _run_recipe builds its evaluation view with only
argument/tool_result/pre_state/post_state keys; reset_state paths resolve to
_MISSING, the rule never fires in the reference evaluation (expected
status ""), while the runtime evaluates against live state and fires it
(actual "not_ready"). The precondition guard check uses task_trace (which
carries reset_state) and is unaffected.

## Fix

Add "reset_state" to the composition view dict in _run_recipe
({index: task_trace["reset_state"][index]}), so reference evaluation and the
runtime resolve reset_state references identically.
