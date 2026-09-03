# S3 raw-requirement checklist

- [ ] Does every rollout use a fresh real environment and only public policy inputs?
- [ ] Is the complete observable assistant/tool trajectory preserved?
- [ ] Does close/reopen common-Goal evaluation, rather than LLM judgment or a generated Checker, own reward?
- [ ] Are `1.0`, `0.0` and `null` physically distinguished?
- [ ] Are all 69 TaskPacks and 552 fixed rollout slots represented honestly?
- [ ] Is the output sufficient for SFT while remaining tokenizer/trainer neutral?
- [ ] Are old S3 formats, compatibility paths and single-Release assumptions absent?
- [ ] Are protected Task truth and S2 sampling/filter evidence absent from training views?
- [ ] Do artifacts cold-read after relocation and bind exact upstream identities?
- [ ] Is completion based on the full Luna campaign rather than a canary or green unit tests?
