# CP1 YES/NO Checklist

- [x] Does every new object have one named producer and consumer?
- [x] Are release, actor runtime, semantics runtime and materialization identities non-circular and content-bound?
- [x] Does the current v1 release fail the v2 admission contract?
- [x] Can the public projection deserialize no trusted field?
- [x] Can trusted calls be represented without implying state mutation or actor import access?
- [x] Are all non-success outcomes typed instead of collapsed into booleans/strings?
- [x] Are Graph/Programmatic, compatibility, domain templates and CP5–CP7 paths still absent?
- [x] Does each acceptance test fail before implementation and kill its corresponding mutant?
- [x] Do locked sync, Ruff, format, Mypy and full Pytest pass after implementation?
