

from functools import lru_cache

from sentence_transformers import SentenceTransformer
from psycopg.rows import dict_row

from ..db import get_connection


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model():
    """Load the local embedding model once."""
    return SentenceTransformer(MODEL_NAME, device="cpu")


def embed_text(text: str) -> list[float]:
    """Generate a 384-dimensional embedding locally."""
    return get_model().encode(text).tolist()


def index_news() -> int:
    """Index financial news from search_results into document_chunks."""
    with get_connection() as conn:
        conn.row_factory = dict_row
        articles = conn.execute(
            """
            SELECT id, title, url, content
            FROM search_results
            WHERE content IS NOT NULL
                AND length(trim(content)) > 0
                AND url IS NOT NULL
                AND length(trim(url)) > 0
                AND COALESCE(source_domain, '') NOT IN (
                    'tavily.com',
                    'www.tavily.com'
                )
            ORDER BY id
            """
        ).fetchall()

    indexed = 0

    for article in articles:
        text = f"{article['title']}\n\n{article['content']}"

        # Skip articles that have already been indexed unchanged.
        with get_connection() as conn:
            existing = conn.execute(
                """
                SELECT chunk_text
                FROM document_chunks
                WHERE source_url = %s AND chunk_index = 0
                  AND embedding IS NOT NULL
                """,
                (article["url"],),
            ).fetchone()

        if existing and existing[0] == text:
            continue

        vector = embed_text(text)

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO document_chunks
                    (source_url, title, chunk_text,
                     chunk_index, metadata, embedding)
                VALUES (%s, %s, %s, 0,
                        jsonb_build_object(
                            'source', 'search_results',
                            'search_result_id', %s
                        ),
                        %s::vector)
                ON CONFLICT (source_url, chunk_index)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    chunk_text = EXCLUDED.chunk_text,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                """,
                (
                    article["url"],
                    article["title"],
                    text,
                    article["id"],
                    str(vector),
                ),
            )

        indexed += 1

    return indexed


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Find articles ranked by cosine similarity."""
    vector = embed_text(query)

    with get_connection() as conn:
        conn.row_factory = dict_row

        rows = conn.execute(
            """
            SELECT
                id,
                title,
                source_url,
                chunk_text,
                metadata,
                1 - (embedding <=> %s::vector) AS similarity
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (str(vector), str(vector), top_k),
        ).fetchall()

    return rows
