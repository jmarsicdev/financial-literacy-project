import os
from urllib.parse import urlsplit, urlunsplit

from tavily import TavilyClient

from app.db import get_connection


def import_search(query="Apple AAPL company financial news"):
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise ValueError("TAVILY_API_KEY is missing")

    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        search_depth="basic",
        max_results=5,
        include_raw_content=True,
    )

    results = response.get("results", [])

    if not results:
        print("No search results returned. Nothing was saved.")
        return

    sql = """
        INSERT INTO search_results (
            title, url, normalized_url, content, raw_content,
            source_domain, score, query_text, provider
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (normalized_url)
        DO UPDATE SET
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            content = EXCLUDED.content,
            raw_content = EXCLUDED.raw_content,
            source_domain = EXCLUDED.source_domain,
            score = EXCLUDED.score,
            query_text = EXCLUDED.query_text,
            provider = EXCLUDED.provider,
            fetched_at = now()
    """

    saved = 0

    with get_connection() as conn:
        with conn.cursor() as cursor:
            for result in results:
                title = result.get("title")
                url = result.get("url")

                if not title or not url:
                    continue

                parts = urlsplit(url)
                normalized_url = urlunsplit((
                    parts.scheme.lower(),
                    parts.netloc.lower(),
                    parts.path,
                    parts.query,
                    "",
                ))

                cursor.execute(sql, (
                    title,
                    url,
                    normalized_url,
                    result.get("content"),
                    result.get("raw_content"),
                    parts.hostname,
                    result.get("score"),
                    query,
                    "tavily",
                ))
                saved += 1

    print(f"Saved or updated {saved} search results.")


if __name__ == "__main__":
    import_search()