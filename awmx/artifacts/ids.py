from __future__ import annotations

import re
from pathlib import PurePath

from awmx.artifacts.schemas import ValidationError


_STORAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def validate_storage_id(value: str, field_name: str = "id") -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field_name} must be a non-empty storage id")
    if value in {".", ".."} or ".." in value:
        raise ValidationError(f"{field_name} must not contain path traversal")
    if "/" in value or "\\" in value:
        raise ValidationError(f"{field_name} must not contain path separators")
    if PurePath(value).is_absolute() or not _STORAGE_ID_RE.fullmatch(value):
        raise ValidationError(f"{field_name} contains unsupported characters")
    return value
