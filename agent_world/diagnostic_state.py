"""Narrow authorization checks for isolated test-node state copies.

The normal ``.agent-world-live`` tree may hold private runtime state and is
never a valid observability input. A test-node copy is different: it is
created below that tree only after volatile agent workspaces are excluded and
its control root receives this exact public marker. Keeping the marker check
in a dependency-free module lets both control and observability enforce the
same boundary without an import cycle.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

TEST_NODE_DIAGNOSTIC_MARKER = ".test-node-diagnostic"
TEST_NODE_DIAGNOSTIC_MARKER_CONTENT = b"diagnostic_only=true\nreleasable=false\n"


def is_marked_test_node_diagnostic_state_root(state_root: str | os.PathLike[str]) -> bool:
    """Return whether ``state_root`` is one exact, marker-authorized clone.

    This function intentionally returns ``False`` for every malformed or
    inaccessible path. It never creates a directory and rejects links at the
    state root, its live parent, its control root, and its marker.
    """

    requested = Path(state_root).expanduser()
    if (
        ".agent-world-live" not in requested.parts
        or requested.parent.name != ".agent-world-live"
        or not requested.name.startswith("test-node-")
    ):
        return False
    if not _is_real_directory(requested.parent):
        return False
    return has_test_node_diagnostic_marker(requested / "work-control")


def has_test_node_diagnostic_marker(control_root: str | os.PathLike[str]) -> bool:
    """Return whether a real ``work-control`` root bears the exact marker.

    The control store uses this form directly, while observability first adds
    the stricter ``.agent-world-live/test-node-*`` state-root location check.
    """

    control = Path(control_root).expanduser()
    if not _is_real_directory(control):
        return False
    marker = control / TEST_NODE_DIAGNOSTIC_MARKER
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(marker, flags)
    except OSError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return False
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            content = stream.read(len(TEST_NODE_DIAGNOSTIC_MARKER_CONTENT) + 1)
    except OSError:
        return False
    return content == TEST_NODE_DIAGNOSTIC_MARKER_CONTENT


def _is_real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


__all__ = [
    "TEST_NODE_DIAGNOSTIC_MARKER",
    "TEST_NODE_DIAGNOSTIC_MARKER_CONTENT",
    "has_test_node_diagnostic_marker",
    "is_marked_test_node_diagnostic_state_root",
]
