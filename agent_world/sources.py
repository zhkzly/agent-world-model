from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_world.artifacts import utc_now


SUPPORT_DESK_REQUIRED_STATE_OBJECTS = [
    "customer",
    "ticket",
    "ticket_note",
    "assignment",
    "audit_event",
]
SUPPORT_DESK_REQUIRED_OPERATIONS = [
    "search_tickets",
    "get_ticket",
    "add_ticket_note",
    "update_ticket_priority",
    "assign_ticket",
    "resolve_ticket",
]
SUPPORT_DESK_REQUIRED_RULES = [
    "audit-on-write",
    "python-required",
]


@dataclass(frozen=True)
class LocalSourceDocument:
    path: Path
    kind: str


class LocalSourceConnector:
    """Indexes local PRD/help/schema files into SourceEvidenceIndex fields."""

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path.cwd() if base_dir is None else Path(base_dir)

    def build_index_fields(
        self,
        paths: list[Path],
        *,
        kinds: dict[Path | str, str] | None = None,
    ) -> dict[str, Any]:
        sources = []
        extractable_objects = []
        kinds = kinds or {}
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.base_dir / path
            source_kind = kinds.get(raw_path) or kinds.get(str(raw_path)) or _infer_source_kind(path)
            display_path = _display_path(path, self.base_dir)
            source_id = f"source-{_slug(display_path)}"
            content = path.read_bytes()
            lines = content.decode("utf-8").splitlines()
            sources.append(
                {
                    "source_id": source_id,
                    "kind": source_kind,
                    "uri_or_path": display_path,
                    "version_or_hash": hashlib.sha256(content).hexdigest(),
                    "retrieved_at": utc_now(),
                    "license": "local_fixture",
                    "auth_requirement": "none",
                    "network_requirement": "none",
                    "security_note": "Local source connector read; no network or external credentials.",
                    "section_refs": _section_refs(display_path, lines),
                }
            )
            extractable_objects.extend(_extractable_objects(source_id, display_path, source_kind, lines))
        return {
            "sources": sources,
            "extractable_objects": extractable_objects,
            "mock_boundaries": ["local files only", "no network search", "no external credentials"],
            "open_questions": [],
            "rejected_sources": [],
        }


class SupportDeskLiteKnowledgeExtractor:
    """Extracts the first support-desk-lite KnowledgePack from local evidence."""

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path.cwd() if base_dir is None else Path(base_dir)

    def build_knowledge_fields(self, source_index: dict[str, Any]) -> dict[str, Any]:
        state_objects: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = []
        business_rules: list[dict[str, Any]] = []
        source_by_path = {source["uri_or_path"]: source for source in source_index.get("sources", [])}
        for display_path, source in source_by_path.items():
            path = Path(display_path)
            if not path.is_absolute():
                path = self.base_dir / path
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, start=1):
                parsed = _parse_prd_line(line)
                if not parsed:
                    continue
                item_kind, item_id, attrs, description = parsed
                source_ref = f"{source['source_id']}#L{line_no}"
                if item_kind == "state":
                    state_objects.append(
                        {
                            "object_id": item_id,
                            "name": item_id.replace("_", " "),
                            "fields": _csv(attrs.get("fields", "")),
                            "relations": _csv(attrs.get("relations", "")),
                            "source_refs": [source_ref],
                        }
                    )
                elif item_kind == "operation":
                    writes = _csv(attrs.get("writes", ""))
                    operations.append(
                        {
                            "operation_id": item_id,
                            "name": item_id.replace("_", " "),
                            "inputs": _csv(attrs.get("required", "")) + _csv(attrs.get("optional", "")),
                            "outputs": ["object"],
                            "side_effects": writes,
                            "source_refs": [source_ref],
                            "required_inputs": _csv(attrs.get("required", "")),
                            "optional_inputs": _csv(attrs.get("optional", "")),
                            "reads": _csv(attrs.get("reads", "")),
                            "writes": writes,
                            "idempotency": attrs.get("idempotency", "unknown"),
                        }
                    )
                elif item_kind == "rule":
                    business_rules.append(
                        {
                            "rule_id": item_id,
                            "description": description,
                            "source_refs": [source_ref],
                            "confidence": "high",
                        }
                    )
        state_objects = _dedupe_by_id(state_objects, "object_id")
        operations = _dedupe_by_id(operations, "operation_id")
        business_rules = _dedupe_by_id(business_rules, "rule_id")
        uncertainties = _support_desk_uncertainties(state_objects, operations, business_rules)
        return {
            "state_objects": state_objects,
            "operations": operations,
            "business_rules": business_rules,
            "verifiable_fields": _verifiable_fields(state_objects, operations),
            "uncertainties": uncertainties,
        }


def _infer_source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "prd"
    if suffix in {".txt", ".help"}:
        return "cli_help"
    if suffix in {".json", ".yaml", ".yml"}:
        return "database_schema"
    return "local_files"


def _display_path(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _section_refs(display_path: str, lines: list[str]) -> list[str]:
    refs = []
    for line_no, line in enumerate(lines, start=1):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                refs.append(f"{display_path}#L{line_no}-{_slug(heading)}")
    return refs


def _extractable_objects(source_id: str, display_path: str, kind: str, lines: list[str]) -> list[dict[str, Any]]:
    objects = []
    content = "\n".join(lines)
    if kind == "database_schema":
        objects.extend(_extract_schema_objects(source_id, display_path, content))
    if kind in {"database_schema", "local_files"}:
        objects.extend(_extract_example_objects(source_id, display_path, content))
    for line_no, line in enumerate(lines, start=1):
        parsed = _parse_prd_line(line)
        if parsed:
            item_kind, item_id, _, _ = parsed
            objects.append(
                {
                    "source_id": source_id,
                    "object_kind": _object_kind(item_kind),
                    "name": item_id,
                    "evidence_refs": [f"{display_path}#L{line_no}"],
                }
            )
            continue
        if kind == "cli_help":
            command = _parse_cli_help_command(line)
            if command:
                objects.append(
                    {
                        "source_id": source_id,
                        "object_kind": "operation",
                        "name": command,
                        "evidence_refs": [f"{display_path}#L{line_no}"],
                    }
                )
    return objects


def _extract_schema_objects(source_id: str, display_path: str, content: str) -> list[dict[str, Any]]:
    data = _load_structured_source(content)
    if not isinstance(data, dict):
        return []
    objects = []
    for item in data.get("state_objects", []) or []:
        if not isinstance(item, dict) or not item.get("object_id"):
            continue
        name = str(item["object_id"])
        objects.append(
            {
                "source_id": source_id,
                "object_kind": "state_entity",
                "name": name,
                "evidence_refs": [f"{display_path}#L{_line_number_for(content, f'object_id: {name}')}"],
            }
        )
    return objects


def _extract_example_objects(source_id: str, display_path: str, content: str) -> list[dict[str, Any]]:
    data = _load_structured_source(content)
    if not isinstance(data, dict):
        return []
    objects = []
    for item in data.get("business_rules", []) or []:
        if not isinstance(item, dict) or not item.get("rule_id"):
            continue
        name = str(item["rule_id"])
        objects.append(
            {
                "source_id": source_id,
                "object_kind": "business_rule",
                "name": name,
                "evidence_refs": [f"{display_path}#L{_line_number_for(content, f'rule_id: {name}')}"],
            }
        )
    for item in data.get("examples", []) or []:
        if not isinstance(item, dict) or not item.get("example_id"):
            continue
        name = str(item["example_id"])
        objects.append(
            {
                "source_id": source_id,
                "object_kind": "example",
                "name": name,
                "evidence_refs": [f"{display_path}#L{_line_number_for(content, f'example_id: {name}')}"],
            }
        )
    return objects


def _load_structured_source(content: str) -> Any:
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None


def _line_number_for(content: str, needle: str) -> int:
    for line_no, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return line_no
    return 1


def _parse_prd_line(line: str) -> tuple[str, str, dict[str, str], str] | None:
    match = re.match(r"^\s*-\s+`([^`]+)`\s+(state|operation|rule):\s*(.*)$", line)
    if not match:
        return None
    item_id, item_kind, rest = match.groups()
    if item_kind == "rule":
        return item_kind, item_id, {}, rest.strip()
    attrs = {}
    for chunk in rest.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        attrs[key.strip()] = value.strip()
    return item_kind, item_id, attrs, rest.strip()


def _parse_cli_help_command(line: str) -> str:
    match = re.match(r"^\s{0,4}([a-z][a-z0-9-]{2,})(?:\s|$)", line)
    if not match:
        return ""
    command = match.group(1)
    if command in {"usage", "options", "commands"}:
        return ""
    return command.replace("-", "_")


def _object_kind(item_kind: str) -> str:
    return {
        "state": "state_entity",
        "operation": "operation",
        "rule": "business_rule",
    }[item_kind]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _dedupe_by_id(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        item_id = item[id_key]
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _support_desk_uncertainties(
    state_objects: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    business_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    state_ids = {item["object_id"] for item in state_objects}
    operation_ids = {item["operation_id"] for item in operations}
    rule_ids = {item["rule_id"] for item in business_rules}
    uncertainties = []
    for required in SUPPORT_DESK_REQUIRED_STATE_OBJECTS:
        if required not in state_ids:
            uncertainties.append(
                {
                    "question": f"Missing required support-desk state object evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add source evidence for the state object or stop before synthesis.",
                }
            )
    for required in SUPPORT_DESK_REQUIRED_OPERATIONS:
        if required not in operation_ids:
            uncertainties.append(
                {
                    "question": f"Missing required support-desk operation evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add source evidence for the operation or mark the pipeline needs_human.",
                }
            )
    for required in SUPPORT_DESK_REQUIRED_RULES:
        if required not in rule_ids:
            uncertainties.append(
                {
                    "question": f"Missing required support-desk business rule evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add source evidence for the business rule or stop before implementation.",
                }
            )
    return uncertainties


def _verifiable_fields(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[str]:
    fields = set()
    state_by_id = {item["object_id"]: item for item in state_objects}
    for operation in operations:
        for state_id in operation.get("writes", []):
            for field in state_by_id.get(state_id, {}).get("fields", []):
                fields.add(f"{state_id}.{field}")
    for state_id in ["ticket", "assignment", "ticket_note", "audit_event"]:
        for field in state_by_id.get(state_id, {}).get("fields", []):
            fields.add(f"{state_id}.{field}")
    return sorted(fields)


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "source"
