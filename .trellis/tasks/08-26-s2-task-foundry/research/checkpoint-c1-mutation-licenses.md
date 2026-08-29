# Checkpoint C1 mutation licences

Six executed mutations became RED and restored GREEN:

1. disable accepted source-digest comparison;
2. misattribute verifier import leak as `SemanticsDefect`;
3. remove file mode from canonical project identity;
4. include verifier `actor-view` in project identity/copy;
5. include old author `.venv` in project identity/copy;
6. bypass role-owned conversion of copy-time identity failure.

These prove deterministic materializer enforcement only; the separate live
accepted-verifier run proves the real handoff.
