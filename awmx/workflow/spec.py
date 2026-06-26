from __future__ import annotations

from awmx.artifacts.schemas import ValidationError, WorkflowNodeSpec, WorkflowSpec
from awmx.workflow.nodes import NODE_TYPE_REGISTRY


def validate_workflow_spec(workflow: WorkflowSpec) -> WorkflowSpec:
    _validate_node_types(workflow.nodes)
    _validate_budgets(workflow)
    topological_order(workflow)
    return workflow


def topological_order(workflow: WorkflowSpec) -> list[WorkflowNodeSpec]:
    node_map = {node.id: node for node in workflow.nodes}
    original_order = {node.id: index for index, node in enumerate(workflow.nodes)}
    incoming_count = {node.id: len(node.needs) for node in workflow.nodes}
    dependents: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for node in workflow.nodes:
        for dependency in node.needs:
            dependents[dependency].append(node.id)

    ready = sorted(
        [node.id for node in workflow.nodes if incoming_count[node.id] == 0],
        key=original_order.__getitem__,
    )
    ordered: list[WorkflowNodeSpec] = []

    while ready:
        node_id = ready.pop(0)
        ordered.append(node_map[node_id])
        for dependent_id in sorted(dependents[node_id], key=original_order.__getitem__):
            incoming_count[dependent_id] -= 1
            if incoming_count[dependent_id] == 0:
                ready.append(dependent_id)
                ready.sort(key=original_order.__getitem__)

    if len(ordered) != len(workflow.nodes):
        raise ValidationError("workflow contains a dependency cycle")
    return ordered


def _validate_node_types(nodes: list[WorkflowNodeSpec]) -> None:
    for node in nodes:
        if node.node_type not in NODE_TYPE_REGISTRY:
            raise ValidationError(f"unknown node type: {node.node_type}")


def _validate_budgets(workflow: WorkflowSpec) -> None:
    max_nodes = workflow.budgets.get("max_nodes")
    if max_nodes is not None and (not isinstance(max_nodes, int) or max_nodes < 1):
        raise ValidationError("budgets.max_nodes must be a positive integer")
