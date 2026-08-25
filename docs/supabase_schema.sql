-- Cognitive Logic — app schema for Supabase (Postgres)
--
-- Run in: Supabase → SQL Editor → New query → Run
-- You do NOT need CREATE DATABASE; Supabase already provides `postgres`.
--
-- Optional: the API also creates these on first boot via SQLAlchemy
-- (init_db). Use this script if you want the schema ready before deploy,
-- or to recreate a clean project.
--
-- Connection string for Render / .env:
--   postgresql+asyncpg://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
-- (use the pooled URI from Project Settings → Database; keep +asyncpg)

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL DEFAULT '',
    full_name       VARCHAR(255),
    supabase_id     VARCHAR(64),
    role            VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_supabase_id ON users (supabase_id);

CREATE TABLE IF NOT EXISTS data_sources (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER REFERENCES users (id),
    name              VARCHAR(255) NOT NULL,
    source_type       VARCHAR(50) NOT NULL,
    connection_config TEXT,
    schema_json       TEXT,
    created_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS queries (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER REFERENCES users (id),
    data_source_id   INTEGER NOT NULL REFERENCES data_sources (id),
    natural_language TEXT NOT NULL,
    generated_sql    TEXT,
    result_json      TEXT,
    status           VARCHAR(50) NOT NULL DEFAULT 'pending',
    session_id       VARCHAR(64),
    answer           TEXT,
    response_format  VARCHAR(20),
    diagnosis_json   TEXT,
    created_at       TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_queries_session_id ON queries (session_id);

CREATE TABLE IF NOT EXISTS conversations (
    id         VARCHAR(64) PRIMARY KEY,
    user_id    INTEGER REFERENCES users (id),
    title      VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboards (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users (id),
    name        VARCHAR(255) NOT NULL,
    layout_json TEXT,
    created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Singleton runtime settings (AI providers, branding). Row id = 1.
CREATE TABLE IF NOT EXISTS app_config (
    id         INTEGER PRIMARY KEY,
    data_json  TEXT NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

COMMIT;
