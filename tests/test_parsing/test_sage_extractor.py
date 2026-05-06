from __future__ import annotations

from src.parsing.kiss_parser import KISSParser
from src.parsing.sage_extractor import SageExtractor


def test_sage_extractor_builds_policy_triple() -> None:
    parser = KISSParser()
    document = parser.parse_document(
        "The delegated manager must approve an indeterminate IT-02 in the NCR.",
        "https://example.invalid/policy",
        "Test Policy",
        "staffing",
    )
    extractor = SageExtractor(parser=parser)

    triples = extractor.extract_triples(document, "doc-1")

    assert len(triples) == 1
    assert triples[0].subject == "delegated manager"
    assert triples[0].predicate == "must"
    assert triples[0].deontic_type == "obligation"
    assert triples[0].object_ == "indeterminate"
