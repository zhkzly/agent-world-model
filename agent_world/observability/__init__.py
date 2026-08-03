"""Agent-facing observability support.

Phase 2 adds a bounded, rebuildable Tier A scene projection while retaining
Phase 1's secret-safe Runtime subprocess facts as Tier B evidence.
"""

from .debug_transcript import (
    MAX_DEBUG_TRANSCRIPT_BYTES,
    DebugTranscriptStatus,
    DebugTranscriptWrite,
    DebugTranscriptWriter,
)
from .paths import ObservabilityError, ObservabilityRoot
from .projector import SceneProjector
from .query import ObservabilityReader, SceneRead
from .scene import (
    ActiveWorkPointer,
    BudgetAdmissionDimension,
    BudgetExhaustion,
    CandidateWorkspaceLiveness,
    CodexTerminalEnvelope,
    CoordinatePointer,
    CoordinateScene,
    FrontierDiff,
    FrontierRecord,
    ObservabilityIndex,
    RunSceneIndex,
    RuntimeAgentActivityCounts,
    RuntimeAgentLiveness,
    RuntimeAgentRequestShape,
    Scene,
    SceneHead,
    SceneIssue,
    SceneTierBEvent,
    SceneWatermark,
    TopIssue,
    active_work_digest,
    fold,
)
from .subprocess_scene import (
    MAX_STDERR_TAIL_BYTES,
    RuntimeSubprocessScene,
    runtime_subprocess_scene,
    runtime_subprocess_scene_from_payload,
    safe_dynamic_text,
)

__all__ = [
    "ActiveWorkPointer",
    "BudgetAdmissionDimension",
    "BudgetExhaustion",
    "CandidateWorkspaceLiveness",
    "CodexTerminalEnvelope",
    "CoordinatePointer",
    "CoordinateScene",
    "DebugTranscriptStatus",
    "DebugTranscriptWrite",
    "DebugTranscriptWriter",
    "FrontierDiff",
    "FrontierRecord",
    "MAX_DEBUG_TRANSCRIPT_BYTES",
    "MAX_STDERR_TAIL_BYTES",
    "ObservabilityError",
    "ObservabilityIndex",
    "ObservabilityReader",
    "ObservabilityRoot",
    "RunSceneIndex",
    "RuntimeAgentActivityCounts",
    "RuntimeAgentLiveness",
    "RuntimeAgentRequestShape",
    "RuntimeSubprocessScene",
    "Scene",
    "SceneHead",
    "SceneIssue",
    "SceneProjector",
    "SceneRead",
    "SceneTierBEvent",
    "SceneWatermark",
    "TopIssue",
    "active_work_digest",
    "fold",
    "runtime_subprocess_scene",
    "runtime_subprocess_scene_from_payload",
    "safe_dynamic_text",
]
