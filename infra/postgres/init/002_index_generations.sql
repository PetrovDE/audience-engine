CREATE TABLE IF NOT EXISTS index_generations (
    id BIGSERIAL PRIMARY KEY,
    alias_name TEXT NOT NULL,
    emb_version TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    generation TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('built', 'validated', 'promoted', 'rolled_back', 'failed')),
    points_count INTEGER NOT NULL DEFAULT 0 CHECK (points_count >= 0),
    previous_collection_name TEXT,
    validation_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ,
    promoted_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ,
    UNIQUE (alias_name, collection_name)
);

CREATE INDEX IF NOT EXISTS idx_index_generations_alias_created_at
ON index_generations (alias_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_index_generations_status_created_at
ON index_generations (status, created_at DESC);
