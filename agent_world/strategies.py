from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageExecutionProfile:
    stage: str
    executor_id: str
    node_purpose: str
    prompt_ref: str = ""
    skill_refs: list[str] = field(default_factory=list)


STAGE_PROFILES: dict[str, StageExecutionProfile] = {
    "PLAN": StageExecutionProfile("PLAN", "structured_agent", "synthesize", "prompts/domain_plan.md"),
    "S0": StageExecutionProfile("S0", "structured_agent", "synthesize", "prompts/need_spec.md"),
    "S1": StageExecutionProfile(
        "S1",
        "research_agent",
        "search",
        "prompts/source_evidence.md",
        ["skills/research-source-discovery/SKILL.md"],
    ),
    "S2": StageExecutionProfile(
        "S2",
        "structured_agent",
        "extract",
        "prompts/knowledge_pack.md",
        ["skills/knowledge-extraction/SKILL.md"],
    ),
    "S3": StageExecutionProfile("S3", "structured_agent", "synthesize", "prompts/environment_spec.md"),
    "S4": StageExecutionProfile(
        "S4",
        "structured_agent",
        "synthesize",
        "prompts/logical_tool_graph.md",
        ["skills/tool-surface-discovery/SKILL.md", "skills/knowledge-extraction/SKILL.md"],
    ),
    "S5": StageExecutionProfile(
        "S5",
        "structured_agent",
        "synthesize",
        "prompts/task_set.md",
        ["skills/task-generation/SKILL.md"],
    ),
    "S6": StageExecutionProfile("S6", "structured_agent", "synthesize", "prompts/surface_plan.md"),
    "S7": StageExecutionProfile(
        "S7",
        "structured_agent",
        "synthesize",
        "prompts/verifier_plan.md",
        ["skills/verifier-planning/SKILL.md"],
    ),
    "S8": StageExecutionProfile(
        "S8",
        "structured_agent",
        "judge",
        "prompts/feasibility_review.md",
        ["skills/feasibility-review/SKILL.md"],
    ),
}


def execution_profile_for_stage(stage: str) -> StageExecutionProfile | None:
    return STAGE_PROFILES.get(stage)
