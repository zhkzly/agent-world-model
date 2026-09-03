# S3 raw-requirement checklist

- [x] Does every rollout use a fresh real environment and only public policy inputs?
- [x] Is the complete observable assistant/tool trajectory preserved?
- [x] Does close/reopen common-Goal evaluation, rather than LLM judgment or a generated Checker, own reward?
- [x] Are `1.0`, `0.0` and `null` physically distinguished?
- [x] Are all 69 TaskPacks and 552 fixed rollout slots represented honestly?
- [x] Is the output sufficient for SFT while remaining tokenizer/trainer neutral?
- [x] Are old S3 formats, compatibility paths and single-Release assumptions absent?
- [x] Are protected Task truth and S2 sampling/filter evidence absent from training views?
- [x] Do artifacts cold-read after relocation and bind exact upstream identities?
- [x] Is completion based on the full Luna campaign rather than a canary or green unit tests?
