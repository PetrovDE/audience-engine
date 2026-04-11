-- Init 010: Persisted user credentials and password lifecycle foundation.
-- Mirrors infra/postgres/migrations/010_user_credentials_login.sql.

CREATE TABLE IF NOT EXISTS ae_user_credentials (
    user_id UUID PRIMARY KEY REFERENCES ae_users(user_id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    require_password_reset BOOLEAN NOT NULL DEFAULT FALSE,
    password_updated_by TEXT NOT NULL,
    password_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ae_user_credentials_password_updated
ON ae_user_credentials (password_updated_at DESC);

