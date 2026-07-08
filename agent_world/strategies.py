from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeAttemptProfile:
    stage: str
    executor_id: str
    node_purpose: str
    prompt_ref: str = ""
    skill_refs: list[str] = field(default_factory=list)


STAGE_ATTEMPT_PROFILES: dict[str, NodeAttemptProfile] = {
    "PLAN": NodeAttemptProfile("PLAN", "llm_attempt", "synthesize", "prompts/domain_plan.md"),
    "S0": NodeAttemptProfile("S0", "llm_attempt", "synthesize", "prompts/need_spec.md"),
    "S1": NodeAttemptProfile(
        "S1",
        "agent_attempt",
        "search",
        "prompts/source_evidence.md",
        ["skills/research-source-discovery/SKILL.md"],
    ),
    "S2": NodeAttemptProfile(
        "S2",
        "llm_attempt",
        "extract",
        "prompts/knowledge_pack.md",
        ["skills/knowledge-extraction/SKILL.md"],
    ),
    "S3": NodeAttemptProfile("S3", "llm_attempt", "synthesize", "prompts/environment_spec.md"),
    "S4": NodeAttemptProfile(
        "S4",
        "llm_attempt",
        "synthesize",
        "prompts/logical_tool_graph.md",
        ["skills/tool-surface-discovery/SKILL.md", "skills/knowledge-extraction/SKILL.md"],
    ),
    "S5": NodeAttemptProfile(
        "S5",
        "llm_attempt",
        "synthesize",
        "prompts/task_set.md",
        ["skills/task-generation/SKILL.md"],
    ),
    "S6": NodeAttemptProfile("S6", "llm_attempt", "synthesize", "prompts/surface_plan.md"),
    "S7": NodeAttemptProfile(
        "S7",
        "llm_attempt",
        "synthesize",
        "prompts/verifier_plan.md",
        ["skills/verifier-planning/SKILL.md"],
    ),
}


def attempt_profile_for_stage(stage: str) -> NodeAttemptProfile | None:
    return STAGE_ATTEMPT_PROFILES.get(stage)
