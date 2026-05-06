from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from src.config import get_config
from src.data.deontic_verbs import DEONTIC_VERBS
from src.models.schemas import KISSDocument, KISSToken
from src.parsing.gc_entities import EntityMatch, GCEntityMatcher

logger = logging.getLogger(__name__)

ENTITY_POS = {"NOUN", "PROPN", "NUM", "PRON"}
VERB_POS = {"VERB", "AUX"}
CONNECTOR_POS = {"ADP", "CONJ", "CCONJ", "SCONJ", "PART", "DET", "ADV", "ADJ"}
PUNCT_POS = {"PUNCT", "SPACE"}
TOKEN_PATTERN = re.compile(r"\w+(?:[-']\w+)*|[^\w\s]", re.UNICODE)
STOPWORDS = {
    "a",
    "an",
    "and",
    "based",
    "do",
    "has",
    "have",
    "i",
    "in",
    "need",
    "of",
    "on",
    "or",
    "related",
    "the",
    "they",
    "to",
    "what",
    "who",
}
COMMON_VERBS = {"approve", "filed", "hire", "work", "works"}


class KISSParser:
    def __init__(self, entity_matcher: GCEntityMatcher | None = None) -> None:
        self._config = get_config()
        self._entity_matcher = entity_matcher or GCEntityMatcher()
        self._nlp = self._load_spacy()
        self.model_version = self._resolve_model_version()

    def parse_document(
        self,
        text: str,
        source_url: str,
        instrument_title: str,
        agent_id: str,
    ) -> KISSDocument:
        matches = self._entity_matcher.find_matches(text)
        raw_tokens = self._spacy_tokens(text)
        sentence_spans = self._sentence_spans(text)
        tokens = self._merge_entity_matches(text, raw_tokens, matches, sentence_spans)
        return KISSDocument(
            source_url=source_url,
            instrument_title=instrument_title,
            agent_id=agent_id,
            tokens=tokens,
            sentence_count=len(sentence_spans),
            token_count=len(tokens),
            parsed_at=datetime.utcnow().isoformat(),
            model_version=self.model_version,
        )

    def classify_token(self, text: str, lemma: str, pos: str) -> tuple[str, bool, str | None]:
        phrase = text.lower()
        lemma_phrase = lemma.lower()
        deontic_type = DEONTIC_VERBS.get(phrase) or DEONTIC_VERBS.get(lemma_phrase)
        if deontic_type is not None:
            return ("VERB", True, deontic_type)
        if self._entity_matcher.get_entity_type(text) is not None:
            return ("ENTITY", False, None)
        if pos in ENTITY_POS:
            return ("ENTITY", False, None)
        if pos in VERB_POS:
            return ("VERB", False, None)
        if pos in PUNCT_POS:
            return ("PUNCTUATION", False, None)
        if pos in CONNECTOR_POS:
            return ("CONNECTOR", False, None)
        return ("CONNECTOR", False, None)

    def _load_spacy(self) -> Any | None:
        try:
            import spacy

            return spacy.load(self._config.parsing.spacy_model)
        except (ImportError, OSError) as e:
            logger.warning("spaCy model unavailable; using heuristic KISS parsing: %s", e)
            return None

    def _resolve_model_version(self) -> str:
        if self._nlp is None:
            return "heuristic"
        meta = getattr(self._nlp, "meta", {})
        name = meta.get("name", self._config.parsing.spacy_model)
        version = meta.get("version", self._config.parsing.spacy_model_version)
        return f"{name}-{version}"

    def _spacy_tokens(self, text: str) -> list[dict[str, Any]]:
        if self._nlp is None:
            return self._heuristic_tokens(text)
        doc = self._nlp(text)
        return [
            {
                "text": token.text,
                "lemma": token.lemma_ or token.text.lower(),
                "pos": token.pos_ or self._guess_pos(token.text),
                "start": token.idx,
                "end": token.idx + len(token.text),
            }
            for token in doc
        ]

    def _heuristic_tokens(self, text: str) -> list[dict[str, Any]]:
        return [
            {
                "text": match.group(0),
                "lemma": match.group(0).lower(),
                "pos": self._guess_pos(match.group(0)),
                "start": match.start(),
                "end": match.end(),
            }
            for match in TOKEN_PATTERN.finditer(text)
        ]

    def _guess_pos(self, token: str) -> str:
        lowered = token.lower()
        if re.fullmatch(r"\W", token):
            return "PUNCT"
        if lowered in DEONTIC_VERBS:
            return "AUX"
        if lowered in STOPWORDS:
            return "DET"
        if lowered in COMMON_VERBS or lowered.endswith(("ed", "ing")):
            return "VERB"
        if token[:1].isupper() or token.isdigit():
            return "PROPN"
        return "X"

    def _sentence_spans(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start = 0
        for match in re.finditer(r"[.!?]\s+", text):
            end = match.end()
            spans.append((start, end))
            start = end
        if start < len(text):
            spans.append((start, len(text)))
        return spans or [(0, 0)]

    def _merge_entity_matches(
        self,
        text: str,
        raw_tokens: list[dict[str, Any]],
        matches: list[EntityMatch],
        sentence_spans: list[tuple[int, int]],
    ) -> list[KISSToken]:
        tokens: list[KISSToken] = []
        token_idx = 0
        match_by_start = {match.char_start: match for match in matches}
        covered = {
            pos
            for match in matches
            for pos in range(match.char_start, match.char_end)
        }

        for raw in raw_tokens:
            start = raw["start"]
            if start in match_by_start:
                match = match_by_start[start]
                sentence_idx = self._sentence_idx(match.char_start, sentence_spans)
                tokens.append(
                    KISSToken(
                        text=text[match.char_start:match.char_end],
                        lemma=match.canonical_text.lower(),
                        pos="ENTITY_OVERRIDE",
                        kiss_category="ENTITY",
                        is_deontic=False,
                        deontic_type=None,
                        char_start=match.char_start,
                        char_end=match.char_end,
                        sentence_idx=sentence_idx,
                        token_idx=token_idx,
                    )
                )
                token_idx += 1
                continue
            if start in covered:
                continue
            category, is_deontic, deontic_type = self.classify_token(
                raw["text"], raw["lemma"], raw["pos"]
            )
            tokens.append(
                KISSToken(
                    text=raw["text"],
                    lemma=raw["lemma"],
                    pos=raw["pos"],
                    kiss_category=category,
                    is_deontic=is_deontic,
                    deontic_type=deontic_type,
                    char_start=raw["start"],
                    char_end=raw["end"],
                    sentence_idx=self._sentence_idx(raw["start"], sentence_spans),
                    token_idx=token_idx,
                )
            )
            token_idx += 1
        return tokens

    def _sentence_idx(self, char_start: int, sentence_spans: list[tuple[int, int]]) -> int:
        for idx, (start, end) in enumerate(sentence_spans):
            if start <= char_start < end:
                return idx
        return max(len(sentence_spans) - 1, 0)
