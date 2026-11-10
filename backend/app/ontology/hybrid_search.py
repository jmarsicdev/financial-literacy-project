
import re

from psycopg.rows import dict_row

from ..db import get_connection
from ..semantic_search.service import semantic_search


def find_matching_concepts(query: str, limit: int = 5):
    """Find ontology concepts explicitly mentioned in a question."""
    matches = []

    with get_connection() as conn:
        conn.row_factory = dict_row
        concepts = conn.execute(
            """
            SELECT id, name, description, category
            FROM financial_concepts
            ORDER BY length(name) DESC
            """
        ).fetchall()

    for concept in concepts:
        pattern = r"(?<!\w)" + re.escape(concept["name"]) + r"(?!\w)"

        if re.search(pattern, query, re.IGNORECASE):
            matches.append(concept)

        if len(matches) >= limit:
            break

    return matches


def get_related_concepts(concept_ids: list[int], limit: int = 15):
    """Retrieve directly connected ontology relationships."""
    if not concept_ids:
        return []

    with get_connection() as conn:
        conn.row_factory = dict_row

        relationships = conn.execute(
            """
            SELECT
                source.name AS source_name,
                target.name AS target_name,
                r.relationship_type,
                r.description
            FROM concept_relationships r
            JOIN financial_concepts source
                ON source.id = r.source_concept_id
            JOIN financial_concepts target
                ON target.id = r.target_concept_id
            WHERE r.source_concept_id = ANY(%s)
               OR r.target_concept_id = ANY(%s)
            ORDER BY r.id
            LIMIT %s
            """,
            (concept_ids, concept_ids, limit),
        ).fetchall()

    return relationships


def hybrid_search(query: str, top_k: int = 5):
    """Combine ontology relationships with semantic article retrieval."""
    matched = find_matching_concepts(query)
    related = get_related_concepts([c["id"] for c in matched])

    # Expand the query using concepts directly connected in the graph.
    names = {c["name"] for c in matched}

    for relationship in related:
        names.add(relationship["source_name"])
        names.add(relationship["target_name"])

    expanded_query = query

    if names:
        expanded_query += "\nRelated financial concepts: " + ", ".join(
            sorted(names)
        )

    # Preserve the original retrieval as a baseline.
    baseline_results = semantic_search(query, top_k)

    # Search with ontology-enriched context when concepts are found.
    if matched:
        results = semantic_search(expanded_query, top_k)
    else:
        results = baseline_results

    return {
        "query": query,
        "expanded_query": expanded_query,
        "matched_concepts": matched,
        "relationships": related,
        "baseline_results": baseline_results,
        "results": results,
        "count": len(results),
    }
