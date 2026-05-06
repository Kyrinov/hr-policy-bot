from __future__ import annotations

from src.config import get_config
from src.data.db import DatabaseManager
from src.models.schemas import PolicyTriple


class GraphQueryEngine:
    def __init__(self, db: DatabaseManager | None = None) -> None:
        self._config = get_config()
        self._db = db or DatabaseManager()

    async def search_triples_semantic(
        self,
        query_entities: list[str],
        query_verbs: list[str],
        agent_id: str | None = None,
    ) -> list[PolicyTriple]:
        await self._db.initialize()
        candidates = await self._db.search_policy_triples(
            query_entities=query_entities,
            query_verbs=query_verbs,
            agent_id=agent_id,
            limit=self._config.parsing.max_graph_results,
        )
        scored = [
            (self._score(triple, query_entities, query_verbs), triple)
            for triple in candidates
        ]
        return [
            triple
            for score, triple in sorted(scored, key=lambda item: item[0], reverse=True)
            if score > 0
        ][: self._config.parsing.max_graph_results]

    async def query_triples_by_url(self, source_url: str) -> list[PolicyTriple]:
        await self._db.initialize()
        return await self._db.query_triples_by_url(source_url)

    async def find_conflicts(
        self, subject: str, predicate: str
    ) -> list[tuple[PolicyTriple, PolicyTriple]]:
        await self._db.initialize()
        triples = await self._db.find_conflicting_triples(subject, predicate)
        conflicts: list[tuple[PolicyTriple, PolicyTriple]] = []
        for index, left in enumerate(triples):
            for right in triples[index + 1 :]:
                if left.object_.lower() != right.object_.lower():
                    conflicts.append((left, right))
        return conflicts

    async def get_entity_neighborhood(
        self, entity_text: str, depth: int = 2
    ) -> list[PolicyTriple]:
        await self._db.initialize()
        return await self._db.search_policy_triples(
            query_entities=[entity_text],
            query_verbs=[],
            agent_id=None,
            limit=max(depth, 1) * self._config.parsing.max_graph_results,
        )

    async def is_document_parsed(self, source_url: str) -> bool:
        await self._db.initialize()
        return await self._db.is_document_parsed(source_url)

    async def get_coverage_stats(self) -> dict:
        await self._db.initialize()
        return await self._db.get_coverage_stats()

    def _score(
        self, triple: PolicyTriple, query_entities: list[str], query_verbs: list[str]
    ) -> int:
        score = 0
        subject = triple.subject.lower()
        object_text = triple.object_.lower()
        for entity in query_entities:
            lowered = entity.lower()
            if lowered in subject or subject in lowered:
                score += 2
            if lowered in object_text or object_text in lowered:
                score += 1
        if triple.predicate_lemma.lower() in {verb.lower() for verb in query_verbs}:
            score += 1
        if "CROSS_INSTRUMENT_CORROBORATION" in triple.validation_flags:
            score += 1
        return score


_graph_query: GraphQueryEngine | None = None


def get_graph_query() -> GraphQueryEngine:
    global _graph_query
    if _graph_query is None:
        _graph_query = GraphQueryEngine()
    return _graph_query
