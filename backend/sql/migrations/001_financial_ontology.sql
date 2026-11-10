
CREATE TABLE IF NOT EXISTS financial_concepts (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS concept_relationships (
    id BIGSERIAL PRIMARY KEY,
    source_concept_id BIGINT NOT NULL
        REFERENCES financial_concepts(id) ON DELETE CASCADE,
    target_concept_id BIGINT NOT NULL
        REFERENCES financial_concepts(id) ON DELETE CASCADE,
    relationship_type VARCHAR(60) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT no_self_relationship
        CHECK (source_concept_id <> target_concept_id),

    CONSTRAINT unique_concept_relationship
        UNIQUE (
            source_concept_id,
            target_concept_id,
            relationship_type
        )
);

CREATE INDEX IF NOT EXISTS idx_concept_relationships_source
    ON concept_relationships(source_concept_id);

CREATE INDEX IF NOT EXISTS idx_concept_relationships_target
    ON concept_relationships(target_concept_id);

CREATE INDEX IF NOT EXISTS idx_financial_concepts_category
    ON financial_concepts(category);
