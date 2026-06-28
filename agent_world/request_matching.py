from __future__ import annotations

import re


def match_request_tokens(raw_request: str, lowered: str, tokens: set[str]) -> list[str]:
    return sorted(token for token in tokens if request_token_matches(raw_request, lowered, token))


def request_token_matches(raw_request: str, lowered: str, token: str) -> bool:
    if token.isascii() and re.search(r"[a-z0-9_]", token):
        return re.search(rf"(?<![a-z0-9_]){re.escape(token.lower())}(?![a-z0-9_])", lowered) is not None
    return token in raw_request
