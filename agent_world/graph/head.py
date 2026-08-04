"""Single content-addressed run head with file-locked CAS.

The old control plane kept two independently designed mutable heads for the same
conceptual role: ``WorkControlHead`` (keyed by WorkCoordinate) and
``DirectJobHead`` (keyed by request_id).  They are collapsed here into one head
keyed by ``scope_id`` that stores the latest ``RunState`` snapshot.  Because
``RunState`` evolves append-only, a resume is just "read the head, re-run any
non-terminal slice"; there is no separate resume-recovery reader and therefore
no orphan-head/topology-index class of bugs.
"""

from __future__ import annotations

import os
from pathlib import Path

from .state import RunState


class RunHeadStore:
    """Durable per-scope head backed by one JSON file plus an flock CAS guard."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, scope_id: str) -> Path:
        safe = scope_id.replace("/", "_")
        return self._root / f"{safe}.head.json"

    def read(self, scope_id: str) -> RunState | None:
        path = self._path(scope_id)
        if not path.exists():
            return None
        return RunState.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, state: RunState) -> RunState:
        """Atomically replace the head via write-to-temp + rename under flock."""

        path = self._path(state.scope_id)
        lock = path.with_suffix(".lock")
        with self._exclusive(lock):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(state.stable_json(), encoding="utf-8")
            os.replace(tmp, path)
        return state

    def scopes(self) -> tuple[str, ...]:
        return tuple(
            sorted(p.name[: -len(".head.json")] for p in self._root.glob("*.head.json"))
        )

    @staticmethod
    def _exclusive(lock_path: Path) -> "_FlockGuard":
        return _FlockGuard(lock_path)


class _FlockGuard:
    """A tiny context manager wrapping fcntl.flock for cross-process CAS."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fd: int | None = None

    def __enter__(self) -> None:
        import fcntl

        self._fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def __exit__(self, *exc: object) -> None:
        import fcntl

        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


__all__ = ["RunHeadStore"]
