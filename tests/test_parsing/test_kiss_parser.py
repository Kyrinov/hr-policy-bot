from __future__ import annotations

from src.parsing.kiss_parser import KISSParser


def test_kiss_parser_is_deterministic() -> None:
    parser = KISSParser()
    text = "The delegated manager must approve an indeterminate IT-02 in the NCR."

    runs = [
        parser.parse_document(text, "https://example.invalid/policy", "Test Policy", "staffing")
        for _ in range(10)
    ]

    first = [
        (
            token.text,
            token.lemma,
            token.pos,
            token.kiss_category,
            token.is_deontic,
            token.deontic_type,
            token.char_start,
            token.char_end,
            token.sentence_idx,
            token.token_idx,
        )
        for token in runs[0].tokens
    ]
    for document in runs[1:]:
        assert [
            (
                token.text,
                token.lemma,
                token.pos,
                token.kiss_category,
                token.is_deontic,
                token.deontic_type,
                token.char_start,
                token.char_end,
                token.sentence_idx,
                token.token_idx,
            )
            for token in document.tokens
        ] == first


def test_kiss_parser_resolves_gc_entity_overrides_and_deontic_verbs() -> None:
    parser = KISSParser()

    document = parser.parse_document(
        "The delegated manager must approve an indeterminate IT-02 in the NCR.",
        "https://example.invalid/policy",
        "Test Policy",
        "staffing",
    )

    entities = [token.text for token in document.tokens if token.kiss_category == "ENTITY"]
    deontic = [token for token in document.tokens if token.is_deontic]

    assert "delegated manager" in entities
    assert "indeterminate" in entities
    assert "IT-02" in entities
    assert "NCR" in entities
    assert len(deontic) == 1
    assert deontic[0].text == "must"
    assert deontic[0].deontic_type == "obligation"
