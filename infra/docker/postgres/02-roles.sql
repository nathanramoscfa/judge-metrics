-- infra/docker/postgres/02-roles.sql
-- Runs once on first start of the Compose PostgreSQL (docker-entrypoint-initdb.d)
-- against $POSTGRES_DB, as the $POSTGRES_USER superuser. Creates the three
-- application roles the brief's "separate public and administrative
-- permissions" requirement calls for. Passwords come from the environment
-- (.env via docker-compose.yml) through psql's \getenv; nothing is inlined.
--
--   judgemetrics_app     the public API: read-only on public tables
--   judgemetrics_ingest  the ingest runner: reads and writes public tables
--   judgemetrics_admin   migrations and admin tools: full control of the
--                        public schema (not a superuser)
--
-- The `restricted` schema (Phase 5) is granted separately when it is created;
-- judgemetrics_app never receives access to it.

\set ON_ERROR_STOP on
\getenv app_password JUDGEMETRICS_APP_DB_PASSWORD
\getenv ingest_password JUDGEMETRICS_INGEST_DB_PASSWORD
\getenv admin_password JUDGEMETRICS_ADMIN_DB_PASSWORD
\getenv db_name POSTGRES_DB
\getenv owner_name POSTGRES_USER

CREATE ROLE judgemetrics_app LOGIN PASSWORD :'app_password';
CREATE ROLE judgemetrics_ingest LOGIN PASSWORD :'ingest_password';
CREATE ROLE judgemetrics_admin LOGIN PASSWORD :'admin_password';

GRANT CONNECT ON DATABASE :"db_name" TO judgemetrics_app, judgemetrics_ingest, judgemetrics_admin;
GRANT TEMPORARY ON DATABASE :"db_name" TO judgemetrics_admin;

-- Admin: full control of the public schema (DDL for migrations).
GRANT ALL ON SCHEMA public TO judgemetrics_admin;

-- App: read-only on public tables and sequences.
GRANT USAGE ON SCHEMA public TO judgemetrics_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO judgemetrics_app;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO judgemetrics_app;

-- Ingest: reads and writes public tables; no DDL.
GRANT USAGE ON SCHEMA public TO judgemetrics_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO judgemetrics_ingest;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO judgemetrics_ingest;

-- Objects created later (migrations run as the admin role or as the Compose
-- superuser) inherit the same split automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE judgemetrics_admin IN SCHEMA public
    GRANT SELECT ON TABLES TO judgemetrics_app;
ALTER DEFAULT PRIVILEGES FOR ROLE judgemetrics_admin IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO judgemetrics_app;
ALTER DEFAULT PRIVILEGES FOR ROLE judgemetrics_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO judgemetrics_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE judgemetrics_admin IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO judgemetrics_ingest;

ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT SELECT ON TABLES TO judgemetrics_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO judgemetrics_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO judgemetrics_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO judgemetrics_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT ALL ON TABLES TO judgemetrics_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_name" IN SCHEMA public
    GRANT ALL ON SEQUENCES TO judgemetrics_admin;
