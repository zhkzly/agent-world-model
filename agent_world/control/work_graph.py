"""Framework-owned WorkDefinition catalog and dependency/invalidation graph."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    ContentHash,
    Identifier,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

from .work import (
    ArtifactSlotContract,
    AssurancePolicy,
    OperationBudget,
    ProposalPolicy,
    RepairPolicy,
    ValidationPolicy,
    WorkCoordinate,
    WorkDefinition,
)

if TYPE_CHECKING:
    from agent_world.designer.models import ToolCouplingPlan


class WorkGraphError(RuntimeError):
    """The framework WorkGraph is incomplete, cyclic, or identity-conflicting."""


_REQUIRED_PRODUCTION_STAGES = frozenset(
    {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
        ("design", "world_rules"),
        ("design", "task_curriculum"),
        ("design", "modeling_boundary"),
        ("build", "candidate_build"),
        ("verifier", "verifier_intent"),
        ("integration", "runtime_integration"),
        ("judge", "release_assurance"),
        ("release", "observability_closure"),
        ("release", "package"),
        ("registry", "publication"),
    }
)
_BEHAVIOR_STAGES = frozenset({"shared_tool_semantics", "tool_semantics_batch"})


def _has_complete_production_topology(
    coordinates: Iterable[WorkCoordinate],
    terminals: Iterable[WorkCoordinate],
) -> bool:
    """Return whether the only releasable shape has every causal product stage.

    A milestone name is not evidence that its work happened.  Release eligibility
    therefore derives from the frozen coordinates themselves, including actual
    behavior work, and from a sole Registry publication terminal.
    """

    items = tuple(coordinates)
    stage_pairs = {(item.component, item.stage) for item in items}
    terminal_pairs = {(item.component, item.stage) for item in terminals}
    return (
        _REQUIRED_PRODUCTION_STAGES <= stage_pairs
        and any(item.component == "design" and item.stage in _BEHAVIOR_STAGES for item in items)
        and terminal_pairs == {("registry", "publication")}
    )


def _stable_work_identity_digest(coordinate: WorkCoordinate) -> str:
    """Derive logical Work identity only from its stable scheduling coordinate."""

    return coordinate.coordinate_key.removeprefix("sha256:")[:24]


class WorkGraphNodeBinding(V2Contract):
    coordinate: WorkCoordinate
    work_id: Identifier
    definition_digest: ContentHash


class JoinPolicy(V2Contract):
    """Deterministic aggregate readiness for one bounded physical group."""

    # Threshold joins are deliberately not exposed until the runtime can bind
    # the exact selected child-commit set.  Advertising ``at_least`` while the
    # aggregate WorkDefinition still depends on every member made the contract
    # impossible to execute.
    mode: Literal["all"] = "all"
    retain_successful_siblings: Literal[True] = True
    cancel_running_on_failure: Literal[False] = False


class WorkGroupDefinition(V2Contract):
    """Frozen member set and aggregate coordinate for dynamic physical work."""

    group_id: Identifier
    scope_id: Identifier
    member_coordinates: Annotated[tuple[WorkCoordinate, ...], Field(min_length=1)]
    aggregate_coordinate: WorkCoordinate
    join_policy: JoinPolicy = Field(default_factory=JoinPolicy)

    @model_validator(mode="after")
    def validate_group(self) -> WorkGroupDefinition:
        keys = tuple(item.coordinate_key for item in self.member_coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("WorkGroup members must be unique")
        if self.aggregate_coordinate.coordinate_key in keys:
            raise ValueError("WorkGroup aggregate cannot also be a physical member")
        if any(item.scope_id != self.scope_id for item in self.member_coordinates) or (
            self.aggregate_coordinate.scope_id != self.scope_id
        ):
            raise ValueError("WorkGroup cannot mix scopes")
        if any(item.group_id != self.group_id for item in self.member_coordinates):
            raise ValueError("WorkGroup member coordinates must bind the group id")
        if any(item.shard_id is None for item in self.member_coordinates):
            raise ValueError("WorkGroup members must be physical shards")
        if self.aggregate_coordinate.shard_id is not None:
            raise ValueError("WorkGroup aggregate cannot be a shard")
        return self


class WorkGraphGroupBinding(V2Contract):
    group_id: Identifier
    group_digest: ContentHash
    aggregate_coordinate: WorkCoordinate
    member_coordinates: tuple[WorkCoordinate, ...]


class WorkGraphMilestone(V2Contract):
    """Named readiness milestone; publication and release-candidate readiness differ."""

    milestone_id: Identifier
    kind: Literal["progress", "release_candidate", "released"] = "progress"
    required_coordinates: Annotated[tuple[WorkCoordinate, ...], Field(min_length=1)]
    establishes: Identifier

    @model_validator(mode="after")
    def validate_milestone(self) -> WorkGraphMilestone:
        keys = tuple(item.coordinate_key for item in self.required_coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("WorkGraph milestone coordinates must be unique")
        return self


class WorkGraphMilestoneBinding(V2Contract):
    milestone_id: Identifier
    milestone_digest: ContentHash
    kind: Literal["progress", "release_candidate", "released"]
    required_coordinates: tuple[WorkCoordinate, ...]
    establishes: Identifier


class WorkGraphManifest(V2Contract):
    """Persistent topology identity; readiness and release bind this exact graph."""

    graph_id: Identifier
    scope_id: Identifier
    topology_id: Identifier
    mode: Literal["diagnostic", "production"]
    node_bindings: tuple[WorkGraphNodeBinding, ...]
    group_bindings: tuple[WorkGraphGroupBinding, ...] = ()
    milestone_bindings: tuple[WorkGraphMilestoneBinding, ...] = ()
    required_terminal_coordinates: tuple[WorkCoordinate, ...]
    external_root_refs: tuple[ArtifactRef, ...] = ()
    diagnostic_only: bool
    releasable: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> WorkGraphManifest:
        if not self.node_bindings or not self.required_terminal_coordinates:
            raise ValueError("WorkGraphManifest requires nodes and terminals")
        coordinate_keys = tuple(item.coordinate.coordinate_key for item in self.node_bindings)
        if len(set(coordinate_keys)) != len(coordinate_keys):
            raise ValueError("WorkGraphManifest node coordinates must be unique")
        if len({item.work_id for item in self.node_bindings}) != len(self.node_bindings):
            raise ValueError("WorkGraphManifest work ids must be unique")
        if len({item.group_id for item in self.group_bindings}) != len(self.group_bindings):
            raise ValueError("WorkGraphManifest group ids must be unique")
        for group in self.group_bindings:
            group_keys = {
                group.aggregate_coordinate.coordinate_key,
                *(item.coordinate_key for item in group.member_coordinates),
            }
            if not group_keys <= set(coordinate_keys):
                raise ValueError("WorkGraphManifest group references unregistered nodes")
        if len({item.milestone_id for item in self.milestone_bindings}) != len(
            self.milestone_bindings
        ):
            raise ValueError("WorkGraphManifest milestone ids must be unique")
        for kind in ("release_candidate", "released"):
            if sum(item.kind == kind for item in self.milestone_bindings) > 1:
                raise ValueError(f"WorkGraphManifest has duplicate {kind} milestones")
        if any(
            coordinate.coordinate_key not in set(coordinate_keys)
            for milestone in self.milestone_bindings
            for coordinate in milestone.required_coordinates
        ):
            raise ValueError("WorkGraphManifest milestone references unregistered nodes")
        terminal_keys = tuple(item.coordinate_key for item in self.required_terminal_coordinates)
        if len(set(terminal_keys)) != len(terminal_keys) or not set(terminal_keys) <= set(
            coordinate_keys
        ):
            raise ValueError("WorkGraphManifest terminals must be unique registered nodes")
        if len(set(self.external_root_refs)) != len(self.external_root_refs):
            raise ValueError("WorkGraphManifest external roots must be unique")
        release_kinds = {item.kind for item in self.milestone_bindings}
        has_complete_release_milestones = {
            "release_candidate",
            "released",
        } <= release_kinds
        publication_terminal = any(
            item.component == "registry" and item.stage == "publication"
            for item in self.required_terminal_coordinates
        )
        if self.mode == "diagnostic":
            if not self.diagnostic_only or self.releasable:
                raise ValueError("diagnostic WorkGraphManifest cannot be releasable")
        elif self.diagnostic_only:
            raise ValueError("production WorkGraphManifest cannot be diagnostic")
        complete_topology = _has_complete_production_topology(
            (item.coordinate for item in self.node_bindings),
            self.required_terminal_coordinates,
        )
        if self.releasable != (
            self.mode == "production"
            and has_complete_release_milestones
            and publication_terminal
            and complete_topology
        ):
            raise ValueError(
                "WorkGraphManifest releasable flag must bind complete publication topology"
            )
        if any(item.coordinate.scope_id != self.scope_id for item in self.node_bindings):
            raise ValueError("WorkGraphManifest cannot mix scopes")
        return self

    @property
    def graph_digest(self) -> ContentHash:
        return self.content_digest()


class WorkGraphEpoch(V2Contract):
    """One immutable topology freeze for a single GenerationContext.

    Dynamic behavior/verifier groups are materialized only after grounded
    Architecture and the compiled curriculum reveal two different bounded
    physical member sets.  ``bootstrap`` therefore freezes Research through
    Architecture, ``design`` freezes behavior through the deterministic
    VerifierPlan, and only ``final`` retains both closures before it appends
    Build through Registry.  These are graph-freezing boundaries within one
    Job and one budget ledger, never separate pipelines or authorities.
    """

    epoch_id: Identifier
    scope_id: Identifier
    epoch_kind: Literal["bootstrap", "design", "final"]
    context_ref: ArtifactRef
    manifest_ref: ArtifactRef
    predecessor_epoch_ref: ArtifactRef | None = None
    retained_commit_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_epoch(self) -> WorkGraphEpoch:
        if self.context_ref.artifact_type != "control.generation_context":
            raise ValueError("WorkGraphEpoch must bind a GenerationContext Artifact")
        if self.manifest_ref.artifact_type != "control.work_graph_manifest":
            raise ValueError("WorkGraphEpoch must bind a WorkGraphManifest Artifact")
        if any(ref.artifact_type != "control.work_commit" for ref in self.retained_commit_refs):
            raise ValueError("WorkGraphEpoch retained refs must be WorkCommits")
        if len(set(self.retained_commit_refs)) != len(self.retained_commit_refs):
            raise ValueError("WorkGraphEpoch retained commits must be unique")
        if self.epoch_kind == "bootstrap":
            if self.predecessor_epoch_ref is not None or self.retained_commit_refs:
                raise ValueError("bootstrap WorkGraphEpoch cannot retain a predecessor closure")
        elif self.predecessor_epoch_ref is None or not self.retained_commit_refs:
            raise ValueError(
                "non-bootstrap WorkGraphEpoch requires predecessor and retained commits"
            )
        elif self.predecessor_epoch_ref.artifact_type != "control.work_graph_epoch":
            raise ValueError("non-bootstrap WorkGraphEpoch predecessor has the wrong artifact type")
        return self


class ResolvedWorkInputs(V2Contract):
    """Framework-derived immutable inputs for one exact graph coordinate."""

    coordinate: WorkCoordinate
    graph_digest: ContentHash
    external_input_refs: tuple[ArtifactRef, ...] = ()
    parent_commit_refs: tuple[ArtifactRef, ...] = ()
    parent_output_refs: tuple[ArtifactRef, ...] = ()
    input_fingerprint: ContentHash

    @model_validator(mode="after")
    def validate_inputs(self) -> ResolvedWorkInputs:
        for refs in (
            self.external_input_refs,
            self.parent_commit_refs,
            self.parent_output_refs,
        ):
            if len(set(refs)) != len(refs):
                raise ValueError("resolved work input refs must be unique")
        if any(ref.artifact_type != "control.work_commit" for ref in self.parent_commit_refs):
            raise ValueError("resolved parent refs must be WorkCommit Artifacts")
        expected = sha256_digest(
            canonical_json_bytes(
                {
                    "graph_digest": self.graph_digest,
                    "coordinate": self.coordinate.model_dump(mode="json"),
                    "external_input_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.external_input_refs
                    ),
                    "parent_commit_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.parent_commit_refs
                    ),
                    "parent_output_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.parent_output_refs
                    ),
                }
            )
        )
        if self.input_fingerprint != expected:
            raise ValueError("resolved work input fingerprint mismatch")
        return self

    @property
    def all_input_refs(self) -> tuple[ArtifactRef, ...]:
        return tuple(dict.fromkeys((*self.external_input_refs, *self.parent_output_refs)))


@dataclass(frozen=True, slots=True)
class GenerationWorkGraph:
    """Immutable, digest-bound topology authority for one generation scope.

    A diagnostic graph can exercise an isolated slice but can never be projected
    as release-ready.  A production graph freezes its required terminal
    coordinates so deleting a node cannot silently weaken readiness.
    """

    _definitions: tuple[WorkDefinition, ...]
    _groups: tuple[WorkGroupDefinition, ...]
    _milestones: tuple[WorkGraphMilestone, ...]
    mode: Literal["diagnostic", "production"]
    required_terminal_coordinates: tuple[WorkCoordinate, ...]

    @classmethod
    def compile(
        cls,
        definitions: Iterable[WorkDefinition],
        *,
        mode: Literal["diagnostic", "production"],
        strict_input_contracts: bool = False,
        required_terminal_coordinates: Iterable[WorkCoordinate] | None = None,
        groups: Iterable[WorkGroupDefinition] = (),
        milestones: Iterable[WorkGraphMilestone] = (),
    ) -> GenerationWorkGraph:
        items = tuple(
            WorkDefinition.model_validate(item.model_dump(mode="python")) for item in definitions
        )
        if not items:
            raise WorkGraphError("WorkGraph cannot be empty")
        by_key = {item.coordinate.coordinate_key: item for item in items}
        if len(by_key) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate coordinates")
        if len({item.work_id for item in items}) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate work ids")
        scopes = {item.coordinate.scope_id for item in items}
        if len(scopes) > 1:
            raise WorkGraphError("one WorkGraph cannot mix generation scopes")
        group_items = tuple(
            WorkGroupDefinition.model_validate(item.model_dump(mode="python")) for item in groups
        )
        if len({item.group_id for item in group_items}) != len(group_items):
            raise WorkGraphError("WorkGraph contains duplicate group ids")
        registered_keys = set(by_key)
        for group in group_items:
            if group.scope_id not in scopes:
                raise WorkGraphError("WorkGroup scope differs from its WorkGraph")
            group_keys = {
                group.aggregate_coordinate.coordinate_key,
                *(item.coordinate_key for item in group.member_coordinates),
            }
            if not group_keys <= registered_keys:
                raise WorkGraphError("WorkGroup references unregistered coordinates")
            aggregate = by_key[group.aggregate_coordinate.coordinate_key]
            member_keys = {item.coordinate_key for item in group.member_coordinates}
            dependency_keys = {item.coordinate_key for item in aggregate.dependency_coordinates}
            if member_keys != dependency_keys:
                raise WorkGraphError(
                    "WorkGroup aggregate dependencies must equal its frozen members"
                )
        milestone_items = tuple(
            WorkGraphMilestone.model_validate(item.model_dump(mode="python")) for item in milestones
        )
        if len({item.milestone_id for item in milestone_items}) != len(milestone_items):
            raise WorkGraphError("WorkGraph contains duplicate milestone ids")
        for kind in ("release_candidate", "released"):
            if sum(item.kind == kind for item in milestone_items) > 1:
                raise WorkGraphError(f"WorkGraph contains duplicate {kind} milestones")
        if any(
            coordinate.coordinate_key not in registered_keys
            for milestone in milestone_items
            for coordinate in milestone.required_coordinates
        ):
            raise WorkGraphError("WorkGraph milestone references unregistered coordinates")
        for item in items:
            missing = tuple(
                dependency
                for dependency in item.dependency_coordinates
                if dependency.coordinate_key not in by_key
            )
            if missing:
                raise WorkGraphError(
                    f"WorkGraph dependency is not registered: {missing[0].coordinate_key}"
                )
            missing_repair_targets = tuple(
                target
                for target in item.repair_target_coordinates
                if target.coordinate_key not in by_key
            )
            if missing_repair_targets:
                raise WorkGraphError(
                    "WorkGraph repair target is not registered: "
                    f"{missing_repair_targets[0].coordinate_key}"
                )
            ancestors = cls._ancestor_keys(item.coordinate, by_key)
            invalid_repair_targets = tuple(
                target
                for target in item.repair_target_coordinates
                if target.coordinate_key not in ancestors
            )
            if invalid_repair_targets:
                raise WorkGraphError(
                    "WorkGraph repair target must be a causal dependency ancestor: "
                    f"{invalid_repair_targets[0].coordinate_key}"
                )
        cls._assert_acyclic(items, by_key)
        if strict_input_contracts:
            cls._assert_declared_input_sources(items, by_key)
        terminals = tuple(
            WorkCoordinate.model_validate(item.model_dump(mode="python"))
            for item in (
                required_terminal_coordinates
                if required_terminal_coordinates is not None
                else cls._terminal_coordinates(items)
            )
        )
        if not terminals or len({item.coordinate_key for item in terminals}) != len(terminals):
            raise WorkGraphError("WorkGraph requires unique terminal coordinates")
        unknown = tuple(item for item in terminals if item.coordinate_key not in by_key)
        if unknown:
            raise WorkGraphError(
                f"WorkGraph terminal is not registered: {unknown[0].coordinate_key}"
            )
        actual_terminal_keys = {item.coordinate_key for item in cls._terminal_coordinates(items)}
        if any(item.coordinate_key not in actual_terminal_keys for item in terminals):
            raise WorkGraphError("required WorkGraph terminals must be dependency leaves")
        if mode == "production":
            if {item.coordinate_key for item in terminals} != actual_terminal_keys:
                raise WorkGraphError(
                    "production WorkGraph must freeze every dependency leaf as required"
                )
            if not _has_complete_production_topology(
                (item.coordinate for item in items), terminals
            ):
                raise WorkGraphError(
                    "production WorkGraph requires the complete generation topology"
                )
        return cls(
            tuple(sorted(items, key=lambda item: item.coordinate.coordinate_key)),
            tuple(sorted(group_items, key=lambda item: item.group_id)),
            tuple(sorted(milestone_items, key=lambda item: item.milestone_id)),
            mode,
            tuple(sorted(terminals, key=lambda item: item.coordinate_key)),
        )

    @staticmethod
    def _ancestor_keys(
        coordinate: WorkCoordinate,
        by_key: dict[str, WorkDefinition],
    ) -> set[str]:
        """Return transitive readiness ancestors for repair-edge validation."""

        ancestors: set[str] = set()
        pending = deque(by_key[coordinate.coordinate_key].dependency_coordinates)
        while pending:
            parent = pending.popleft()
            if parent.coordinate_key in ancestors:
                continue
            ancestors.add(parent.coordinate_key)
            pending.extend(by_key[parent.coordinate_key].dependency_coordinates)
        return ancestors

    @staticmethod
    def _terminal_coordinates(
        definitions: tuple[WorkDefinition, ...],
    ) -> tuple[WorkCoordinate, ...]:
        dependency_keys = {
            dependency.coordinate_key
            for item in definitions
            for dependency in item.dependency_coordinates
        }
        return tuple(
            item.coordinate
            for item in definitions
            if item.coordinate.coordinate_key not in dependency_keys
        )

    @staticmethod
    def _assert_acyclic(
        definitions: tuple[WorkDefinition, ...],
        by_key: dict[str, WorkDefinition],
    ) -> None:
        indegree = {item.coordinate.coordinate_key: 0 for item in definitions}
        children: dict[str, list[str]] = {key: [] for key in indegree}
        for item in definitions:
            child_key = item.coordinate.coordinate_key
            for dependency in item.dependency_coordinates:
                parent_key = dependency.coordinate_key
                indegree[child_key] += 1
                children[parent_key].append(child_key)
        ready = deque(key for key, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            key = ready.popleft()
            visited += 1
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(by_key):
            raise WorkGraphError("WorkGraph contains a dependency cycle")

    @staticmethod
    def _assert_declared_input_sources(
        definitions: tuple[WorkDefinition, ...],
        by_key: dict[str, WorkDefinition],
    ) -> None:
        """Prove every declared non-root input can come from a direct parent.

        A dependency is a *causal* edge: changing that parent invalidates the
        child.  An input slot is a separate, least-privilege disclosure edge:
        it names exactly which parent Artifacts may enter the leaf.  Keeping
        these two relations distinct lets a code-only observer depend on a
        completed Judge without receiving its sealed report, while a Builder
        receives only the EnvironmentDesign it actually needs.

        This check catches the opposite error at graph-freeze time: a leaf
        declaring an Artifact that no direct producer can supply.  Runtime
        then filters parent consumer refs through these slots and keeps its
        strict unexpected-ref check as a final fence.
        """

        for definition in definitions:
            parents = tuple(
                by_key[parent.coordinate_key]
                for parent in definition.dependency_coordinates
            )
            if parents and not definition.input_slots:
                raise WorkGraphError(
                    "strict WorkGraph requires an explicit input disclosure contract: "
                    f"{definition.coordinate.coordinate_key}"
                )
            for slot in definition.input_slots:
                if slot.producer_component == "external":
                    continue
                matching_output_slots = tuple(
                    output_slot
                    for parent in parents
                    if parent.coordinate.component == slot.producer_component
                    for output_slot in parent.output_slots
                    if set(output_slot.artifact_types) & set(slot.artifact_types)
                )
                maximum_available = sum(
                    output_slot.maximum_count for output_slot in matching_output_slots
                )
                minimum_available = sum(
                    output_slot.minimum_count for output_slot in matching_output_slots
                )
                if not matching_output_slots or slot.minimum_count > maximum_available:
                    raise WorkGraphError(
                        "WorkGraph input slot has no sufficient direct parent output: "
                        f"{definition.coordinate.coordinate_key}:{slot.slot_id}"
                    )
                if slot.maximum_count < minimum_available:
                    raise WorkGraphError(
                        "WorkGraph input slot cannot accept every required direct parent output: "
                        f"{definition.coordinate.coordinate_key}:{slot.slot_id}"
                    )

    @property
    def definitions(self) -> tuple[WorkDefinition, ...]:
        return self._definitions

    @property
    def groups(self) -> tuple[WorkGroupDefinition, ...]:
        return self._groups

    @property
    def milestones(self) -> tuple[WorkGraphMilestone, ...]:
        return self._milestones

    @property
    def graph_digest(self) -> ContentHash:
        return self.manifest(topology_id="topology:unpersisted").graph_digest

    @property
    def release_eligible(self) -> bool:
        return (
            self.mode == "production"
            and {item.kind for item in self._milestones} >= {"release_candidate", "released"}
            and _has_complete_production_topology(
                (item.coordinate for item in self._definitions),
                self.required_terminal_coordinates,
            )
        )

    def manifest(
        self,
        *,
        topology_id: Identifier,
        external_root_refs: tuple[ArtifactRef, ...] = (),
    ) -> WorkGraphManifest:
        scope_id = self._definitions[0].coordinate.scope_id
        bindings = tuple(
            WorkGraphNodeBinding(
                coordinate=item.coordinate,
                work_id=item.work_id,
                definition_digest=item.definition_digest,
            )
            for item in self._definitions
        )
        group_bindings = tuple(
            WorkGraphGroupBinding(
                group_id=item.group_id,
                group_digest=item.content_digest(),
                aggregate_coordinate=item.aggregate_coordinate,
                member_coordinates=item.member_coordinates,
            )
            for item in self._groups
        )
        milestone_bindings = tuple(
            WorkGraphMilestoneBinding(
                milestone_id=item.milestone_id,
                milestone_digest=item.content_digest(),
                kind=item.kind,
                required_coordinates=item.required_coordinates,
                establishes=item.establishes,
            )
            for item in self._milestones
        )
        identity = sha256_digest(
            canonical_json_bytes(
                {
                    "scope_id": scope_id,
                    "topology_id": topology_id,
                    "mode": self.mode,
                    "node_bindings": tuple(item.model_dump(mode="json") for item in bindings),
                    "group_bindings": tuple(
                        item.model_dump(mode="json") for item in group_bindings
                    ),
                    "milestone_bindings": tuple(
                        item.model_dump(mode="json") for item in milestone_bindings
                    ),
                    "required_terminal_coordinates": tuple(
                        item.model_dump(mode="json") for item in self.required_terminal_coordinates
                    ),
                    "external_root_refs": tuple(
                        item.model_dump(mode="json") for item in external_root_refs
                    ),
                }
            )
        ).removeprefix("sha256:")[:24]
        return WorkGraphManifest(
            graph_id=f"work-graph:{identity}",
            scope_id=scope_id,
            topology_id=topology_id,
            mode=self.mode,
            node_bindings=bindings,
            group_bindings=group_bindings,
            milestone_bindings=milestone_bindings,
            required_terminal_coordinates=self.required_terminal_coordinates,
            external_root_refs=external_root_refs,
            diagnostic_only=self.mode == "diagnostic",
            releasable=self.release_eligible,
        )

    def topological_definitions(self) -> tuple[WorkDefinition, ...]:
        """Return parents before consumers using deterministic coordinate order."""

        by_key = {item.coordinate.coordinate_key: item for item in self._definitions}
        indegree = {key: 0 for key in by_key}
        children: dict[str, list[str]] = {key: [] for key in by_key}
        for item in self._definitions:
            child_key = item.coordinate.coordinate_key
            for dependency in item.dependency_coordinates:
                indegree[child_key] += 1
                children[dependency.coordinate_key].append(child_key)
        ready = sorted(key for key, degree in indegree.items() if degree == 0)
        ordered: list[WorkDefinition] = []
        while ready:
            key = ready.pop(0)
            ordered.append(by_key[key])
            for child_key in sorted(children[key]):
                indegree[child_key] -= 1
                if indegree[child_key] == 0:
                    ready.append(child_key)
                    ready.sort()
        return tuple(ordered)

    def require(self, coordinate: WorkCoordinate) -> WorkDefinition:
        definition = next(
            (item for item in self._definitions if item.coordinate == coordinate),
            None,
        )
        if definition is None:
            raise WorkGraphError(f"unknown WorkCoordinate: {coordinate.coordinate_key}")
        return definition

    def descendants(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return all and only transitive consumers in deterministic topological order."""

        self.require(coordinate)
        reached: set[str] = set()
        queue = deque((coordinate.coordinate_key,))
        ordered: list[WorkCoordinate] = []
        while queue:
            parent_key = queue.popleft()
            children = sorted(
                (
                    item
                    for item in self._definitions
                    if any(
                        dependency.coordinate_key == parent_key
                        for dependency in item.dependency_coordinates
                    )
                ),
                key=lambda item: item.coordinate.coordinate_key,
            )
            for child in children:
                key = child.coordinate.coordinate_key
                if key in reached:
                    continue
                reached.add(key)
                ordered.append(child.coordinate)
                queue.append(key)
        return tuple(ordered)

    def ancestors(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return transitive producers in deterministic topological order."""

        self.require(coordinate)
        by_key = {item.coordinate.coordinate_key: item for item in self._definitions}
        ancestor_keys = self._ancestor_keys(coordinate, by_key)
        return tuple(
            item.coordinate
            for item in self.topological_definitions()
            if item.coordinate.coordinate_key in ancestor_keys
        )

    def automatic_repair_target(
        self,
        *,
        current: WorkCoordinate,
        proposed_target: WorkCoordinate,
    ) -> WorkDefinition:
        """Permit local or one declared causal repair edge only."""

        current_definition = self.require(current)
        target = self.require(proposed_target)
        if proposed_target == current:
            return target
        if proposed_target not in current_definition.repair_target_coordinates:
            raise WorkGraphError("automatic repair target is not a declared causal edge")
        if current_definition.repair_policy.maximum_automatic_backjump < 1:
            raise WorkGraphError("this WorkDefinition forbids automatic parent correction")
        return target


def tool_semantics_batch_definition(
    *,
    job_id: Identifier,
    group_id: Identifier,
    batch_id: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    agent_wall_seconds: float,
    agent_token_limit: int,
    agent_monetary_limit: float = 0.0,
    validation_wall_seconds: float = 10.0,
) -> WorkDefinition:
    """Compile framework policy for one real ToolSemanticsBatch shard."""

    coordinate = WorkCoordinate(
        scope_id=job_id,
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        group_id=group_id,
        shard_id=batch_id,
    )
    digest = _stable_work_identity_digest(coordinate)
    claim_id = "design.tool_semantics.compiles"
    return WorkDefinition(
        work_id=f"work:tool-semantics:{digest}",
        coordinate=coordinate,
        claim=(
            "The exact tool batch compiles against the frozen world schema, "
            "Rule IR context, and shared multi-tool constraints."
        ),
        timing_reason=(
            "World rules and task materialization may consume this batch only after "
            "its deterministic semantic frontier closes."
        ),
        dependency_coordinates=dependency_coordinates,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:tool-semantics:{digest}",
            executor="agent",
            operation="design.tool_semantics_batch",
            budget=OperationBudget(
                wall_seconds=agent_wall_seconds,
                first_progress_seconds=min(60.0, agent_wall_seconds),
                llm_tokens=agent_token_limit,
                agent_turns=1,
                monetary_cost=agent_monetary_limit,
            ),
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:tool-semantics-batch-source",
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:tool-semantics:{digest}",
            validator_id="validator:tool-semantics-batch",
            validator_revision_id="framework.validator.tool-semantics-batch.v1",
            validation_phase="tool_semantics",
            frontier_ordinal=20,
            claim_id=claim_id,
            effect="block_compile",
            budget=OperationBudget(wall_seconds=validation_wall_seconds),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:tool-semantics:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_automatic_backjump=0,
            maximum_total_repair_attempts=3,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=("/tools",),
        success_maturity="semantic_compiled",
    )


def structured_agent_work_definition(
    *,
    scope_id: Identifier,
    component: Literal["research", "design"] = "design",
    stage: Identifier,
    artifact_slot: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    output_contract_id: Identifier,
    acceptance_transform_id: Identifier | None = None,
    executor_revision_id: Identifier = "framework.executor.v1",
    implementation_revision_id: Identifier = "framework.impl.unversioned.v0",
    validator_revision_id: Identifier | None = None,
    agent_role: Literal["researcher", "environment_engineer"] = "environment_engineer",
    allowed_mutation_roots: tuple[str, ...],
    agent_wall_seconds: float,
    agent_token_limit: int,
    replay_mode: Literal[
        "deterministic", "idempotent_with_key", "queryable", "non_replayable"
    ] = "non_replayable",
    maximum_local_corrections: int = 1,
    strict_progress_bonus_corrections: int = 1,
    maximum_infrastructure_retries: int = 1,
    maximum_process_recoveries: int = 2,
    maximum_automatic_backjump: int = 0,
    maximum_total_repair_attempts: int = 3,
    group_id: Identifier | None = None,
    shard_id: Identifier | None = None,
    success_maturity: Identifier = "semantic_compiled",
    input_slots: tuple[ArtifactSlotContract, ...] = (),
    output_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    """Compile one explicit, bounded semantic Agent transaction policy."""

    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
        group_id=group_id,
        shard_id=shard_id,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependency_coordinates,
        input_slots=input_slots,
        output_slots=output_slots,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="agent",
            executor_revision_id=executor_revision_id,
            implementation_revision_id=implementation_revision_id,
            operation=f"design.{stage}",
            replay_mode=replay_mode,
            budget=OperationBudget(
                wall_seconds=agent_wall_seconds,
                first_progress_seconds=min(60.0, agent_wall_seconds),
                llm_tokens=agent_token_limit,
                agent_turns=1,
            ),
            agent_role=agent_role,
            capability_profile_id=f"profile:{agent_role.replace('_', '-')}",
            output_contract_id=output_contract_id,
            acceptance_transform_id=acceptance_transform_id,
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=(validator_revision_id or f"framework.validator.{stage}.v1"),
            validation_phase=stage,
            frontier_ordinal=10,
            claim_id=claim_id,
            effect="block_compile",
            budget=OperationBudget(wall_seconds=30.0),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=maximum_local_corrections,
            strict_progress_bonus_corrections=strict_progress_bonus_corrections,
            maximum_infrastructure_retries=maximum_infrastructure_retries,
            maximum_process_recoveries=maximum_process_recoveries,
            maximum_automatic_backjump=maximum_automatic_backjump,
            maximum_total_repair_attempts=maximum_total_repair_attempts,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def research_plan_work_definition(
    *,
    scope_id: Identifier,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the root ResearchPlan claim with no implicit Controller inputs."""

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim=(
            "The bounded research plan covers workflow, tools, state, authority, errors, and "
            "risks before any real search is spent."
        ),
        timing_reason="Real search must consume one validated bounded query plan.",
        output_contract_id="contract:research-plan",
        acceptance_transform_id="framework.direct-structured-output.v3",
        validator_revision_id="framework.validator.research-plan.v3",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        success_maturity="research_planned",
    )


def research_synthesis_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the one tool-free claim that turns admitted bodies into an EvidenceGraph."""

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="research",
        stage="evidence_synthesis",
        artifact_slot="evidence_synthesis",
        dependency_coordinates=(dependency_coordinate,),
        claim_id="research.evidence.grounded",
        claim=(
            "Observed claims bind real fetched passages while conflicts and unknowns remain "
            "explicit."
        ),
        timing_reason="World architecture may consume only one grounded EvidenceGraph.",
        output_contract_id="contract:evidence-synthesis",
        acceptance_transform_id="framework.direct-structured-output.v3",
        validator_revision_id="framework.validator.evidence-synthesis.v3",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:research-acquisition",
                direction="input",
                artifact_types=("design.research_acquisition",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-passage-pack",
                direction="input",
                artifact_types=("design.evidence_passage_pack",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:research-source-closure",
                direction="input",
                artifact_types=(
                    "evidence.raw_content",
                    "evidence.response_metadata",
                    "evidence.extracted_content",
                ),
                minimum_count=3,
                maximum_count=96,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:evidence-synthesis",
                direction="output",
                artifact_types=("design.evidence_synthesis",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:evidence-graph",
                direction="output",
                artifact_types=("design.evidence_graph",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        success_maturity="research_synthesized",
    )


def world_architecture_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the single Architecture transaction after grounded evidence.

    This is a semantic boundary, not a second verification loop.  The Agent
    describes domain meaning once; framework code immediately compiles the
    state/tool schema closure and deterministic coupling plan that downstream
    nodes must consume unchanged.
    """

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture",
        dependency_coordinates=(dependency_coordinate,),
        claim_id="design.architecture.closed",
        claim=(
            "One evidence-bound world boundary, state inventory, and public tool surface "
            "compile into a closed skeleton before behavior is authored."
        ),
        timing_reason=(
            "Rules, tool behavior, tasks, and runtime code must share one compiled world "
            "identity rather than independently infer an environment."
        ),
        output_contract_id="contract:world-architecture-source.v3",
        acceptance_transform_id="framework.architecture-compiler.v3",
        validator_revision_id="framework.validator.world-architecture.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/boundary", "/state_entities", "/tool_inventory"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-graph",
                direction="input",
                artifact_types=("design.evidence_graph",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-synthesis-lineage",
                direction="input",
                artifact_types=("design.evidence_synthesis",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:world-architecture-source",
                direction="output",
                artifact_types=("design.world_architecture_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-skeleton",
                direction="output",
                artifact_types=("design.world_skeleton",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:tool-coupling-plan",
                direction="output",
                artifact_types=("design.tool_coupling_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="architecture_compiled",
    )


def deterministic_boundary_work_definition(
    *,
    scope_id: Identifier,
    component: Literal["design", "integration", "release", "registry", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_compile", "block_integration", "block_release", "quarantine"],
    success_maturity: Identifier,
    wall_seconds: float = 30.0,
) -> WorkDefinition:
    """Compile a code-owned Claim boundary with no Agent repair authority."""

    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependency_coordinates,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="code",
            operation=f"{component}.{stage}",
            budget=OperationBudget(wall_seconds=wall_seconds),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=f"framework.validator.{stage}.v1",
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=effect,
            budget=OperationBudget(wall_seconds=wall_seconds),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_automatic_backjump=0,
            maximum_total_repair_attempts=0,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=(),
        success_maturity=success_maturity,
    )


def research_acquisition_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    wall_seconds: float,
    maximum_search_calls: int,
    maximum_tool_calls: int,
) -> WorkDefinition:
    """Compile the real search/fetch/extract boundary between plan and synthesis.

    Search is neither an implicit side effect of EvidenceSynthesis nor an LLM
    action.  It has its own real-tools proposal, deterministic evidence
    admission and infrastructure-only recovery policy.
    """

    if maximum_search_calls < 1 or maximum_tool_calls < maximum_search_calls + 2:
        raise ValueError(
            "research acquisition requires bounded search, fetch, and extract capacity"
        )
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="research",
        stage="evidence_acquisition",
        artifact_slot="research_acquisition",
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:evidence-acquisition:{digest}",
        coordinate=coordinate,
        claim=(
            "The frozen ResearchPlan produced bounded real source bodies whose provenance "
            "can be admitted as evidence."
        ),
        timing_reason=(
            "Evidence synthesis must not infer claims from search snippets or unfetched URLs."
        ),
        dependency_coordinates=(dependency_coordinate,),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:research-plan",
                direction="input",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-acquisition",
                direction="output",
                artifact_types=("design.research_acquisition",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:evidence-passage-pack",
                direction="output",
                artifact_types=("design.evidence_passage_pack",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:research-source-closure",
                direction="output",
                artifact_types=(
                    "evidence.raw_content",
                    "evidence.response_metadata",
                    "evidence.extracted_content",
                ),
                minimum_count=3,
                maximum_count=96,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:evidence-acquisition:{digest}",
            executor="real_tools",
            operation="research.search_fetch_extract",
            # Search/fetch/extract are read-only, source-addressed queries.
            # An interrupted operation is still charged as unknown, but one
            # policy-authorized fresh query may be attempted on recovery.
            replay_mode="queryable",
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                first_progress_seconds=min(30.0, wall_seconds),
                search_calls=maximum_search_calls,
                tool_calls=maximum_tool_calls,
            ),
            capability_profile_id="profile:researcher-tools",
            tool_ids=("research.search", "research.fetch", "research.extract"),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:evidence-acquisition:{digest}",
            validator_id="validator:evidence-acquisition",
            validator_revision_id="framework.validator.evidence-acquisition.v1",
            validation_phase="evidence_acquisition",
            frontier_ordinal=20,
            claim_id="research.evidence.acquired",
            effect="block_compile",
            budget=OperationBudget(wall_seconds=min(60.0, wall_seconds)),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:evidence-acquisition:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=1,
            maximum_process_recoveries=1,
            maximum_total_repair_attempts=1,
        ),
        required_claim_id="research.evidence.acquired",
        success_maturity="research_acquired",
    )


def compile_design_work_graph(
    *,
    scope_id: Identifier,
    design_definitions: Iterable[WorkDefinition],
    modeling_definition: WorkDefinition,
    verifier_plan_definition: WorkDefinition,
    groups: Iterable[WorkGroupDefinition] = (),
    strict_input_contracts: bool = False,
) -> GenerationWorkGraph:
    """Freeze the non-releasable semantic prefix through VerifierPlan.

    Tool behavior is derived from Architecture and task cardinality only becomes
    known after Modeling.  The deterministic VerifierPlan is therefore the
    exact terminal of the intermediate graph; it commits the one fact needed
    to derive final Challenger physical work without hiding Agent calls.
    """

    upstream = tuple(design_definitions)
    if modeling_definition.coordinate.scope_id != scope_id:
        raise WorkGraphError("ModelingBoundary scope differs from generation scope")
    if modeling_definition.coordinate.stage != "modeling_boundary":
        raise WorkGraphError("design graph requires ModelingBoundary")
    if verifier_plan_definition.coordinate.scope_id != scope_id:
        raise WorkGraphError("VerifierPlan scope differs from generation scope")
    if (
        verifier_plan_definition.coordinate.component != "verifier"
        or verifier_plan_definition.coordinate.stage != "verifier_plan"
        or verifier_plan_definition.dependency_coordinates != (modeling_definition.coordinate,)
    ):
        raise WorkGraphError("design graph requires VerifierPlan directly after ModelingBoundary")
    if any(item.coordinate.scope_id != scope_id for item in upstream):
        raise WorkGraphError("Design definitions cannot mix generation scopes")
    upstream_by_key = {item.coordinate.coordinate_key: item for item in upstream}
    if modeling_definition.coordinate.coordinate_key in upstream_by_key:
        raise WorkGraphError("ModelingBoundary must be appended exactly once")
    if verifier_plan_definition.coordinate.coordinate_key in upstream_by_key:
        raise WorkGraphError("VerifierPlan must be appended exactly once")
    for dependency in modeling_definition.dependency_coordinates:
        if dependency.coordinate_key not in upstream_by_key:
            raise WorkGraphError("ModelingBoundary depends on an unregistered Design coordinate")
    upstream_stage_pairs = {(item.coordinate.component, item.coordinate.stage) for item in upstream}
    required_upstream = {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
        ("design", "world_rules"),
        ("design", "task_curriculum"),
    }
    if not required_upstream <= upstream_stage_pairs or not any(
        item.coordinate.component == "design" and item.coordinate.stage in _BEHAVIOR_STAGES
        for item in upstream
    ):
        raise WorkGraphError(
            "design graph requires Research and full semantic Design closure "
            "before ModelingBoundary"
        )
    return GenerationWorkGraph.compile(
        (*upstream, modeling_definition, verifier_plan_definition),
        mode="diagnostic",
        strict_input_contracts=strict_input_contracts,
        required_terminal_coordinates=(verifier_plan_definition.coordinate,),
        groups=groups,
    )


def complete_generation_work_graph(
    *,
    scope_id: Identifier,
    design_graph: GenerationWorkGraph,
    builder_wall_seconds: float = 1_200.0,
    builder_token_limit: int = 64_000,
    verifier_wall_seconds: float = 900.0,
    verifier_token_limit: int = 48_000,
    verifier_batch_count: int,
    integration_wall_seconds: float = 600.0,
    release_wall_seconds: float = 900.0,
    strict_input_contracts: bool = False,
) -> GenerationWorkGraph:
    """Compile the one releasable Direct/Evolve topology.

    The function accepts the exact intermediate ``design_graph`` rather than a
    loose list of definitions.  Its committed VerifierPlan determines the
    supplied physical Challenger count; :class:`WorkGraphEpochRuntime` checks
    that count against the exact persisted plan before freezing the final epoch.
    Callers cannot create a production graph whose terminal is merely
    ``ModelingBoundary`` or whose Agent fan-out is unknown.
    """

    if design_graph.mode != "diagnostic" or design_graph.release_eligible:
        raise WorkGraphError("final graph requires the diagnostic Design predecessor graph")
    upstream = design_graph.definitions
    if not upstream or upstream[0].coordinate.scope_id != scope_id:
        raise WorkGraphError("Design predecessor graph scope differs from generation scope")
    modeling = tuple(
        item
        for item in upstream
        if (item.coordinate.component, item.coordinate.stage) == ("design", "modeling_boundary")
    )
    verifier_plans = tuple(
        item
        for item in upstream
        if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_plan")
    )
    if len(modeling) != 1 or len(verifier_plans) != 1:
        raise WorkGraphError("final graph requires one retained ModelingBoundary and VerifierPlan")
    modeling_definition = modeling[0]
    verifier_plan = verifier_plans[0]
    if design_graph.required_terminal_coordinates != (verifier_plan.coordinate,):
        raise WorkGraphError("Design predecessor must terminate exactly at VerifierPlan")

    if not 1 <= verifier_batch_count <= 8:
        raise WorkGraphError("Verifier batch count must be within the fixed 1..8 capacity")

    build = _agent_component_definition(
        scope_id=scope_id,
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependencies=(modeling_definition.coordinate,),
        claim_id="build.candidate.valid",
        claim="Exact frozen Design bytes are implemented as a closed executable Candidate.",
        timing_reason="Integration can execute only a committed Candidate source closure.",
        role="environment_engineer",
        operation="build.environment_candidate",
        output_contract_id="contract:environment-candidate.v3",
        validation_effect="block_integration",
        success_maturity="candidate_built",
        wall_seconds=builder_wall_seconds,
        token_limit=builder_token_limit,
        allowed_mutation_roots=("/source", "/dependencies", "/runtime", "/materializer"),
        output_types=(
            "build.implementation_contract",
            "build.source_workspace_snapshot",
            "build.implementation_lineage",
            "build.candidate_manifest",
            "build.record",
            "build.environment_candidate",
        ),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
    )
    verifier_batches, verifier_group, verifier = _verifier_intent_group(
        scope_id=scope_id,
        verifier_plan_coordinate=verifier_plan.coordinate,
        batch_count=verifier_batch_count,
        wall_seconds=verifier_wall_seconds,
        token_limit=verifier_token_limit,
    )
    integration = _assured_code_definition(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependencies=(build.coordinate,),
        repair_targets=(build.coordinate,),
        claim_id="integration.runtime.executable",
        claim="Candidate installs, starts, materializes tasks, resets and steps in isolation.",
        timing_reason="Release assurance may consume only fresh Candidate execution evidence.",
        effect="block_release",
        success_maturity="integration_passed",
        wall_seconds=integration_wall_seconds,
        probe_ids=(
            "clean-install",
            "runtime-handshake",
            "task-materialization",
            "reset-step",
            "restart-teardown",
        ),
        output_types=("judge.integration_report",),
        allowed_mutation_roots=("/source", "/dependencies", "/runtime", "/materializer"),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    release_assurance = _assured_code_definition(
        scope_id=scope_id,
        component="judge",
        stage="release_assurance",
        artifact_slot="judge_report",
        # Release probes may expose a causal Candidate defect that integration's
        # public smoke did not reach.  Build is consequently a direct readiness
        # and one-hop repair edge, not an implicit two-hop ancestor hidden behind
        # Integration.  Exact Integration evidence is still consumed to avoid
        # rerunning its matching checks under another name.
        dependencies=(build.coordinate, integration.coordinate, verifier.coordinate),
        repair_targets=(build.coordinate,),
        claim_id="release.assurance.passed",
        claim="Exact Candidate and Verifier bytes satisfy every required hard release claim.",
        timing_reason="Packaging is forbidden until independent additive release probes pass.",
        effect="block_release",
        success_maturity="release_assured",
        wall_seconds=release_wall_seconds,
        probe_ids=(
            "task-reachability",
            "rule-properties",
            "sealed-cases",
            "fresh-deployment",
        ),
        output_types=("judge_report",),
        allowed_mutation_roots=("/verifier", "/source", "/runtime"),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:release-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:integration-report",
                direction="input",
                artifact_types=("judge.integration_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="integration",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-ir",
                direction="input",
                artifact_types=("judge.verifier_ir_projection",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
        ),
    )
    observability = _code_component_definition(
        scope_id=scope_id,
        component="release",
        stage="observability_closure",
        artifact_slot="telemetry_release_summary",
        dependencies=(release_assurance.coordinate,),
        claim_id="release.observability.closed",
        claim="The run exposes complete typed time, usage, tool, process and repair accounting.",
        timing_reason="An unauditable Candidate cannot enter an experimental release package.",
        effect="block_release",
        success_maturity="observability_closed",
        # This is the immutable pre-package trace cut consumed by the Dossier,
        # envpkg metadata and Registry.  A post-publish trace is operational
        # telemetry only: it cannot be a dependency of the package it observes.
        output_types=("release.telemetry_summary",),
        # Declaring the common root explicitly means this observer receives no
        # Judge artifact bytes from its causal predecessor; it reads only the
        # telemetry store under its own framework capability.
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
        ),
    )
    package = _code_component_definition(
        scope_id=scope_id,
        component="release",
        stage="package",
        artifact_slot="environment_package",
        # Package assembly is an explicit closure consumer.  It receives the
        # exact active Design, Candidate, Verifier and independent reports
        # rather than reaching into unrelated Work heads behind the Scheduler.
        dependencies=(
            modeling_definition.coordinate,
            build.coordinate,
            verifier.coordinate,
            integration.coordinate,
            release_assurance.coordinate,
            observability.coordinate,
        ),
        claim_id="release.package.closed",
        claim="The exact assured Candidate is assembled as a canonical movable envpkg v3 closure.",
        timing_reason="Registry may inspect only immutable package bytes and their manifest.",
        effect="block_release",
        success_maturity="release_candidate_ready",
        output_types=("environment_package_manifest",),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:world-spec",
                direction="input",
                artifact_types=("design.world_spec",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:environment-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:candidate-manifest",
                direction="input",
                artifact_types=("build.candidate_manifest",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:build-record",
                direction="input",
                artifact_types=("build.record",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-lineage",
                direction="input",
                artifact_types=("build.implementation_lineage",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-ir",
                direction="input",
                artifact_types=("judge.verifier_ir_projection",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
            ArtifactSlotContract(
                slot_id="input:integration-report",
                direction="input",
                artifact_types=("judge.integration_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="integration",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:judge-report",
                direction="input",
                artifact_types=("judge_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="judge",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:telemetry-summary",
                direction="input",
                artifact_types=("release.telemetry_summary",),
                minimum_count=1,
                maximum_count=1,
                producer_component="release",
                confidentiality="framework_private",
            ),
        ),
    )
    registry = _code_component_definition(
        scope_id=scope_id,
        component="registry",
        stage="publication",
        artifact_slot="registry_publication",
        dependencies=(package.coordinate,),
        claim_id="registry.publication.committed",
        claim="Registry atomically published and reread the exact envpkg bytes.",
        timing_reason="Only atomic Registry truth establishes a released EnvironmentPackage.",
        effect="block_release",
        success_maturity="released",
        output_types=("release.record",),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:package-manifest",
                direction="input",
                artifact_types=("environment_package_manifest",),
                minimum_count=1,
                maximum_count=1,
                producer_component="release",
            ),
        ),
    )
    milestones = (
        WorkGraphMilestone(
            milestone_id="milestone:release-candidate",
            kind="release_candidate",
            required_coordinates=(package.coordinate,),
            establishes="release_candidate_ready",
        ),
        WorkGraphMilestone(
            milestone_id="milestone:released",
            kind="released",
            required_coordinates=(registry.coordinate,),
            establishes="released",
        ),
    )
    return GenerationWorkGraph.compile(
        (
            *upstream,
            build,
            *verifier_batches,
            verifier,
            integration,
            release_assurance,
            observability,
            package,
            registry,
        ),
        mode="production",
        strict_input_contracts=strict_input_contracts,
        required_terminal_coordinates=(registry.coordinate,),
        groups=(*design_graph.groups, verifier_group),
        milestones=milestones,
    )


def derive_final_design_definitions(
    *,
    scope_id: Identifier,
    bootstrap_definitions: tuple[WorkDefinition, ...],
    architecture_source_ref: ArtifactRef,
    coupling_plan: ToolCouplingPlan,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkDefinition]:
    """Freeze the only final Design suffix from a committed coupling plan.

    Architecture is the one deliberate topology-discovery boundary: it fixes
    the actual tool batches and any cross-batch shared-semantics transactions.
    This compiler turns that immutable plan into physical WorkDefinitions. It
    never invokes an Agent, reads a workspace, or reaches into the legacy
    Designer. Direct Generation and Evolve both call this exact compiler after
    adapting their respective frozen ``GenerationContext``.

    The `ToolCouplingPlan` import is type-only: the control layer never calls
    Designer code. Its closed `groups` expose `group_id`, `mode` and
    `ordered_tool_ids`; `execution_batches` contains every tool exactly once
    in frozen order.
    """

    if agent_wall_seconds <= 0 or agent_token_limit <= 0:
        raise WorkGraphError("final Design Agent budgets must be positive")
    if not bootstrap_definitions:
        raise WorkGraphError("final Design derivation requires retained bootstrap definitions")
    if any(item.coordinate.scope_id != scope_id for item in bootstrap_definitions):
        raise WorkGraphError("bootstrap definitions mix a different generation scope")

    architecture = tuple(
        item
        for item in bootstrap_definitions
        if (item.coordinate.component, item.coordinate.stage)
        == ("design", "world_architecture")
    )
    if len(architecture) != 1:
        raise WorkGraphError("final Design derivation requires exactly one Architecture definition")
    architecture_coordinate = architecture[0].coordinate
    if architecture_source_ref.artifact_type != "design.world_architecture_source":
        raise WorkGraphError("final Design derivation requires a WorldArchitecture source Artifact")
    if coupling_plan.architecture_ref != architecture_source_ref:
        raise WorkGraphError(
            "ToolCouplingPlan is not bound to the committed WorldArchitecture source"
        )
    synthesis = tuple(
        item
        for item in bootstrap_definitions
        if (item.coordinate.component, item.coordinate.stage)
        == ("research", "evidence_synthesis")
    )
    if len(synthesis) != 1:
        raise WorkGraphError(
            "final Design derivation requires exactly one EvidenceSynthesis definition"
        )
    synthesis_coordinate = synthesis[0].coordinate

    groups = coupling_plan.groups
    execution_batches = coupling_plan.execution_batches
    if not groups or not execution_batches:
        raise WorkGraphError("ToolCouplingPlan must contain groups and execution batches")

    declared_tool_ids = tuple(
        tool_id for group in groups for tool_id in group.ordered_tool_ids
    )
    scheduled_tool_ids = tuple(tool_id for batch in execution_batches for tool_id in batch)
    if (
        not declared_tool_ids
        or len(set(declared_tool_ids)) != len(declared_tool_ids)
        or tuple(sorted(scheduled_tool_ids)) != tuple(sorted(declared_tool_ids))
        or len(scheduled_tool_ids) != len(declared_tool_ids)
    ):
        raise WorkGraphError("ToolCouplingPlan does not freeze an exact tool-batch partition")
    if any(not batch or len(batch) > 4 for batch in execution_batches):
        raise WorkGraphError("ToolCouplingPlan contains an invalid physical batch")

    context_slot = ArtifactSlotContract(
        slot_id="input:generation-context",
        direction="input",
        artifact_types=("control.generation_context",),
        minimum_count=1,
        maximum_count=1,
        producer_component="external",
        confidentiality="framework_private",
    )
    architecture_input_slots = (
        context_slot,
        ArtifactSlotContract(
            slot_id="input:world-architecture-source",
            direction="input",
            artifact_types=("design.world_architecture_source",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:world-skeleton",
            direction="input",
            artifact_types=("design.world_skeleton",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:tool-coupling-plan",
            direction="input",
            artifact_types=("design.tool_coupling_plan",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:evidence-graph",
            direction="input",
            artifact_types=("design.evidence_graph",),
            minimum_count=1,
            maximum_count=1,
            producer_component="research",
        ),
    )

    shared_definitions: list[WorkDefinition] = []
    shared_coordinates: dict[str, WorkCoordinate] = {}
    for group in groups:
        group_id = group.group_id
        if group.mode != "multi_batch":
            continue
        coordinate = WorkCoordinate(
            scope_id=scope_id,
            component="design",
            stage="shared_tool_semantics",
            artifact_slot="shared_tool_semantics",
            group_id=group_id,
        )
        shared_coordinates[group_id] = coordinate
        shared_definitions.append(
            structured_agent_work_definition(
                scope_id=scope_id,
                component="design",
                stage="shared_tool_semantics",
                artifact_slot="shared_tool_semantics",
                group_id=group_id,
                dependency_coordinates=(architecture_coordinate, synthesis_coordinate),
                claim_id="design.shared_behavior.closed",
                claim=(
                    "Cross-batch atomicity, ordering, compensation, idempotency and error "
                    "policy are fixed before their physical tool batches execute."
                ),
                timing_reason=(
                    "A coupled group may not author incompatible local retry or rollback "
                    "behavior in separate Agent calls."
                ),
                output_contract_id="contract:shared-tool-semantics-source.v3",
                acceptance_transform_id="framework.shared-tool-semantics-compiler.v3",
                validator_revision_id="framework.validator.shared-tool-semantics.v3",
                agent_role="environment_engineer",
                allowed_mutation_roots=(
                    "/atomicity_domains",
                    "/concurrency_domains",
                    "/idempotency_domains",
                    "/ordering_constraints",
                    "/compensation_edges",
                    "/error_policies",
                ),
                agent_wall_seconds=agent_wall_seconds,
                agent_token_limit=agent_token_limit,
                input_slots=architecture_input_slots,
                output_slots=(
                    ArtifactSlotContract(
                        slot_id="output:shared-tool-semantics-source",
                        direction="output",
                        artifact_types=("design.shared_tool_semantics_source",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="design",
                    ),
                    ArtifactSlotContract(
                        slot_id="output:shared-tool-semantics-contract",
                        direction="output",
                        artifact_types=("design.shared_tool_semantics_contract",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="design",
                    ),
                ),
                success_maturity="shared_behavior_compiled",
            )
        )

    multi_batch_members = {
        tool_id: group.group_id
        for group in groups
        if group.mode == "multi_batch"
        for tool_id in group.ordered_tool_ids
    }
    behavior_definitions: list[WorkDefinition] = []
    for batch_index, tool_ids in enumerate(execution_batches, start=1):
        shared_dependencies = tuple(
            dict.fromkeys(
                shared_coordinates[multi_batch_members[tool_id]]
                for tool_id in tool_ids
                if tool_id in multi_batch_members
            )
        )
        batch_input_slots = architecture_input_slots + (
            (
                ArtifactSlotContract(
                    slot_id="input:shared-tool-semantics-contract",
                    direction="input",
                    artifact_types=("design.shared_tool_semantics_contract",),
                    minimum_count=len(shared_dependencies),
                    maximum_count=len(shared_dependencies),
                    producer_component="design",
                ),
            )
            if shared_dependencies
            else ()
        )
        base = tool_semantics_batch_definition(
            job_id=scope_id,
            group_id="tool-semantics-batches",
            batch_id=f"tool-batch-{batch_index}",
            dependency_coordinates=(
                architecture_coordinate,
                synthesis_coordinate,
                *shared_dependencies,
            ),
            agent_wall_seconds=agent_wall_seconds,
            agent_token_limit=agent_token_limit,
        )
        behavior_definitions.append(
            base.model_copy(
                update={
                    "input_slots": batch_input_slots,
                    "output_slots": (
                        ArtifactSlotContract(
                            slot_id="output:tool-semantics-batch-source",
                            direction="output",
                            artifact_types=("design.tool_semantics_batch_source",),
                            minimum_count=1,
                            maximum_count=1,
                            producer_component="design",
                        ),
                        ArtifactSlotContract(
                            slot_id="output:tool-semantics",
                            direction="output",
                            artifact_types=("design.tool_semantics",),
                            minimum_count=len(tool_ids),
                            maximum_count=len(tool_ids),
                            producer_component="design",
                        ),
                    ),
                }
            )
        )

    behavior_coordinates = tuple(item.coordinate for item in behavior_definitions)
    world_rules = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
        dependency_coordinates=(
            architecture_coordinate,
            synthesis_coordinate,
            *behavior_coordinates,
        ),
        claim_id="design.world_rules.compiles",
        claim="Reset rules and cross-tool invariants compile over the exact committed behavior.",
        timing_reason="Task generation needs an executable, invariant-closed world.",
        output_contract_id="contract:world-rules-source.v3",
        acceptance_transform_id="framework.world-rules-compiler.v3",
        validator_revision_id="framework.validator.world-rules.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/initial_state_rules", "/invariants"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            *architecture_input_slots,
            ArtifactSlotContract(
                slot_id="input:tool-semantics",
                direction="input",
                artifact_types=("design.tool_semantics",),
                minimum_count=len(declared_tool_ids),
                maximum_count=len(declared_tool_ids),
                producer_component="design",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:world-rules-source",
                direction="output",
                artifact_types=("design.world_rules_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-semantic-source",
                direction="output",
                artifact_types=("design.world_semantic_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-model",
                direction="output",
                artifact_types=("design.world_model",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="world_rules_compiled",
    )
    curriculum = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="task_curriculum",
        artifact_slot="task_curriculum",
        dependency_coordinates=(
            synthesis_coordinate,
            architecture_coordinate,
            world_rules.coordinate,
        ),
        claim_id="design.curriculum.compiles",
        claim="Bounded task requirements compile against the exact executable world.",
        timing_reason="Builder and Verifier require one frozen curriculum and task protocol.",
        output_contract_id="contract:task-curriculum-source.v3",
        acceptance_transform_id="framework.training-semantics-compiler.v3",
        validator_revision_id="framework.validator.task-curriculum.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/curriculum_plan", "/task_requirements"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            *architecture_input_slots,
            ArtifactSlotContract(
                slot_id="input:world-semantic-source",
                direction="input",
                artifact_types=("design.world_semantic_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:world-model",
                direction="input",
                artifact_types=("design.world_model",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:task-curriculum-source",
                direction="output",
                artifact_types=("design.task_curriculum_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="curriculum_compiled",
    )
    modeling = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
        dependency_coordinates=(
            synthesis_coordinate,
            architecture_coordinate,
            world_rules.coordinate,
            curriculum.coordinate,
        ),
        claim_id="design.modeling.closed",
        claim="The exact world and curriculum compile into a complete EnvironmentDesign closure.",
        timing_reason="Build cannot consume partial semantic sources or unbound task policy.",
        effect="block_integration",
        success_maturity="design_compiled",
        wall_seconds=60.0,
    ).model_copy(
        update={
            "input_slots": (
                *architecture_input_slots,
                ArtifactSlotContract(
                    slot_id="input:world-semantic-source",
                    direction="input",
                    artifact_types=("design.world_semantic_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:world-model",
                    direction="input",
                    artifact_types=("design.world_model",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:task-curriculum-source",
                    direction="input",
                    artifact_types=("design.task_curriculum_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:coverage-map",
                    direction="output",
                    artifact_types=("design.coverage_map",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:world-spec",
                    direction="output",
                    artifact_types=("design.world_spec",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:environment-design",
                    direction="output",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:modeling-gate",
                    direction="output",
                    artifact_types=("control.modeling_gate",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:design-baseline",
                    direction="output",
                    artifact_types=("design.baseline_checkpoint",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )
    return (
        (
            *bootstrap_definitions,
            *shared_definitions,
            *behavior_definitions,
            world_rules,
            curriculum,
        ),
        modeling,
    )


def _verifier_intent_group(
    *,
    scope_id: Identifier,
    verifier_plan_coordinate: WorkCoordinate,
    batch_count: int,
    wall_seconds: float,
    token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkGroupDefinition, WorkDefinition]:
    """Freeze each real Challenger turn before code aggregates the final IR.

    Verifier task batches are not an implementation detail of one nominal Agent
    node: each has its own retry budget, invocation accounting and WorkCommit.
    The aggregate coordinate remains ``verifier_intent`` so the release dossier
    binds one complete, framework-merged Verifier IR rather than a partial shard.
    """

    group_id = "verifier-intent-batches"
    per_batch_wall = wall_seconds / batch_count
    per_batch_tokens = token_limit // batch_count
    if per_batch_wall <= 0 or per_batch_tokens < 1:
        raise WorkGraphError("Verifier batch budget cannot be split into real Agent turns")
    batches: list[WorkDefinition] = []
    for index in range(batch_count):
        coordinate = WorkCoordinate(
            scope_id=scope_id,
            component="verifier",
            stage="verifier_intent_batch",
            artifact_slot="verifier_intent_checkpoint",
            group_id=group_id,
            shard_id=f"batch-{index + 1}",
        )
        digest = _stable_work_identity_digest(coordinate)
        batches.append(
            WorkDefinition(
                work_id=f"work:verifier-intent-batch:{digest}",
                coordinate=coordinate,
                claim=(
                    "One bounded Challenger batch compiles adversarial verifier intent for its "
                    "exact frozen task partition."
                ),
                timing_reason=(
                    "The final Verifier IR may include only individually validated task-batch "
                    "intent commitments."
                ),
                dependency_coordinates=(verifier_plan_coordinate,),
                input_slots=(
                    ArtifactSlotContract(
                        slot_id="input:verifier-batch-plan",
                        direction="input",
                        artifact_types=("judge.verifier_batch_plan",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                        confidentiality="framework_private",
                    ),
                ),
                output_slots=(
                    ArtifactSlotContract(
                        slot_id="output:verifier-intent-checkpoint",
                        direction="output",
                        artifact_types=("judge.verifier_intent_checkpoint",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                    ),
                    ArtifactSlotContract(
                        slot_id="output:verifier-batch-draft",
                        direction="output",
                        artifact_types=("judge.verifier_batch_draft",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                        confidentiality="sealed",
                    ),
                ),
                proposal_policy=ProposalPolicy(
                    policy_id=f"proposal:verifier-intent-batch:{digest}",
                    executor="agent",
                    operation="verifier.compile_intent_batch",
                    budget=OperationBudget(
                        wall_seconds=per_batch_wall,
                        first_progress_seconds=min(120.0, per_batch_wall),
                        llm_tokens=per_batch_tokens,
                        agent_turns=1,
                    ),
                    agent_role="challenger",
                    capability_profile_id="profile:challenger",
                    output_contract_id="contract:verifier-intent-batch.v3",
                ),
                validation_policy=ValidationPolicy(
                    policy_id=f"validation:verifier-intent-batch:{digest}",
                    validator_id="validator:verifier-intent-batch",
                    validator_revision_id="framework.validator.verifier-intent-batch.v3",
                    validation_phase="verifier_intent_batch",
                    frontier_ordinal=100,
                    claim_id="verifier.intent.batch.valid",
                    effect="block_release",
                    budget=OperationBudget(wall_seconds=min(120.0, per_batch_wall)),
                ),
                repair_policy=RepairPolicy(
                    policy_id=f"repair:verifier-intent-batch:{digest}",
                    policy_revision_id="framework.repair-authority.v2",
                    maximum_local_corrections=1,
                    strict_progress_bonus_corrections=1,
                    maximum_infrastructure_retries=1,
                    maximum_process_recoveries=1,
                    maximum_total_repair_attempts=3,
                ),
                required_claim_id="verifier.intent.batch.valid",
                allowed_mutation_roots=("/cases", "/properties", "/coverage"),
                success_maturity="verifier_batch_compiled",
            )
        )
    aggregate_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_bundle",
        group_id=group_id,
    )
    aggregate = _code_component_definition(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_bundle",
        dependencies=tuple(item.coordinate for item in batches),
        claim_id="verifier.intent.valid",
        claim=(
            "Exact validated Verifier batches aggregate to one framework-owned public "
            "and sealed IR."
        ),
        timing_reason=(
            "Release assurance requires a complete independently compiled verifier closure."
        ),
        effect="block_release",
        success_maturity="verifier_compiled",
        output_types=("judge.verifier_ir_projection",),
    ).model_copy(
        update={
            "coordinate": aggregate_coordinate,
            "work_id": (
                f"work:verifier-intent:{_stable_work_identity_digest(aggregate_coordinate)}"
            ),
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:verifier-batch-draft",
                    direction="input",
                    artifact_types=("judge.verifier_batch_draft",),
                    minimum_count=batch_count,
                    maximum_count=batch_count,
                    producer_component="verifier",
                    confidentiality="sealed",
                ),
            ),
        }
    )
    group = WorkGroupDefinition(
        group_id=group_id,
        scope_id=scope_id,
        member_coordinates=tuple(item.coordinate for item in batches),
        aggregate_coordinate=aggregate_coordinate,
    )
    return tuple(batches), group, aggregate


def verifier_plan_work_definition(
    *,
    scope_id: Identifier,
    modeling_coordinate: WorkCoordinate,
) -> WorkDefinition:
    """Materialize the exact deterministic task partition before any Challenger turn.

    The final graph has to know how many physical batches exist, but the per-batch
    task/rule/property scope must also survive process recovery.  This small code
    boundary writes that framework-private plan from the frozen EnvironmentDesign;
    batch Agents may read it but cannot redefine it.
    """

    return _code_component_definition(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_plan",
        artifact_slot="verifier_batch_plan",
        dependencies=(modeling_coordinate,),
        claim_id="verifier.plan.frozen",
        claim=(
            "The exact task, Rule, property and case-quota partition is frozen before any "
            "Challenger invocation."
        ),
        timing_reason=(
            "Physical Challenger batches need immutable semantic scope for provenance, "
            "local repair and restart."
        ),
        effect="block_release",
        success_maturity="verifier_plan_frozen",
        output_types=("judge.verifier_batch_plan",),
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:environment-design",
                    direction="input",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:world-spec",
                    direction="input",
                    artifact_types=("design.world_spec",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:verifier-batch-plan",
                    direction="output",
                    artifact_types=("judge.verifier_batch_plan",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="verifier",
                    confidentiality="framework_private",
                ),
            )
        }
    )


def _agent_component_definition(
    *,
    scope_id: Identifier,
    component: Literal["build", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    role: Literal["environment_engineer", "challenger"],
    operation: Identifier,
    output_contract_id: Identifier,
    validation_effect: Literal["block_integration", "block_release"],
    success_maturity: Identifier,
    wall_seconds: float,
    token_limit: int,
    allowed_mutation_roots: tuple[str, ...],
    output_types: tuple[Identifier, ...],
    input_slots: tuple[ArtifactSlotContract, ...] = (),
    assurance: AssurancePolicy | None = None,
) -> WorkDefinition:
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependencies,
        input_slots=input_slots,
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component=component,
            )
            for artifact_type in output_types
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="agent",
            operation=operation,
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                first_progress_seconds=min(120.0, wall_seconds),
                first_write_seconds=(min(300.0, wall_seconds) if component == "build" else None),
                llm_tokens=token_limit,
                agent_turns=1,
            ),
            agent_role=role,
            capability_profile_id=f"profile:{role.replace('_', '-')}",
            output_contract_id=output_contract_id,
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=f"framework.validator.{stage}.v1",
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=validation_effect,
            budget=OperationBudget(wall_seconds=min(120.0, wall_seconds), process_calls=2),
        ),
        assurance_policy=assurance,
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_process_recoveries=1,
            maximum_total_repair_attempts=3,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def _assured_code_definition(
    *,
    scope_id: Identifier,
    component: Literal["integration", "judge"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    repair_targets: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_release"],
    success_maturity: Identifier,
    wall_seconds: float,
    probe_ids: tuple[Identifier, ...],
    output_types: tuple[Identifier, ...],
    allowed_mutation_roots: tuple[str, ...],
    input_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependencies,
        repair_target_coordinates=repair_targets,
        input_slots=input_slots,
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component=component,
            )
            for artifact_type in output_types
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="code",
            # The code proposal is the single real isolated execution (clean
            # build/runtime/Judge), not a cheap preflight that later repeats
            # the same probe under a second control operation.  Validation
            # only maps that immutable report to the declared Claim.
            operation=f"{component}.{stage}.execute",
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                tool_calls=max(16, len(probe_ids) * 8),
                process_calls=max(1, len(probe_ids) * 2),
                build_seconds=wall_seconds,
                evaluation_episodes=max(64, len(probe_ids) * 16),
                container_seconds=wall_seconds,
            ),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=f"framework.validator.{stage}.v1",
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=effect,
            budget=OperationBudget(wall_seconds=min(60.0, wall_seconds), process_calls=1),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            # These are diagnostic code leaves.  They cannot edit Candidate or
            # Verifier bytes; semantic failure is routed by Scheduler to the
            # declared causal target.  Only transport/infrastructure recovery
            # may re-run this exact physical probe locally.
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=1,
            maximum_process_recoveries=1,
            maximum_automatic_backjump=1,
            maximum_total_repair_attempts=2,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def _code_component_definition(
    *,
    scope_id: Identifier,
    component: Literal["release", "registry", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_release"],
    success_maturity: Identifier,
    output_types: tuple[Identifier, ...],
    input_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    definition = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
        dependency_coordinates=dependencies,
        claim_id=claim_id,
        claim=claim,
        timing_reason=timing_reason,
        effect=effect,
        success_maturity=success_maturity,
        wall_seconds=120.0,
    )
    return definition.model_copy(
        update={
            "input_slots": input_slots,
            "output_slots": tuple(
                ArtifactSlotContract(
                    slot_id=f"output:{artifact_type}",
                    direction="output",
                    artifact_types=(artifact_type,),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component=component,
                )
                for artifact_type in output_types
            )
        }
    )


__all__ = [
    "GenerationWorkGraph",
    "JoinPolicy",
    "ResolvedWorkInputs",
    "WorkGraphGroupBinding",
    "WorkGraphManifest",
    "WorkGraphMilestone",
    "WorkGraphMilestoneBinding",
    "WorkGraphNodeBinding",
    "WorkGraphError",
    "WorkGraphEpoch",
    "WorkGroupDefinition",
    "compile_design_work_graph",
    "complete_generation_work_graph",
    "derive_final_design_definitions",
    "deterministic_boundary_work_definition",
    "research_acquisition_work_definition",
    "research_plan_work_definition",
    "research_synthesis_work_definition",
    "structured_agent_work_definition",
    "tool_semantics_batch_definition",
    "verifier_plan_work_definition",
    "world_architecture_work_definition",
]
