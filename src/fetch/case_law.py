from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_INDEX_PATH = _PROJECT_ROOT / "data" / "case_law" / "fpslreb_cases.json"
_MIN_QUERY_TERM_LENGTH = 3
_MAX_SUMMARY_CHARS = 900

_QUERY_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "can",
    "could",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "our",
    "should",
    "that",
    "the",
    "their",
    "then",
    "there",
    "this",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
}


@dataclass(frozen=True)
class CaseLawEntry:
    case_id: str
    title: str
    citation: str
    decision_date: str
    decision_type: str
    subject_terms: tuple[str, ...]
    keywords: tuple[str, ...]
    summary: str
    disposition: str
    url: str
    agent_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseLawEntry:
        return cls(
            case_id=str(data.get("case_id", "")),
            title=str(data.get("title", "")),
            citation=str(data.get("citation", "")),
            decision_date=str(data.get("decision_date", "")),
            decision_type=str(data.get("decision_type", "")),
            subject_terms=tuple(str(value) for value in data.get("subject_terms", [])),
            keywords=tuple(str(value) for value in data.get("keywords", [])),
            summary=str(data.get("summary", "")),
            disposition=str(data.get("disposition", "")),
            url=str(data.get("url", "")),
            agent_ids=tuple(str(value) for value in data.get("agent_ids", [])),
        )


class CaseLawIndex:
    """Static compact case-law index for query-time retrieval."""

    def __init__(self, index_path: Path = _DEFAULT_INDEX_PATH) -> None:
        self._index_path = index_path
        self._entries: list[CaseLawEntry] | None = None

    def search(self, query_text: str, agent_id: str, limit: int = 5) -> list[CaseLawEntry]:
        terms = _query_terms(query_text)
        if not terms:
            return []

        scored: list[tuple[int, str, CaseLawEntry]] = []
        for entry in self._load_entries():
            if agent_id not in entry.agent_ids:
                continue
            haystack = _entry_text(entry)
            score = sum(haystack.count(term) for term in terms)
            if score <= 0:
                continue
            scored.append((score, entry.decision_date, entry))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [entry for _score, _date, entry in scored[:limit]]

    def _load_entries(self) -> list[CaseLawEntry]:
        if self._entries is not None:
            return self._entries
        if not self._index_path.exists():
            self._entries = []
            return self._entries
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Case-law index unavailable at %s: %s", self._index_path, exc)
            self._entries = []
            return self._entries
        self._entries = [
            CaseLawEntry.from_dict(item)
            for item in raw.get("cases", [])
            if isinstance(item, dict)
        ]
        return self._entries


def format_case_law_context(cases: list[CaseLawEntry]) -> str:
    if not cases:
        return ""
    parts = [
        "RETRIEVED CASE-LAW CONTEXT:\n",
        "Use these FPSLREB decisions only as case-specific interpretive examples. "
        "Primary authority remains the legislation, collective agreement, policy, directive, or DAOD.\n",
    ]
    for index, case in enumerate(cases, start=1):
        summary = case.summary[:_MAX_SUMMARY_CHARS].strip()
        subjects = ", ".join(case.subject_terms)
        keywords = ", ".join(case.keywords)
        parts.append(
            f"\n{index}. {case.title} ({case.citation})\n"
            f"Date: {case.decision_date}\n"
            f"Type: {case.decision_type}\n"
            f"Subjects: {subjects}\n"
            f"Keywords: {keywords}\n"
            f"Summary: {summary}\n"
            f"Disposition: {case.disposition}\n"
            f"URL: {case.url}\n"
        )
    return "".join(parts)


def _entry_text(entry: CaseLawEntry) -> str:
    return " ".join(
        [
            entry.title,
            entry.citation,
            entry.decision_type,
            " ".join(entry.subject_terms),
            " ".join(entry.keywords),
            entry.summary,
            entry.disposition,
        ]
    ).lower()


def _query_terms(query_text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]+", query_text.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip("'")
        if len(token) < _MIN_QUERY_TERM_LENGTH or token in _QUERY_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


_case_law_index: CaseLawIndex | None = None


def get_case_law_index() -> CaseLawIndex:
    global _case_law_index
    if _case_law_index is None:
        _case_law_index = CaseLawIndex()
    return _case_law_index
