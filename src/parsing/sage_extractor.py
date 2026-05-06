from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections import defaultdict
from pathlib import Path

from src.config import get_config
from src.data.db import DatabaseManager
from src.models.schemas import KISSDocument, KISSToken, PolicyTriple
from src.parsing.kiss_parser import KISSParser

logger = logging.getLogger(__name__)
_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "policy_registry.json"
_GC_ACTORS = {"employee", "deputy head", "delegated manager", "treasury board", "psc", "tbs", "adm", "dm"}


class SageExtractor:
    def __init__(self, db: DatabaseManager | None = None, parser: KISSParser | None = None) -> None:
        self._config = get_config()
        self._db = db or DatabaseManager()
        self._parser = parser or KISSParser()

    async def process_document(
        self,
        source_url: str,
        text: str,
        instrument_title: str,
        agent_id: str,
    ) -> list[PolicyTriple]:
        if not self._config.parsing.enabled:
            return []
        document = await self._parse_in_thread(text, source_url, instrument_title, agent_id)
        doc_id = self._doc_id(document)
        triples = self.extract_triples(document, doc_id)
        await self._db.initialize()
        await self._db.save_kiss_document(doc_id, document)
        await self._db.save_policy_triples(triples)
        logger.info("Parsed %s into %d triples", source_url, len(triples))
        return triples

    async def process_document_for_url(self, source_url: str, text: str) -> list[PolicyTriple]:
        instrument = self._instrument_for_url(source_url)
        if instrument is None:
            logger.debug("Skipping deterministic parsing for unknown URL %s", source_url)
            return []
        agent_ids = instrument.get("agent_ids", ["unknown"])
        return await self.process_document(
            source_url=source_url,
            text=text,
            instrument_title=instrument.get("title", source_url),
            agent_id=agent_ids[0] if agent_ids else "unknown",
        )

    async def _parse_in_thread(
        self, text: str, source_url: str, instrument_title: str, agent_id: str
    ) -> KISSDocument:
        import asyncio

        return await asyncio.to_thread(
            self._parser.parse_document,
            text,
            source_url,
            instrument_title,
            agent_id,
        )

    def extract_triples(self, document: KISSDocument, doc_id: str) -> list[PolicyTriple]:
        triples: list[PolicyTriple] = []
        by_sentence: dict[int, list[KISSToken]] = defaultdict(list)
        for token in document.tokens:
            by_sentence[token.sentence_idx].append(token)

        for tokens in by_sentence.values():
            triple = self._extract_sentence_triple(document, doc_id, tokens)
            if triple is not None:
                triples.append(triple)
        return self._apply_cross_sentence_rules(triples)

    def _extract_sentence_triple(
        self, document: KISSDocument, doc_id: str, tokens: list[KISSToken]
    ) -> PolicyTriple | None:
        verbs = [token for token in tokens if token.kiss_category == "VERB"]
        entities = [token for token in tokens if token.kiss_category == "ENTITY"]
        if not verbs or len(entities) < 2:
            return None

        predicate = next((verb for verb in verbs if verb.is_deontic), verbs[0])
        before = [entity for entity in entities if entity.char_end <= predicate.char_start]
        after = [entity for entity in entities if entity.char_start >= predicate.char_end]
        if not before or not after:
            return None

        subject = before[-1]
        object_token = after[0]
        sentence_text = self._sentence_text(tokens)
        flags = self._validation_flags(subject.text, predicate, object_token.text, sentence_text)
        return PolicyTriple(
            triple_id=str(uuid.uuid4()),
            doc_id=doc_id,
            source_url=document.source_url,
            instrument_title=document.instrument_title,
            agent_id=document.agent_id,
            section_heading=self._section_heading(tokens),
            sentence_text=sentence_text,
            subject=subject.text,
            predicate=predicate.text,
            predicate_lemma=predicate.lemma.lower(),
            is_deontic=predicate.is_deontic,
            deontic_type=predicate.deontic_type,
            object_=object_token.text,
            modifier=self._modifier(tokens, predicate),
            validation_flags=flags,
        )

    def _validation_flags(
        self, subject: str, predicate: KISSToken, object_text: str, sentence_text: str
    ) -> list[str]:
        flags: list[str] = []
        rules = self._config.parsing.validation_rules
        if (
            rules.get("RULE-01")
            and rules["RULE-01"].enabled
            and predicate.deontic_type == "obligation"
            and subject.lower() not in _GC_ACTORS
        ):
            flags.append("UNANCHORED_OBLIGATION")
        section_regex = rules.get("RULE-03").section_ref_regex if rules.get("RULE-03") else None
        if section_regex and re.search(section_regex, object_text) and object_text not in sentence_text:
            flags.append("DANGLING_CROSS_REFERENCE")
        if (
            rules.get("RULE-04")
            and rules["RULE-04"].enabled
            and subject.lower() == "employee"
            and predicate.deontic_type == "discretion"
        ):
            flags.append("DISCRETIONARY_RIGHT")
        return flags

    def _apply_cross_sentence_rules(self, triples: list[PolicyTriple]) -> list[PolicyTriple]:
        seen: dict[tuple[str, str], str] = {}
        output: list[PolicyTriple] = []
        for triple in triples:
            flags = list(triple.validation_flags)
            key = (triple.subject.lower(), triple.predicate_lemma.lower())
            previous_object = seen.get(key)
            if previous_object is not None and previous_object.lower() != triple.object_.lower():
                flags.append("POTENTIAL_CONFLICT")
            seen[key] = triple.object_
            output.append(
                PolicyTriple(
                    **{
                        **triple.__dict__,
                        "validation_flags": sorted(set(flags)),
                    }
                )
            )
        return output

    def _sentence_text(self, tokens: list[KISSToken]) -> str:
        ordered = sorted(tokens, key=lambda token: token.char_start)
        return " ".join(token.text for token in ordered).strip()

    def _section_heading(self, tokens: list[KISSToken]) -> str | None:
        for token in tokens:
            if token.pos == "ENTITY_OVERRIDE" and token.text.lower().startswith(("section", "article", "s.")):
                return token.text
        return None

    def _modifier(self, tokens: list[KISSToken], predicate: KISSToken) -> str | None:
        connectors = [
            token.text
            for token in tokens
            if token.kiss_category == "CONNECTOR" and token.char_start > predicate.char_end
        ]
        return " ".join(connectors[:6]) or None

    def _doc_id(self, document: KISSDocument) -> str:
        payload = f"{document.source_url}:{document.parsed_at}:{document.token_count}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _instrument_for_url(self, source_url: str) -> dict | None:
        normalized = source_url.rstrip("/")
        with open(_REGISTRY_PATH) as f:
            registry = json.load(f)
        for instrument in registry:
            url = instrument.get("url", "").rstrip("/")
            if url == normalized:
                return instrument
            if url.endswith("/FullText.html") and url.removesuffix("/FullText.html") == normalized:
                return instrument
        return None


_pipeline: SageExtractor | None = None


def get_sage_pipeline() -> SageExtractor:
    global _pipeline
    if _pipeline is None:
        _pipeline = SageExtractor()
    return _pipeline
