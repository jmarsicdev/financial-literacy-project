
from unittest.mock import MagicMock

from app.ontology import service


def test_list_concepts(monkeypatch):
    concepts = [
        {
            "id": 1,
            "name": "Inflation",
            "description": "Rising prices",
            "category": "Macroeconomics",
        }
    ]

    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = concepts

    monkeypatch.setattr(
        service, "get_connection", lambda: conn
    )

    result = service.list_concepts()

    assert len(result) == 1
    assert result[0]["name"] == "Inflation"


def test_get_concept_with_relationships(monkeypatch):
    concept = {
        "id": 1,
        "name": "Inflation",
        "description": "Rising prices",
        "category": "Macroeconomics",
    }

    relationships = [
        {
            "source_name": "Inflation",
            "target_name": "Interest Rates",
            "relationship_type": "influences",
            "direction": "outgoing",
        }
    ]

    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.side_effect = [
        MagicMock(fetchone=lambda: concept),
        MagicMock(fetchall=lambda: relationships),
    ]

    monkeypatch.setattr(
        service, "get_connection", lambda: conn
    )

    result = service.get_concept(1)

    assert result["name"] == "Inflation"
    assert len(result["relationships"]) == 1
    assert (
        result["relationships"][0]["target_name"]
        == "Interest Rates"
    )


def test_concept_not_found(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = None

    monkeypatch.setattr(
        service, "get_connection", lambda: conn
    )

    assert service.get_concept(999) is None
