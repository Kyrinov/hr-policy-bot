from __future__ import annotations

from src.models.schemas import PolicyTriple
from src.parsing.graph_query import GraphQueryEngine


def test_graph_query_scoring_prioritizes_subject_entity_matches() -> None:
    graph = GraphQueryEngine()
    triple = PolicyTriple(
        triple_id="triple-1",
        doc_id="doc-1",
        source_url="https://example.invalid/policy",
        instrument_title="Test Policy",
        agent_id="staffing",
        section_heading=None,
        sentence_text="The delegated manager must approve an indeterminate IT-02.",
        subject="delegated manager",
        predicate="must",
        predicate_lemma="must",
        is_deontic=True,
        deontic_type="obligation",
        object_="indeterminate",
        modifier=None,
        validation_flags=["CROSS_INSTRUMENT_CORROBORATION"],
    )

    score = graph._score(
        triple,
        query_entities=["delegated manager", "indeterminate"],
        query_verbs=["must"],
    )

    assert score == 5
