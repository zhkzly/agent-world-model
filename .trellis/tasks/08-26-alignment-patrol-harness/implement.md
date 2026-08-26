# Implementation

1. Freeze task contract and RED acceptance tests.
2. Add Patrol agent document and closed output-schema tests.
3. Implement deterministic request collection, hashing, parsing, and matching.
4. Implement read-only Trellis invocation, timeout, recursion guard, fail-closed errors.
5. Register deterministic Claude/Codex context-reset hooks without model dispatch.
6. Add workflow/config routing for worker-turn and transition gates.
7. Run unit tests and mutation checks.
8. Run hook-command/config and real Patrol channel smoke tests; record host-event limits.
9. Dispatch a fresh read-only check worker and resolve proven in-scope defects.
10. Record final decisions and commit.

## Validation

```bash
uv run python -m unittest discover -s tests -p 'test_alignment_patrol.py'
python3 .trellis/scripts/run_alignment_patrol.py --help
trellis update --dry-run
git diff --check
```

## Rollback

Revert the harness overlay commit. Baseline `9e791fb` remains intact; no product
code or data migration is involved.
