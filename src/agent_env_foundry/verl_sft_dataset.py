"""The one reviewed CP1 reader exception over the pinned veRL SFT dataset.

Parquet struct inference null-unions heterogeneous tool JSON (varying tool
argument keys, varying tool parameter schemas), silently corrupting both the
rendered tool schemas and the trainable argument spans. Foundry SFT rows
therefore carry ``messages`` and ``tools`` as deterministic compact JSON
strings; this subclass only decodes those two columns back to the pristine
in-memory projection before the inherited upstream pipeline runs. Template
application, tokenization and the assistant-only loss mask stay entirely
upstream.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agent_env_foundry.learning_data import _sft_json_text

if TYPE_CHECKING:
    # Type-only local base contract: the root environment type-checks this
    # module without veRL installed; the real upstream base is used at runtime.
    class _MultiTurnSFTDatasetBase:
        dataframe: Any
        messages_key: str
        tools_key: str
        messages: Any
        tools: Any

        def _read_files_and_process(self) -> None: ...

else:
    from verl.utils.dataset.multiturn_sft_dataset import (
        MultiTurnSFTDataset as _MultiTurnSFTDatasetBase,
    )


class FoundryJSONColumnsSFTDataset(_MultiTurnSFTDatasetBase):
    """Upstream ``MultiTurnSFTDataset`` over strict compact-JSON string columns."""

    def _read_files_and_process(self) -> None:
        super()._read_files_and_process()
        for column in (self.messages_key, self.tools_key):
            if column not in self.dataframe.columns:
                raise ValueError(
                    f"FoundryJSONColumnsSFTDataset requires a {column!r} string column"
                )
            decoded: list[Any] = []
            for cell in self.dataframe[column]:
                if not isinstance(cell, str):
                    raise ValueError(
                        f"SFT JSON column {column!r} must contain string cells, got"
                        f" {type(cell).__name__}: native Parquet struct cells are not"
                        " accepted"
                    )
                value = json.loads(cell)
                if not isinstance(value, list):
                    raise ValueError(f"decoded {column!r} cell must be a JSON array")
                if _sft_json_text(value) != cell:
                    raise ValueError(
                        f"decoded {column!r} cell must re-encode to its exact compact JSON text"
                    )
                decoded.append(value)
            self.dataframe[column] = decoded
        self.messages = self.dataframe[self.messages_key].tolist()
        self.tools = self.dataframe[self.tools_key].tolist()
