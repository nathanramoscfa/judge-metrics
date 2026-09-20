-- infra/docker/postgres/03-test-database.sql
-- Creates the scratch database the test suite uses (Phase 2 Step 5) so that
-- `uv run poe check` never touches a developer's live ingest. Runs once on
-- first start of the Compose PostgreSQL (docker-entrypoint-initdb.d), after
-- 02-roles.sql, and again — idempotently — through the `postgres-test-init`
-- one-shot job (`uv run poe up`) for a volume created before this script
-- existed, and in CI against the service container.
--
--   judgemetrics_test  owned by the $POSTGRES_USER superuser; pg_trgm; the
--                      three application roles hold the same grants and
--                      default privileges as on $POSTGRES_DB (02-roles.sql)
--
-- The tests connect through JUDGEMETRICS_TEST_DATABASE_URL (the owner: it
-- runs the migrations, including the round trip to base and back) and reach
-- the app and ingest roles by retargeting their configured URLs at this
-- database (tests/conftest.py, `test_settings`). Nothing here reads a
-- password: the roles already exist.

\set ON_ERROR_STOP on
\getenv owner_name POSTGRES_USER

SELECT format('CREATE DATABASE %I OWNER %I', 'judgemetrics_test', :'owner_name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'judgemetrics_test')
\gexec

GRANT CONNECT ON DATABASE judgemetrics_test TO judgemetrics_app, judgemetrics_ingest, judgemetrics_admin;
GRANT TEMPORARY ON DATABASE judgemetrics_test TO judgemetrics_admin;

\connect judgemetrics_test

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The same split as 02-roles.sql, on this database's public schema.
GRANT ALL ON SCHEMA public TO judgemetrics_admin;

GRANT USAGE ON SCHEMA public TO judgemetrics_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO judgemetrics_app;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO judgemetrics_app;

GRANT USAGE ON SCHEMA public TO judgemetrics_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO judgemetrics_ingest;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO judgemetrics_ingest;

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

-- This script reruns on every `uv run poe up` (and so on every `bootstrap`),
-- after the migrations on an existing volume, and the blanket grants above
-- would re-open the restricted tables to the app role. Re-apply the
-- migrations' revokes for every restricted table that exists (none exists on
-- a fresh volume, where the migrations apply them later): the app role never
-- reads person_identifier, correction_request (INSERT only, revision 0007),
-- audit_log, or entity_resolution_candidate; the ingest role only appends
-- to audit_log.
DO $$
DECLARE
    restricted text;
BEGIN
    FOREACH restricted IN ARRAY ARRAY[
        'person_identifier', 'correction_request', 'audit_log', 'entity_resolution_candidate'
    ] LOOP
        IF to_regclass('public.' || restricted) IS NOT NULL THEN
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM judgemetrics_app', restricted);
        END IF;
    END LOOP;
    IF to_regclass('public.correction_request') IS NOT NULL THEN
        EXECUTE 'GRANT INSERT ON TABLE public.correction_request TO judgemetrics_app';
    END IF;
    IF to_regclass('public.audit_log') IS NOT NULL THEN
        EXECUTE 'REVOKE ALL ON TABLE public.audit_log FROM judgemetrics_ingest';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.audit_log TO judgemetrics_ingest';
    END IF;
END $$;
