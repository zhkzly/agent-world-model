from __future__ import annotations

import copy
import hashlib
import re
from typing import Any


PREFIX_TOKENS = {
    "assert",
    "assertion",
    "bind",
    "binding",
    "entity",
    "field",
    "id",
    "obj",
    "object",
    "op",
    "operation",
    "state",
    "task",
    "tool",
    "verifier",
}


def canonicalize_stage_fields(context: Any, stage: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply framework-owned IDs and rewrite downstream references."""

    normalized = copy.deepcopy(fields)
    if stage == "S2":
        return canonicalize_knowledge_pack_fields(normalized)
    if stage == "S3":
        return canonicalize_environment_spec_fields(context, normalized)
    if stage == "S4":
        return canonicalize_logical_tool_graph_fields(context, normalized)
    if stage == "S5":
        return canonicalize_task_set_fields(context, normalized)
    if stage == "S6":
        return canonicalize_surface_plan_fields(context, normalized)
    if stage == "S7":
        return canonicalize_verifier_plan_fields(context, normalized)
    return normalized


def canonicalize_knowledge_pack_fields(fields: dict[str, Any]) -> dict[str, Any]:
    used_object_ids: set[str] = set()
    object_catalog: dict[str, str] = {}
    for index, item in enumerate(_object_items(fields.get("state_objects")), start=1):
        old_values = [str(item.get(key) or "") for key in ["object_id", "state_object_id", "name"]]
        canonical_id = _unique_id("obj", _first_text(item, ["name", "object_id", "state_object_id"], f"state-object-{index}"), used_object_ids)
        item["object_id"] = canonical_id
        if "state_object_id" in item:
            item["state_object_id"] = canonical_id
        for value in old_values + [canonical_id]:
            _add_aliases(object_catalog, value, canonical_id)

    used_operation_ids: set[str] = set()
    for index, item in enumerate(_object_items(fields.get("operations")), start=1):
        canonical_id = _unique_id("op", _first_text(item, ["name", "operation_id", "tool_id"], f"operation-{index}"), used_operation_ids)
        item["operation_id"] = canonical_id
        if "tool_id" in item:
            item["tool_id"] = canonical_id

    used_rule_ids: set[str] = set()
    for index, item in enumerate(_object_items(fields.get("business_rules")), start=1):
        seed = _first_text(item, ["name", "rule_id", "statement"], f"rule-{index}")
        item["rule_id"] = _unique_id("rule", seed, used_rule_ids)

    used_field_ids: set[str] = set()
    for index, item in enumerate(_object_items(fields.get("verifiable_fields")), start=1):
        object_id = _lookup(object_catalog, _first_text(item, ["object_id", "state_object_id", "field_ref"], ""))
        if object_id:
            item["object_id"] = object_id
        seed = f"{object_id or 'field'}-{_first_text(item, ['name', 'field_id', 'field_ref'], f'field-{index}')}"
        item["field_id"] = _unique_id("field", seed, used_field_ids)

    return fields


def canonicalize_environment_spec_fields(context: Any, fields: dict[str, Any]) -> dict[str, Any]:
    knowledge = _artifact(context, "KnowledgePack")
    object_catalog = _catalog(knowledge.get("state_objects"), ["object_id", "state_object_id"], ["name"])
    operation_catalog = _catalog(knowledge.get("operations"), ["operation_id", "tool_id"], ["name"])

    for item in _object_items(fields.get("state_entities")):
        canonical_id = _lookup(object_catalog, _first_text(item, ["object_id", "state_object_id", "entity_id", "name"], ""))
        if canonical_id:
            item["object_id"] = canonical_id
            if "state_object_id" in item:
                item["state_object_id"] = canonical_id
            if "entity_id" in item:
                item["entity_id"] = canonical_id

    for item in _object_items(fields.get("logical_tools")):
        canonical_id = _lookup(operation_catalog, _first_text(item, ["tool_id", "operation_id", "name"], ""))
        if canonical_id:
            item["tool_id"] = canonical_id
            if "operation_id" in item:
                item["operation_id"] = canonical_id

    return fields


def canonicalize_logical_tool_graph_fields(context: Any, fields: dict[str, Any]) -> dict[str, Any]:
    environment = _artifact(context, "EnvironmentSpec")
    tool_catalog = _catalog(environment.get("logical_tools"), ["tool_id", "operation_id"], ["name"])
    entity_catalog = _catalog(environment.get("state_entities"), ["object_id", "state_object_id", "entity_id"], ["name"])

    for tool in _object_items(fields.get("tools")):
        canonical_tool_id = _lookup(tool_catalog, _first_text(tool, ["tool_id", "operation_id", "name"], ""))
        if canonical_tool_id:
            tool["tool_id"] = canonical_tool_id
        tool["reads"] = [_lookup(entity_catalog, value) or value for value in _string_list(tool.get("reads"))]
        tool["writes"] = [_lookup(entity_catalog, value) or value for value in _string_list(tool.get("writes"))]

    for edge in _object_items(fields.get("edges")):
        from_id = _lookup(tool_catalog, str(edge.get("from_tool_id") or edge.get("from") or ""))
        to_id = _lookup(tool_catalog, str(edge.get("to_tool_id") or edge.get("to") or ""))
        if from_id:
            edge["from_tool_id"] = from_id
        if to_id:
            edge["to_tool_id"] = to_id
        edge.pop("from", None)
        edge.pop("to", None)

    return fields


def canonicalize_task_set_fields(context: Any, fields: dict[str, Any]) -> dict[str, Any]:
    graph = _artifact(context, "LogicalToolGraph")
    environment = _artifact(context, "EnvironmentSpec")
    tool_catalog = _catalog(graph.get("tools"), ["tool_id", "operation_id"], ["name"])
    entity_catalog = _catalog(environment.get("state_entities"), ["object_id", "state_object_id", "entity_id"], ["name"])

    tasks = fields.get("tasks")
    if isinstance(tasks, list):
        used_task_ids: set[str] = set()
        for index, task in enumerate(_object_items(tasks), start=1):
            seed = _first_text(task, ["target_capability", "natural_request", "task_id"], f"task-{index}")
            task_id = _unique_numbered_id("task", index, seed, used_task_ids)
            task["task_id"] = task_id
            task["allowed_logical_tool_ids"] = [_lookup(tool_catalog, value) or value for value in _string_list(task.get("allowed_logical_tool_ids"))]
            task["dependency_path"] = [
                _lookup(tool_catalog, value) or value
                for value in _normalize_dependency_path(task.get("dependency_path"))
            ]
            task["verifier_refs"] = [f"verifier_{task_id}"]
            if isinstance(task.get("framework_replay"), list):
                for call in _object_items(task["framework_replay"]):
                    tool_id = _lookup(tool_catalog, str(call.get("tool_id") or call.get("logical_tool_id") or ""))
                    if tool_id:
                        call["tool_id"] = tool_id

    coverage = fields.get("coverage")
    if isinstance(coverage, dict):
        coverage["tool_ids"] = [_lookup(tool_catalog, value) or value for value in _string_list(coverage.get("tool_ids"))]
        coverage["state_entities"] = [_lookup(entity_catalog, value) or value for value in _string_list(coverage.get("state_entities"))]

    return fields


def canonicalize_surface_plan_fields(context: Any, fields: dict[str, Any]) -> dict[str, Any]:
    graph = _artifact(context, "LogicalToolGraph")
    environment = _artifact(context, "EnvironmentSpec")
    tool_catalog = _catalog(graph.get("tools"), ["tool_id", "operation_id"], ["name"])
    entity_catalog = _catalog(environment.get("state_entities"), ["object_id", "state_object_id", "entity_id"], ["name"])

    bindings = fields.get("bindings")
    if isinstance(bindings, list):
        used_binding_ids: set[str] = set()
        for binding in _object_items(bindings):
            tool_id = _lookup(tool_catalog, str(binding.get("logical_tool_id") or binding.get("tool_id") or "")) or str(binding.get("logical_tool_id") or binding.get("tool_id") or "")
            if tool_id:
                binding["logical_tool_id"] = tool_id
            binding.pop("tool_id", None)
            surface = str(binding.get("surface") or "python")
            binding["binding_id"] = _unique_id("bind", f"{tool_id}-{surface}", used_binding_ids)
            if not binding.get("exposure_name") and tool_id:
                binding["exposure_name"] = _slug(f"{surface}_{tool_id}")
            binding["state_scope"] = [_lookup(entity_catalog, value) or value for value in _string_list(binding.get("state_scope"))]

    surface_status = fields.get("surface_status")
    if isinstance(surface_status, dict):
        fields["surface_status"] = {
            str(surface): _normalize_surface_status_value(value)
            for surface, value in surface_status.items()
        }

    return fields


def canonicalize_verifier_plan_fields(context: Any, fields: dict[str, Any]) -> dict[str, Any]:
    task_set = _artifact(context, "TaskSet")
    task_aliases: dict[str, str] = {}
    for task in task_set.get("tasks", []):
        if isinstance(task, dict) and task.get("task_id"):
            _add_aliases(task_aliases, str(task["task_id"]), str(task["task_id"]))
            _add_aliases(task_aliases, str(task.get("natural_request") or ""), str(task["task_id"]))
            _add_aliases(task_aliases, str(task.get("target_capability") or ""), str(task["task_id"]))

    verifiers = fields.get("verifiers")
    if isinstance(verifiers, list):
        per_task_counts: dict[str, int] = {}
        for verifier in _object_items(verifiers):
            task_id = _lookup(task_aliases, str(verifier.get("task_id") or "")) or str(verifier.get("task_id") or "")
            if task_id:
                verifier["task_id"] = task_id
            per_task_counts[task_id] = per_task_counts.get(task_id, 0) + 1
            suffix = "" if per_task_counts[task_id] == 1 else f"_{per_task_counts[task_id]}"
            verifier_id = f"verifier_{task_id}{suffix}" if task_id else _unique_id("verifier", str(verifier.get("verifier_id") or "verifier"), set())
            verifier["verifier_id"] = verifier_id
            assertions = verifier.get("assertions")
            if isinstance(assertions, list):
                used_assertion_ids: set[str] = set()
                for index, assertion in enumerate(_object_items(assertions), start=1):
                    seed = f"assert_{verifier_id}_{_slug(str(assertion.get('target') or index))}"
                    assertion["assertion_id"] = _unique_raw_id(seed, used_assertion_ids)

    return fields


def _artifact(context: Any, name: str) -> dict[str, Any]:
    artifacts = getattr(context, "artifacts", {})
    artifact = artifacts.get(name, {}) if isinstance(artifacts, dict) else {}
    return artifact if isinstance(artifact, dict) else {}


def _object_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_text(item: dict[str, Any], keys: list[str], fallback: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


def _catalog(items: Any, id_keys: list[str], name_keys: list[str]) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for item in _object_items(items):
        canonical = _first_text(item, id_keys, "")
        if not canonical:
            continue
        for key in id_keys + name_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                _add_aliases(catalog, value, canonical)
        _add_aliases(catalog, canonical, canonical)
    return catalog


def _add_aliases(catalog: dict[str, str], value: str, canonical: str) -> None:
    for alias in _semantic_aliases(value):
        catalog.setdefault(alias, canonical)


def _lookup(catalog: dict[str, str], value: str) -> str:
    for alias in _semantic_aliases(value):
        if alias in catalog:
            return catalog[alias]
    return ""


def _semantic_aliases(value: str) -> set[str]:
    key = _semantic_key(value)
    if not key:
        return set()
    aliases = {key}
    parts = key.split("_")
    if parts:
        singular_parts = list(parts)
        singular_parts[-1] = _singularize(singular_parts[-1])
        aliases.add("_".join(singular_parts))
    return {alias for alias in aliases if alias}


def _semantic_key(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value).lower()).strip("_")
    parts = [part for part in text.split("_") if part]
    while parts and parts[0] in PREFIX_TOKENS:
        parts = parts[1:]
    return "_".join(parts)


def _singularize(value: str) -> str:
    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


def _unique_id(prefix: str, seed: str, used: set[str]) -> str:
    base_key = _semantic_key(seed) or hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    base = f"{prefix}_{base_key}"
    value = base
    counter = 2
    while value in used:
        value = f"{base}_{counter}"
        counter += 1
    used.add(value)
    return value


def _unique_numbered_id(prefix: str, index: int, seed: str, used: set[str]) -> str:
    base_key = _semantic_key(seed) or hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    base = f"{prefix}_{index:03d}_{base_key}"
    value = base
    counter = 2
    while value in used:
        value = f"{base}_{counter}"
        counter += 1
    used.add(value)
    return value


def _unique_raw_id(seed: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_./:#-]+", "_", seed).strip("_") or hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    value = base
    counter = 2
    while value in used:
        value = f"{base}_{counter}"
        counter += 1
    used.add(value)
    return value


def _slug(value: str) -> str:
    return _semantic_key(value) or hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _normalize_dependency_path(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            if not normalized or normalized[-1] != item:
                normalized.append(item)
        elif isinstance(item, dict):
            for key in ["from", "from_tool_id", "to", "to_tool_id"]:
                ref = item.get(key)
                if ref and (not normalized or normalized[-1] != str(ref)):
                    normalized.append(str(ref))
    return normalized


def _normalize_surface_status_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return value
    if value.get("required_for_first_slice") is True:
        return "required_for_first_slice"
    if value.get("compatible") is True:
        return "planned"
    if value.get("compatible") is False:
        return "rejected"
    return value
