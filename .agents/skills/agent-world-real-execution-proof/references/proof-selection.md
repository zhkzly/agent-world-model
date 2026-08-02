# Select the True Proof Boundary

Choose the narrowest executable boundary that can falsify the claim. Preserve
the exact frozen input closure whenever it exists.

| Changed or claimed surface | Required proof |
| --- | --- |
| Code, feedback, validator, parser, scheduler, scene, projection, verifier, CLI, replay, resume, or isolation | Construct or preserve realistic input and execute the actual local boundary. |
| CLI/execution safety | Execute the actual CLI through uv and show its InvocationBackend/control path, not a generic shell fallback. |
| Verifier or gate | Use a Candidate that should pass or fail and prove the real verifier/Judge decision. |
| Project-execution Agent view | Give a fresh project Agent only the top-level view and live question; it must name precise reads without broad search. |
| Direct Prompt/input, model/profile/route/response mode | Run one isolated DirectLlmBackend node with its declared envelope. Verify zero Runtime Skills, Hooks, tool/profile instructions, and no Provider instructions field; read its scene. |
| Codex Agent Skill/tool/profile | Run one isolated real Codex SDK Agent turn with the actual mounted bundle and granted tools. When tool dispatch matters, make the Agent use the granted tool. Verify full bundle identity, references/scripts/assets, and executable bits. |
| Repair/correction | Run the normal Scheduler path with real RepairAction authority; a diagnostic one-attempt run proves only initial generation/validation. |
| Immediate Integration / E2E | Run the smallest predecessor/successor chain after the affected leaf passes; run the wider chain only after all affected leaf and immediate Integration boundaries pass. |

For runtime/Judge isolation, prove the intended isolated boundary actually ran
and did not silently use host-local behavior. For replay/resume, prove the
actual state transition and show retired replay/fixture/ABI paths are not the
normal success route.

Before a change to any Prompt, Agent Runtime Skill, profile, compiler, or
feedback surface, audit live siblings using the same mechanism. One discovered
omission often has homologous paths; do not blindly patch unrelated siblings.
