# S3 Activation Input Readiness

Status: **READY for final planning/activation review.**

This ledger records operational locators and checks for the exact upstream
authority required by S3. Paths are non-authoritative and never enter product
identity. Descriptor hashes and JSON claims below are locator checks only; they
do not replace the current production cold readers.

## Exact authority inventory

### Git

- Release ID:
  `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`
- Corpus ID:
  `4fddce70a03b716de69041397b941c4e752e7bf969b8de27d387777ebaaa8344`
- Located Release:
  `/home/kelong/pycodes/foundry-s2-task-foundry/.artifacts/releases/14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80/EnvironmentRelease`
- Located corpus/task store:
  `/tmp/foundry-cp5-relocation-qz0vTG/git`
- Selected/current packs:
  - `242b298797d5dc9cdc558ebb74f59977a35033b113e84f2f1190890f746a48bc`
    — Atom v4
  - `20829f466ca50a02c4d5030bc690e169d46e1d3736b91e7e8d1fa2a7db19b7ef`
    — ForEach v3
  - `b0c519b0d05f327ed64594f7176029b9399523ce1a65e204a62cd6c67b43f7ae`
    — ForEach v3

The first locator search missed this Release because `.artifacts` is ignored
and the search did not use `--no-ignore`. Raw Codex session
`01a0463f-1be1-79e3-abe3-ed1f873e43ab` recovered both the publication result
and exact regeneration command. The original final run reported:

```text
run_root
= /home/kelong/pycodes/foundry-s2-task-foundry/.artifacts/s1-noop-git-final-LVbHOL/run

receipt_digest
= a2db5637233f1825bd806d3824f100e42ac3476f0a00d6ac05f5fc280950b9ac

qualification
= 6 noop + 6 positive
```

Exact regeneration command, if the retained Release is lost:

```bash
cd /home/kelong/pycodes/foundry-s2-task-foundry
run_parent=$(mktemp -d .artifacts/s1-noop-git-final-XXXXXX)
.venv/bin/python /tmp/regenerate_s1_release.py \
  --release .artifacts/releases/bdb1f97e3cded9960df7cf2c8c7112406ded1525c5e2529c962d2d3059d4e810/EnvironmentRelease \
  --verifier-source .artifacts/s1-noop-git-verifier-wsXqwM/run/verifier \
  --run-root "$run_parent/run" \
  --artifact-root .artifacts/releases
```

The regeneration script, source Release and corrected verifier source are all
currently present. Regeneration must reproduce the expected Release ID; a new
identity is not an acceptable substitute.

### SQLite

- Release ID:
  `64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87`
- Corpus ID:
  `a750a8127058f8afc9e2f1c038d1a3c3ef39a9205d2e9b83aee69a221802ae68`
- Located Release:
  `/tmp/foundry-manual-if-9Drp43/cache/releases/64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87`
- Located corpus/task store:
  `/tmp/foundry-cp5-relocation-qz0vTG/sqlite`
- Current packs:
  - `dc3991e5a1fa5938783e4ff732e31477052201752167b511874ef21867b6f943`
    — Atom v4
  - `f825fcf88d07fcda3c0049412cccdd4c8f6d32fba3ab24e02859560392caa940`
    — Atom v4
  - `055a57008c9458952834399d383770571d0951d8399d7aa4a47fbe456d54a0b4`
    — ForEach v3
  - `fc1080b3c6ea45078111353e4c21a45b68d972ac43cdd396852fe02505e2bb7b`
    — If v3

Locator checks on 2026-08-31:

```text
sha256(release.json)
= 64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87

CorpusManifest.corpus_id
= a750a8127058f8afc9e2f1c038d1a3c3ef39a9205d2e9b83aee69a221802ae68
```

### Inherited maintenance

- Release ID:
  `7e2c0718a7de84b07261b729cbe12da86e313c75e4aa107d60ede4c2c34e407a`
- Corpus ID:
  `31eb42b31e621c4ba75892f5866222f80055ccca00a0a018788a4f17d32eb14e`
- Located Release:
  `/tmp/foundry-heldout-handoff-n9uBeF/EnvironmentRelease`
- Located corpus/task store:
  `/tmp/foundry-heldout-handoff-n9uBeF/s2-output`
- Current packs:
  - `acf69d81f78d2c3ed8ceb0dd6b376227d944ee839cee8b0e9491aefd63ca541d`
    — Atom v4
  - `db38c6b49152cb1e27e5f290a590cbc9aba41bceb93bd017ca83e6d982c2d64e`
    — Atom v4
  - `37b8b9f5135102d73e707ebc55af9c30084e9d8564c182d24dcf8482a992da6a`
    — ForEach v3

Locator checks on 2026-08-31:

```text
sha256(release.json)
= 7e2c0718a7de84b07261b729cbe12da86e313c75e4aa107d60ede4c2c34e407a

CorpusManifest.corpus_id
= 31eb42b31e621c4ba75892f5866222f80055ccca00a0a018788a4f17d32eb14e
```

## Current production-reader receipt

On 2026-08-31, the S2 locked Python environment with
`PYTHONPATH=/home/kelong/pycodes/foundry-s3-episode-runtime/src` ran the current
S3 product readers:

- `verify_release_v2` for all three Release roots;
- `read_identity_artifact` with each expected Corpus ID;
- `verify_task_pack_artifact` with every pack directory's expected ID;
- an explicit assertion that every TaskPack Release ID matched its verified
  Release and that every Corpus-selected pack existed.

Result: exit code 0.

```text
Git:
  Release 14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80
  Corpus  4fddce70a03b716de69041397b941c4e752e7bf969b8de27d387777ebaaa8344
  selected/current packs 3/3: Atom v4 + ForEach v3 + ForEach v3

SQLite:
  Release 64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87
  Corpus  a750a8127058f8afc9e2f1c038d1a3c3ef39a9205d2e9b83aee69a221802ae68
  selected/current packs 3/4: Atom v4 + ForEach v3 + If v3
  unselected current Atom v4 is the retained If branch dependency

Maintenance:
  Release 7e2c0718a7de84b07261b729cbe12da86e313c75e4aa107d60ede4c2c34e407a
  Corpus  31eb42b31e621c4ba75892f5866222f80055ccca00a0a018788a4f17d32eb14e
  selected/current packs 3/3: Atom v4 + Atom v4 + ForEach v3
```

The product source trees in the S2 and S3 worktrees are identical; the only
directory diff was ignored Python bytecode under the S2 worktree.

This closes the input-readiness blocker. It does not activate the task:
explicit approval of the final planning summary and `task.py start` remain
separate required gates.
