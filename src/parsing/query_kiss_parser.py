from __future__ import annotations

from src.config import get_config
from src.models.schemas import QueryKISSResult
from src.parsing.kiss_parser import KISSParser


class QueryKISSParser:
    def __init__(self, kiss_parser: KISSParser | None = None) -> None:
        self._config = get_config()
        self._kiss_parser = kiss_parser or KISSParser()

    def parse(self, query_text: str) -> QueryKISSResult | None:
        doc = self._kiss_parser.parse_document(
            text=query_text,
            source_url="query",
            instrument_title="User query",
            agent_id="query",
        )
        entities: list[str] = []
        entity_types: dict[str, str] = {}
        verbs: list[str] = []
        deontic_verbs: list[str] = []

        for token in doc.tokens:
            if token.kiss_category == "ENTITY":
                canonical = token.text.strip()
                if canonical not in entities:
                    entities.append(canonical)
                    entity_types[canonical] = self._infer_entity_type(canonical, token.pos)
            elif token.kiss_category == "VERB":
                lemma = token.lemma.lower()
                if lemma not in verbs:
                    verbs.append(lemma)
                if token.is_deontic and lemma not in deontic_verbs:
                    deontic_verbs.append(lemma)

        fallback_triggered = len(entities) < self._config.parsing.query_entity_threshold
        if fallback_triggered:
            return None
        return QueryKISSResult(
            raw_query=query_text,
            entities=entities,
            entity_types=entity_types,
            verbs=verbs,
            deontic_verbs=deontic_verbs,
            sentence_count=doc.sentence_count,
            entity_count=len(entities),
            fallback_triggered=False,
            model_version=doc.model_version,
        )

    def parse_with_fallback_result(self, query_text: str) -> QueryKISSResult:
        result = self.parse(query_text)
        if result is not None:
            return result
        doc = self._kiss_parser.parse_document(
            text=query_text,
            source_url="query",
            instrument_title="User query",
            agent_id="query",
        )
        entities = [token.text for token in doc.tokens if token.kiss_category == "ENTITY"]
        return QueryKISSResult(
            raw_query=query_text,
            entities=entities,
            entity_types={entity: "CONCEPT" for entity in entities},
            verbs=[token.lemma for token in doc.tokens if token.kiss_category == "VERB"],
            deontic_verbs=[
                token.lemma for token in doc.tokens if token.kiss_category == "VERB" and token.is_deontic
            ],
            sentence_count=doc.sentence_count,
            entity_count=len(entities),
            fallback_triggered=True,
            model_version=doc.model_version,
        )

    def _infer_entity_type(self, text: str, pos: str) -> str:
        entity_type = self._kiss_parser._entity_matcher.get_entity_type(text)
        if entity_type is not None:
            return entity_type
        if pos == "ENTITY_OVERRIDE":
            return "CONCEPT"
        return "CONCEPT"
