# Checkpoint C/D filesystem/Git production evidence

Date: 2026-08-30

## Frozen inputs

- Expected Semantics: `9a4a1c5800326f36f0010410a48bad50498878baae6d315b1081401292c363e7`
- Public Surface: `34e448946d36baa964d7c46d6d9a42f4d840c88d7ab5b1af94ba3450a344335b`
- Actor: `055dfeae0ce57b32e0924ea37c6bc100f83353e059e65d1d0b2fc2f0eb439587`
- TaskSemantics: `ead395edd3329b0862bec8e410f7079d6a13e7223ffc24490e62f02c94e9b5f2`
- Independent verifier: `249f03c93d4f45ebebc300fc03c12263b976cbb804d084b81d979f917e250560`
- Core: `ce26a09b89c4ee3ef7487b1fae968f4af8add4ce7f47bd054779455799e9ed43`

## Qualification

Production `run_v2_qualification` returned a strict report with:

- 18 physical cases: positive 6, fresh replay 6, missing process 2, no-op 1,
  wrong answer 1, wrong target 1 and collateral 1;
- two independent result-axis mutants, one for each reader lineage;
- capabilities `CAP-GIT-INSPECT`, `CAP-GIT-REFUSAL` and
  `CAP-GIT-UPDATE-COMMIT`;
- StartCases `clean` and `pending-change`;
- evidence digest `8a3ed79c665951f954c46b5385c2b566dc7b9e6b2e308e4ac064e055cf18f179`;
- strict passed receipt digest
  `c99db13a65cff30fc9a236a9f6cc811a419fbc2075a2567dcfc6563414bfa90c`.

Every reader disagreement failed immediately with category, capability,
semantic key and per-axis values. Author repairs remained in their original
independent lineage; Framework did not learn Git field names.

## Publication and cold use

- Release ID: `175d92d1d8c107ad6cabc6b5b39c7334216b849a3971a5233781ae8ddbff393e`.
- Directory verification and audit-only replay returned that ID.
- Deterministic ZIP was renamed and relocated before `prepare_release`; the
  prepared release returned the same ID.
- A fresh Consumer session reproduced two sealed StartCases, three capabilities
  and six tools, then executed real `reset()` and `list_tracked_files` successfully.
- Canonical ZIP SHA-256:
  `6bb57a0744127accbe8bd60a657d77566eba6c4523044d830d78487ee07d652e`.

The first ZIP exposed that file-only archives omit empty `.git` directories,
changing sealed physical tree identity. The corrected production ZIP includes
explicit directory entries and modes, and the same relocated cold path passed.

## Repository gates

- `UV_CACHE_DIR=/tmp/foundry-s2-uv-cache uv lock --check`
- `.venv/bin/ruff check src tests`
- `.venv/bin/ruff format --check src tests`
- `.venv/bin/mypy src`
- `.venv/bin/python -m pytest -q`
- `git diff --check`

All returned exit code 0. Five mutation licences independently killed:

1. selecting a reader-mutant axis that was not independently false;
2. making optional near-miss/alternative-route evidence mandatory;
3. reverting query wrong-target discrimination to a state-only effect check;
4. dropping directory entries from the production ZIP writer;
5. dropping directory-mode restoration from ZIP staging.

## Non-claims

This closes the required filesystem/Git Checkpoint C/D repeat. It does not
claim Git Task compilation/admission, corpus floors, held-out generalization or
downstream paper value; those remain Checkpoints E-G.
