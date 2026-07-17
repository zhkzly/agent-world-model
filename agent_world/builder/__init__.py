"""Environment Builder: frozen design to real, untrusted candidate project."""

from .models import (
    BuilderWorkspaceProgress,
    BuildRecord,
    CandidateCompletion,
    CandidateFileDeclaration,
    CandidatePublicSelfCheckDeclaration,
    CandidateRuntimeDeclaration,
    CandidateTaskMaterializerDeclaration,
    ImplementationContract,
    RepairDisclosure,
    normalize_candidate_completion_output,
)
from .service import (
    AgentProfileProvider,
    BuildBundle,
    BuilderError,
    BuilderSessionState,
    BuildInvocationSummary,
    EnvironmentBuilder,
)
from .workspace import (
    CandidateWorkspaceError,
    CandidateWorkspaceValidator,
    ValidatedCandidateFile,
    ValidatedCandidateWorkspace,
)

__all__ = [
    "AgentProfileProvider",
    "BuildBundle",
    "BuildInvocationSummary",
    "BuildRecord",
    "BuilderWorkspaceProgress",
    "BuilderError",
    "BuilderSessionState",
    "CandidateCompletion",
    "CandidateFileDeclaration",
    "CandidatePublicSelfCheckDeclaration",
    "CandidateRuntimeDeclaration",
    "CandidateTaskMaterializerDeclaration",
    "CandidateWorkspaceError",
    "CandidateWorkspaceValidator",
    "EnvironmentBuilder",
    "ImplementationContract",
    "RepairDisclosure",
    "ValidatedCandidateFile",
    "ValidatedCandidateWorkspace",
    "normalize_candidate_completion_output",
]
