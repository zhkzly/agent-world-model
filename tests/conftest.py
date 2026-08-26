"""Shared pytest configuration for S1 Slice 1 contract tests.

Puts ``tests/fixtures`` on ``sys.path`` so mechanical release descriptors can
reference fixture factories through the standard ``module:factory`` import spec,
exactly like a real installed generated package would be referenced.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
if str(FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURES_DIR))
