from __future__ import annotations

import json
from pathlib import Path

from awmx.artifacts.schemas import RewardRecord


def write_reward_record(reward: RewardRecord, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reward.to_dict(), ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return path
