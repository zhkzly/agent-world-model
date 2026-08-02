# Design a Compact Project-Agent View

Code evidence may accumulate: logs, traces, state, Artifacts, source, tests,
and event records. The project-execution Agent view must remain short and
replaceable. It answers only what is happening, what is known/unknown, and
which local files answer the next question.

## Prefer a path map

Use progressive disclosure. A useful top-level view has:

    Project root: <absolute repository root>
    Active task: .trellis/tasks/<task-id>/
    Current question: <one live decision>
    Known: <one or two safe facts>
    Unknown: <the decisive uncertainty>

    Read on demand:
    - <path> — <question this path answers>
    - <path> — <question this path answers>

Each path may be absolute or repository-relative when it remains inside the
project. Use a URL only for a genuinely external question. Do not copy raw
logs, whole prompts, or every prior attempt into the view.

## Choose the smallest supported change

1. Rewrite or trim the top-level summary.
2. Replace obsolete attempt status with one delta.
3. Add one path and its question.
4. Correct one stable index entry when the relationship recurs.
5. Change a session-start or per-turn hook only when it keeps the map current.
6. Inline one small safe excerpt only when a path cannot resolve the live
   ambiguity quickly enough.

Never add secrets, raw Provider content, or evaluator-only facts for
convenience. Remove or replace stale material at the next attempt rather than
appending lessons to the hook.
