"""Environment Builder: frozen design to real, untrusted candidate project."""

from .leaf import BuilderLeaf, BuildPlanningLeaf
from .models import (
    BuilderWorkspaceProgress,
    BuildRecord,
    CandidateCompletion,
    CandidateFileDeclaration,
    CandidatePublicSelfCheckDeclaration,
    CandidateRuntimeDeclaration,
    CandidateTaskMaterializerDeclaration,
    ImplementationContract,
    ImplementationPlan,
    ImplementationPlanDraft,
    RepairDisclosure,
    normalize_candidate_completion_output,
)
from .precommit import (
    CandidatePrecommitInfrastructureError,
    CandidateWorkspaceProbe,
    HostCandidateWorkspaceProbe,
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
    "BuildPlanningLeaf",
    "BuildRecord",
    "BuilderWorkspaceProgress",
    "BuilderError",
    "BuilderLeaf",
    "BuilderSessionState",
    "CandidateCompletion",
    "CandidateWorkspaceProbe",
    "CandidateFileDeclaration",
    "CandidatePublicSelfCheckDeclaration",
    "CandidateRuntimeDeclaration",
    "CandidateTaskMaterializerDeclaration",
    "CandidateWorkspaceError",
    "CandidateWorkspaceValidator",
    "CandidatePrecommitInfrastructureError",
    "EnvironmentBuilder",
    "ImplementationContract",
    "ImplementationPlan",
    "ImplementationPlanDraft",
    "HostCandidateWorkspaceProbe",
    "RepairDisclosure",
    "ValidatedCandidateFile",
    "ValidatedCandidateWorkspace",
    "normalize_candidate_completion_output",
]
