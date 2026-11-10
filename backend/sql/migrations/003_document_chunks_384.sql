-- for db volumes created before the local embedding model (all-MiniLM-L6-v2, 384 dims) replaced the 1536-dim placeholder
-- fresh volumes don't need this; init.sql already declares vector(384)
-- docker compose exec -T db psql -U team5 -d financial_literacy < backend/sql/migrations/003_document_chunks_384.sql
DO $$
BEGIN
  IF (
    SELECT atttypmod FROM pg_attribute
    WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'
  ) <> 384 THEN
    -- existing vectors have the wrong dimension and cannot be converted; re-run POST /search/index-news afterwards
    UPDATE document_chunks SET embedding = NULL;
    ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(384);
  END IF;
END $$;
