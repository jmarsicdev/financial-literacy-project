# Financial Ontology and Hybrid Search

## Overview

The financial ontology provides structured financial concepts
and relationships to support semantic search.

Features:

- 25 financial concepts
- 24 concept relationships
- PostgreSQL-backed ontology
- Local Sentence Transformers embeddings
- Ontology-enhanced semantic search using pgvector
- No additional paid AI services required

## Database Setup

Start PostgreSQL:

    docker compose up -d db

From the project root, apply the migrations in order:

    Get-Content backend/sql/migrations/001_financial_ontology.sql -Raw | docker compose exec -T db psql -U team5 -d financial_literacy -v ON_ERROR_STOP=1

    Get-Content backend/sql/migrations/002_seed_financial_ontology.sql -Raw | docker compose exec -T db psql -U team5 -d financial_literacy -v ON_ERROR_STOP=1

These commands are intended for PowerShell.

Existing database data is preserved.
The migrations must also be applied to existing Docker volumes.

## API Endpoints

GET /ontology/concepts
Lists financial concepts.

GET /ontology/search?query=inflation
Searches financial concepts.

GET /ontology/concepts/1
Returns a concept and its relationships.

POST /search/semantic
Runs standard semantic document retrieval.

POST /search/hybrid
Runs ontology-enhanced semantic retrieval.

POST /search/index-news
Indexes eligible financial news into pgvector.

## Hybrid Search Example

POST /search/hybrid

Request:

    {
      "query": "How does inflation affect investments?",
      "top_k": 5
    }

The response includes:

- Matched financial concepts
- Related ontology relationships
- Expanded search query
- Original semantic search results
- Ontology-enhanced search results

## Testing

From the backend directory:

    python -m pytest tests/ -q

The ontology and hybrid search unit tests use mocks and
do not require external API calls.

## Current Limitations

- Concept recognition uses exact concept names.
- Ontology relationships are curated manually.
- Retrieval quality depends on indexed document coverage.
- Hybrid query expansion does not guarantee better ranking.
- Full RAG answer generation is handled separately.
