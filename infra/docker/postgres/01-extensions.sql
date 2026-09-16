-- infra/docker/postgres/01-extensions.sql
-- Runs once on first start of the Compose PostgreSQL (docker-entrypoint-initdb.d)
-- against $POSTGRES_DB. pg_trgm backs the trigram search indexes and the
-- /api/v1/search endpoint (Phase 1 Steps 2 and 4).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
