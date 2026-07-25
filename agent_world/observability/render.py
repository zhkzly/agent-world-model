"""Deterministic Markdown companions for bounded Tier A JSON scenes."""

from __future__ import annotations

from .scene import CoordinateScene, RunSceneIndex, TopIssue


def render_scene(scene: RunSceneIndex, coordinates: tuple[CoordinateScene, ...]) -> str:
    """Render the one-screen map layer without adding facts beyond JSON."""

    lines = [
        f"Status: {scene.overall_status}",
        f"Scope: {_text(scene.scope_id)}",
        f"Frontier: {scene.frontier_size} ({_delta(scene.frontier_delta)})",
    ]
    stuck = (
        _coordinate_by_key(coordinates, scene.stuck_coordinate.coordinate_key)
        if scene.stuck_coordinate
        else None
    )
    if stuck is None:
        lines.append("Stuck: none; all known coordinates are committed.")
    else:
        lines.append(
            "Stuck: "
            f"{_text(stuck.coordinate_label)} [{stuck.pipeline_stage}] "
            f"attempt {stuck.attempt_ordinal}"
        )
        if scene.stuck_reason is not None:
            lines.append(f"Reason: {scene.stuck_reason}")
        if stuck.top_issues:
            lines.append(_why_line(stuck, stuck.top_issues[0]))
        if stuck.repair_target == "generated_candidate_code" and stuck.candidate_file is not None:
            lines.append(
                "Repair target: generated Candidate code. "
                "WorldSpec and the gate are frozen; do not change either (DRIFT)."
            )
        elif stuck.repair_target == "proposal_semantics":
            lines.append(
                "Repair target: the rejected proposal this coordinate just produced. "
                "Revise that output so it satisfies its own declared contract; the "
                "frozen WorldSpec and gate are NOT the repair subject (editing them "
                "is DRIFT)."
            )
        elif stuck.repair_target == "design_worldspec":
            lines.append(
                "Repair target: frozen-design review required. "
                "Do not mutate the frozen WorldSpec or gate during Candidate repair (DRIFT)."
            )
        elif stuck.repair_target == "infrastructure_transport":
            lines.append(
                "Repair target: infrastructure/transport terminal, not a design defect. "
                "The leaf produced no proposal to judge; the frozen WorldSpec and gate "
                "are NOT the repair subject (editing them is DRIFT). Treat as a bounded "
                "backend retry or escalate to human review."
            )
        elif stuck.repair_target == "needs_human":
            lines.append("Repair target: needs human review; no single Candidate file is guessed.")
        if scene.stuck_coordinate is not None:
            lines.append(f"Next read: {scene.stuck_coordinate.markdown_path}")
        if stuck.contract_pointer is not None:
            lines.append(f"Contract: {_text(stuck.contract_pointer)}")
        if stuck.subprocess_pointer is not None:
            lines.append(f"Subprocess: {_text(stuck.subprocess_pointer)}")
    if scene.next_action_hint is not None:
        lines.append(f"Next action: {scene.next_action_hint}")
    return "\n".join(lines) + "\n"


def render_coordinate(scene: CoordinateScene) -> str:
    """Render one terrain-layer coordinate scene from the same JSON facts."""

    lines = [
        f"Coordinate: {_text(scene.coordinate_label)}",
        f"Stage: {scene.pipeline_stage}",
        f"Head: {scene.head_status} (attempt {scene.attempt_ordinal})",
        f"Frontier: {scene.frontier_diff.current_size} ({_delta(scene.frontier_diff.delta)})",
        f"Progress: {scene.frontier_progress}",
        f"Repair authority: {scene.repair_authority}",
    ]
    if scene.failure_code is not None:
        lines.append(f"Failure code: {_text(scene.failure_code)}")
    if scene.candidate_file is not None:
        lines.append(f"Candidate file: {_text(scene.candidate_file)}")
    if scene.repair_target == "generated_candidate_code" and scene.candidate_file is not None:
        lines.append(
            f"Why: {_text(scene.candidate_file)} is the repair subject; "
            "the frozen WorldSpec and gate are not editable (DRIFT)."
        )
    elif scene.repair_target == "proposal_semantics":
        lines.append("Repair target: proposal_semantics")
        lines.append(
            "Why: the proposal produced here violates its own declared contract; "
            "revise this output, not the frozen WorldSpec or gate (DRIFT)."
        )
    elif scene.repair_target == "infrastructure_transport":
        lines.append("Repair target: infrastructure_transport")
        lines.append(
            "Why: an infrastructure/transport terminal (no proposal was produced); "
            "the frozen WorldSpec and gate are not the repair subject (DRIFT). "
            "Bounded backend retry or human review, not a design edit."
        )
    elif scene.repair_target is not None:
        lines.append(f"Repair target: {scene.repair_target}")
    if scene.contract_pointer is not None:
        lines.append(f"Read-only contract: {_text(scene.contract_pointer)}")
    if scene.subprocess_pointer is not None:
        lines.append(f"Subprocess scene: {_text(scene.subprocess_pointer)}")
    if scene.top_issues:
        lines.append("Issues:")
        lines.extend(_issue_line(issue) for issue in scene.top_issues)
    return "\n".join(lines) + "\n"


def _why_line(scene: CoordinateScene, issue: TopIssue) -> str:
    if scene.repair_target == "generated_candidate_code" and scene.candidate_file is not None:
        return (
            f"Why: {_text(scene.candidate_file)} failed gate {_text(issue.code)}: "
            f"{_text(issue.violated_condition)}"
        )
    return f"Why: gate {_text(issue.code)} failed: {_text(issue.violated_condition)}"


def _issue_line(issue: TopIssue) -> str:
    location = "/".join(_text(str(part)) for part in issue.path)
    return (
        f"- [{issue.severity}] {_text(issue.code)} at {location}: "
        f"{_text(issue.violated_condition)} "
        f"(expected {_text(issue.expected_category)})"
    )


def _coordinate_by_key(
    coordinates: tuple[CoordinateScene, ...],
    coordinate_key: str,
) -> CoordinateScene | None:
    return next((item for item in coordinates if item.coordinate_key == coordinate_key), None)


def _delta(value: int) -> str:
    return f"{value:+d}" if value else "=0"


def _text(value: str) -> str:
    return " ".join(value.split())


__all__ = ["render_coordinate", "render_scene"]
