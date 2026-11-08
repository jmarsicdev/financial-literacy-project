
from psycopg.rows import dict_row

from ..db import get_connection


def list_concepts(category=None, limit=100):
    """Retrieve financial concepts, optionally filtered by category."""
    with get_connection() as conn:
        conn.row_factory = dict_row

        if category:
            rows = conn.execute(
                """
                SELECT id, name, description, category
                FROM financial_concepts
                WHERE category = %s
                ORDER BY name
                LIMIT %s
                """,
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, name, description, category
                FROM financial_concepts
                ORDER BY name
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

    return rows


def get_concept(concept_id):
    """Retrieve a concept and its incoming/outgoing relationships."""
    with get_connection() as conn:
        conn.row_factory = dict_row

        concept = conn.execute(
            """
            SELECT id, name, description, category
            FROM financial_concepts
            WHERE id = %s
            """,
            (concept_id,),
        ).fetchone()

        if concept is None:
            return None

        relationships = conn.execute(
            """
            SELECT
                r.id,
                r.relationship_type,
                r.description,
                source.id AS source_id,
                source.name AS source_name,
                target.id AS target_id,
                target.name AS target_name,
                CASE
                    WHEN r.source_concept_id = %s
                    THEN 'outgoing'
                    ELSE 'incoming'
                END AS direction
            FROM concept_relationships r
            JOIN financial_concepts source
                ON source.id = r.source_concept_id
            JOIN financial_concepts target
                ON target.id = r.target_concept_id
            WHERE r.source_concept_id = %s
               OR r.target_concept_id = %s
            ORDER BY r.relationship_type, source.name, target.name
            """,
            (concept_id, concept_id, concept_id),
        ).fetchall()

    return {
        **concept,
        "relationships": relationships,
    }


def search_concepts(query, limit=20):
    """Search concepts by name or description."""
    pattern = f"%{query.strip()}%"

    with get_connection() as conn:
        conn.row_factory = dict_row

        rows = conn.execute(
            """
            SELECT id, name, description, category
            FROM financial_concepts
            WHERE name ILIKE %s
               OR description ILIKE %s
            ORDER BY
                CASE WHEN name ILIKE %s THEN 0 ELSE 1 END,
                name
            LIMIT %s
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()

    return rows
