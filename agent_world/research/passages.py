"""Deterministic bounded passage selection over immutable research bodies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

from agent_world.contracts import Evidence, EvidencePassage, EvidencePassagePack

from .models import ResearchBundle

PASSAGE_CHAR_LIMIT = 1_200
PASSAGE_STRIDE = 1_000
PASSAGES_PER_SOURCE = 2
PASSAGE_PACK_CHAR_LIMIT = 64_000
MAX_QUERY_TERMS = 128

_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{2,}|[\u3400-\u9fff]{2,}")
_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "and",
        "are",
        "can",
        "complete",
        "environment",
        "for",
        "from",
        "into",
        "must",
        "only",
        "public",
        "should",
        "that",
        "the",
        "their",
        "this",
        "tool",
        "tools",
        "using",
        "when",
        "with",
    }
)


def build_evidence_passage_pack(
    *,
    pack_id: str,
    need: str,
    query_texts: Sequence[str],
    evidence: tuple[Evidence, ...],
    bundle: ResearchBundle,
) -> EvidencePassagePack:
    """Select at least one bounded, hash-bound passage from every source."""

    if len(evidence) != len(bundle.documents) or not evidence:
        raise ValueError("passage selection requires aligned non-empty evidence and documents")
    terms = _query_terms((need, *query_texts))
    query_fingerprint = _content_hash(
        json.dumps(
            {"need": need, "queries": list(query_texts)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    ranked_by_source: list[list[EvidencePassage]] = []
    for item, document in zip(evidence, bundle.documents, strict=True):
        text = document.text
        if item.content_hash != _content_hash(text):
            raise ValueError(f"passage source hash mismatch for {item.evidence_id}")
        candidates: list[tuple[int, int, int, tuple[str, ...]]] = []
        for window_start, window_end in _window_ranges(text):
            start, end = _trimmed_range(text, window_start, window_end)
            if start == end:
                continue
            passage_text = text[start:end]
            matched = tuple(term for term in terms if term in passage_text.casefold())
            score = sum(
                min(3, passage_text.casefold().count(term)) * max(1, len(term) - 2)
                for term in matched
            )
            candidates.append((score, start, end, matched[:16]))
        candidates.sort(key=lambda value: (-value[0], value[1]))
        selected: list[EvidencePassage] = []
        for _score, start, end, matched in candidates:
            if any(
                start < existing.end_char and end > existing.start_char
                for existing in selected
            ):
                continue
            passage_text = text[start:end]
            passage_hash = _content_hash(passage_text)
            passage_suffix = hashlib.sha256(
                f"{item.evidence_id}\0{start}\0{end}\0{passage_hash}".encode()
            ).hexdigest()[:24]
            selected.append(
                EvidencePassage(
                    passage_id=f"passage:{passage_suffix}",
                    evidence_id=item.evidence_id,
                    source_uri=item.source_uri,
                    source_content_hash=item.content_hash,
                    start_char=start,
                    end_char=end,
                    passage_hash=passage_hash,
                    text=passage_text,
                    matched_terms=matched,
                )
            )
            if len(selected) >= PASSAGES_PER_SOURCE:
                break
        if not selected:
            raise ValueError(f"extracted evidence body is empty: {item.evidence_id}")
        ranked_by_source.append(selected)

    passages: list[EvidencePassage] = []
    total_chars = 0
    for rank in range(PASSAGES_PER_SOURCE):
        for selected in ranked_by_source:
            if rank >= len(selected):
                continue
            passage = selected[rank]
            if rank > 0 and total_chars + len(passage.text) > PASSAGE_PACK_CHAR_LIMIT:
                continue
            passages.append(passage)
            total_chars += len(passage.text)
    if total_chars > PASSAGE_PACK_CHAR_LIMIT:
        raise ValueError("minimum passage coverage exceeds the fixed pack character limit")
    return EvidencePassagePack(
        pack_id=pack_id,
        query_fingerprint=query_fingerprint,
        source_count=len(evidence),
        passages=tuple(passages),
    )


def _window_ranges(text: str) -> tuple[tuple[int, int], ...]:
    if not text:
        return ()
    ranges: list[tuple[int, int]] = []
    for start in range(0, len(text), PASSAGE_STRIDE):
        end = min(len(text), start + PASSAGE_CHAR_LIMIT)
        ranges.append((start, end))
        if end == len(text):
            break
    return tuple(ranges)


def _trimmed_range(text: str, start: int, end: int) -> tuple[int, int]:
    """Return an exact non-whitespace source range for a candidate window.

    Contract strings are whitespace-normalized at their validation boundary.
    Moving the offsets before hashing keeps the stored excerpt byte-auditable
    against the original extracted body instead of letting model validation
    silently change text after its range and digest were calculated.
    """

    candidate = text[start:end]
    trimmed = candidate.strip()
    if not trimmed:
        return start, start
    leading = len(candidate) - len(candidate.lstrip())
    trailing = len(candidate) - len(candidate.rstrip())
    return start + leading, end - trailing


def _query_terms(values: Sequence[str]) -> tuple[str, ...]:
    terms: set[str] = set()
    for value in values:
        for raw in _TOKEN.findall(value.casefold()):
            if raw in _STOP_WORDS:
                continue
            terms.add(raw)
            if any("\u3400" <= character <= "\u9fff" for character in raw):
                terms.update(raw[index : index + 2] for index in range(len(raw) - 1))
    return tuple(sorted(terms, key=lambda item: (-len(item), item))[:MAX_QUERY_TERMS])


def _content_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "PASSAGE_CHAR_LIMIT",
    "PASSAGE_PACK_CHAR_LIMIT",
    "PASSAGES_PER_SOURCE",
    "build_evidence_passage_pack",
]
