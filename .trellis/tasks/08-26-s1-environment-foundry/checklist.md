# User-Source Implementation Checklist

Source: user turn recovered from Codex session `01a03968-c44f-7311-aac2-8fb3b080e55d`; evaluate every item as YES/NO with physical evidence.

- [ ] F1 — No “只注意跑通代码”: tool calls are not dict/map hard-coding or an MVP substitute; successful claims execute real environment code and native state transitions.
- [ ] F2 — No “单纯为了跑通而跑代码”: tests prove the project purpose and semantic behavior, not merely unit/schema/startup green.
- [ ] F3 — No causal-free patching: a failure is attributed through View/Prompt/Skill/Code/Feedback before changing code; no one-off hard-code, fallback, coercion, or normalization.
- [ ] F4 — No redundant design: use a real workspace and mature libraries; do not build unnecessary Codex sandboxes, protocols, workflow engines, or imagined extensibility.
- [ ] F5 — Skills/harness stay live: when behavior is wrong, inspect project/runtime Skills, prompt, context, data, provider, permission and infrastructure instead of assuming a code defect.
- [ ] F6 — Research uses real Search/Fetch/Extract and treats web/OpenViking/model output critically; model prior or search snippets are not evidence.
- [ ] F7 — The canonical PRD/design/implement remain unchanged unless the user explicitly approves the exact semantic modification.
- [ ] F8 — Fake providers and hand-authored fixtures may test mechanics or rejection only; they cannot produce `Released` or product-completion evidence.
- [ ] F9 — At each critical slice and before completion/commit, independent Trellis channel reviewers check the current diff against F1-F8 and the whole product chain.
- [ ] F10 — Completion requires a cold, directly consumable EnvironmentRelease and honest scope evidence; a checkpoint, package shape, or successful demo is not completion.
