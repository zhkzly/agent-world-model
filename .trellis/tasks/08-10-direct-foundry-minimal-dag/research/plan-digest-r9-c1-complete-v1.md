# Direct R9-C1 plan digest under complete-v1

- Child plan revision: R9-C1
- Five-file aggregate SHA-256:
  `baddd746193dc09758ad338543f41c0f3ae827addaba135c667f238ab27c8950`
- Current parent plan digest:
  `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`
- Clean product baseline: `9562c058b61562c11f76d8127f56b68b0f5be2d9`
- Product baseline diff: no changes under `agent_world/`, `tests/`, `config/`,
  `pyproject.toml`, or `README.md` before child implementation.

The five-file child digest uses the declared historical R9-C1 algorithm:
hash raw bytes in this order, emit standard newline-terminated `sha256sum`
lines, then hash their exact concatenation.

```text
03573288978f3c52d92bb85e9265b00155c22bae1113b2197695a3437c8c3e88  .trellis/tasks/08-10-direct-foundry-minimal-dag/prd.md
b27f003fdd040b5539a04cbefea4d0792950201cfcf92f52059d227dee01c77e  .trellis/tasks/08-10-direct-foundry-minimal-dag/design.md
35821202337bf46e8e98bf5eb48a512c1b5d6a1ea80e1c12e26e869133ad983b  .trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md
b88628cc87418bfde175bb4d8e411d64e8a52928ab67640dfc4e9bad110a43e6  .trellis/tasks/08-10-direct-foundry-minimal-dag/implement.md
8a8d324e833beee78b7cfb9ca6624e15315a6895e228b4eef584c00b06a8509e  docs/direct-rewrite-execution-map.zh.md
```

## Baseline facts

- The clean product slice contains nine Python modules with 2,214 production
  lines and six test modules with 1,312 test lines.
- The baseline has 45 passing tests, Ruff format/check, mypy, and compileall.
- `agent_world/foundry.py` is an 801-line monolith. It lets Integration flow to
  Judge without a passed guard and exposes `.foundry-challenge.json` to
  CandidateBuild. The approved implementation must replace this composition,
  not add a parallel orchestration path.
- The baseline already writes `origin=direct` and
  `parent_package_refs=[]`; those facts are preserved and strengthened by
  exact package/Registry closure rather than reimplemented as a second lineage
  authority.
- The public slice has no legacy StateGraph, Scheduler, replay, old `awm` CLI,
  or ExpansionCampaignRunner imports. The legacy firewall remains a required
  check after replacement.

This record proves planning identity and baseline observations only. It does
not authorize implementation or prove Direct, Repair, Expand, Consumer, SFT,
RL, Registry publication, or product completion.
