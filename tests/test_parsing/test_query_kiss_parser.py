from __future__ import annotations

from src.parsing.query_kiss_parser import QueryKISSParser


def test_query_kiss_parser_canonical_grievance_query() -> None:
    parser = QueryKISSParser()

    result = parser.parse(
        "I have an employee who has filed a grievance related to discrimination "
        "based on racial characteristics. What do I need to know?"
    )

    assert result is not None
    assert result.fallback_triggered is False
    assert "employee" in result.entities
    assert "grievance" in result.entities
    assert "discrimination" in result.entities
    assert "racial characteristics" in result.entities


def test_query_kiss_parser_canonical_staffing_query() -> None:
    parser = QueryKISSParser()

    result = parser.parse("I want to hire an indeterminate IT-02, they will work in the NCR.")

    assert result is not None
    assert result.fallback_triggered is False
    assert "indeterminate" in result.entities
    assert "IT-02" in result.entities
    assert "NCR" in result.entities
