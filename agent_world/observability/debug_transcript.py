"""Explicitly opt-in, local-only debug transcript storage.

This module is intentionally separate from ArtifactStore, TelemetryStore, and
the WorkAttempt state machine. It is an operator tool: writes are bounded,
screened before persistence, and failure remains observational only.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .paths import ObservabilityError, ObservabilityRoot
from .subprocess_scene import safe_dynamic_text

MAX_DEBUG_TRANSCRIPT_BYTES = 256 * 1024
_DEBUG_TRANSCRIPTS_FLAG = "AGENT_WORLD_DEBUG_TRANSCRIPTS"

type DebugTranscriptStatus = Literal["disabled", "rejected", "unavailable", "written"]


@dataclass(frozen=True, slots=True)
class DebugTranscriptWrite:
    """One non-authoritative local-write outcome with no transcript echo."""

    status: DebugTranscriptStatus
    path: Path | None = None


class DebugTranscriptWriter:
    """Write safe local transcripts only when the explicit process flag is set."""

    def __init__(
        self,
        *,
        root: ObservabilityRoot,
        known_secret_canaries: Sequence[str | bytes] = (),
        enabled: bool | None = None,
    ) -> None:
        self._root = root
        self._known_secret_canaries = tuple(known_secret_canaries)
        self._enabled = (
            os.environ.get(_DEBUG_TRANSCRIPTS_FLAG) == "1" if enabled is None else enabled
        )

    @property
    def enabled(self) -> bool:
        """Whether this writer can create an on-disk transcript."""

        return self._enabled

    def write(self, *, scope_id: str, transcript: str) -> DebugTranscriptWrite:
        """Best-effort write after screening every dynamic Tier A value.

        A canary or generic credential match in transcript text rejects the
        entire write. A sensitive scope identifier is represented by the same
        deterministic hash that normal Tier A projection uses.
        """

        if not self._enabled:
            return DebugTranscriptWrite(status="disabled")
        if not isinstance(scope_id, str) or not isinstance(transcript, str):
            return DebugTranscriptWrite(status="rejected")

        safe_scope_id = safe_dynamic_text(
            scope_id,
            known_secret_canaries=self._known_secret_canaries,
        )
        safe_transcript = safe_dynamic_text(
            transcript,
            known_secret_canaries=self._known_secret_canaries,
        )
        if safe_transcript != transcript:
            return DebugTranscriptWrite(status="rejected")
        payload = transcript.encode("utf-8", errors="replace")
        if len(payload) > MAX_DEBUG_TRANSCRIPT_BYTES:
            return DebugTranscriptWrite(status="rejected")

        filename = f"{hashlib.sha256(payload).hexdigest()}.txt"
        try:
            path = self._root.write_debug_transcript(safe_scope_id, filename, payload)
        except (ObservabilityError, OSError):
            return DebugTranscriptWrite(status="unavailable")
        return DebugTranscriptWrite(status="written", path=path)


__all__ = [
    "DebugTranscriptStatus",
    "DebugTranscriptWrite",
    "DebugTranscriptWriter",
    "MAX_DEBUG_TRANSCRIPT_BYTES",
]
