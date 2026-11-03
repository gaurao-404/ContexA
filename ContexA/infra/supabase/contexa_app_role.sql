-- Run in Supabase SQL Editor as the project's database administrator.
-- Replace the password placeholder with a unique 32+ character random password.
-- Store that password only in the backend host's DATABASE_URL secret.
--
-- This role deliberately has NOSUPERUSER and NOBYPASSRLS. It owns ContexA's
-- application tables so startup migrations and FORCE ROW LEVEL SECURITY policy
-- management can run, but PostgreSQL still enforces tenant policies for it.
-- Do not use the built-in `postgres` role as the production API connection.

DO $$
DECLARE
  role_password text := 'REPLACE_WITH_A_UNIQUE_RANDOM_PASSWORD';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'contexa_app') THEN
    IF role_password LIKE 'REPLACE_%' OR length(role_password) < 32 THEN
      RAISE EXCEPTION 'Edit contexa_app_role.sql and set a unique random password of at least 32 characters before running it';
    END IF;
    EXECUTE format(
      'CREATE ROLE contexa_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
      role_password
    );
  ELSE
    RAISE NOTICE 'contexa_app already exists; retain its secret or rotate it separately with ALTER ROLE';
  END IF;
END
$$;

-- Re-assert safety properties even if the role already existed.
ALTER ROLE contexa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE postgres TO contexa_app;
GRANT USAGE, CREATE ON SCHEMA public TO contexa_app;

-- Supabase provides pgvector as an available extension. Enable it as the
-- privileged project administrator before the application role starts.
CREATE EXTENSION IF NOT EXISTS vector;

-- Transfer existing public application objects to the runtime role. This makes
-- future ContexA startup migrations idempotent and lets it maintain FORCE RLS
-- policies without granting superuser/BYPASSRLS.
DO $$
DECLARE item record;
BEGIN
  -- Touch only ContexA tables; leave any other public-schema application data alone.
  FOR item IN
    SELECT n.nspname AS schema_name, c.relname AS table_name
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p')
       AND c.relname = ANY (ARRAY[
         'agent_runs','approved_facts','audit_events','auth_action_tokens','brand_assets',
         'brand_incidents','brand_rules','content_documents','decision_traces',
         'digital_twin_scenarios','evaluation_cases','evaluation_runs','evidence_archives',
         'evidence_graph_edges','evidence_graph_nodes','evidence_merkle_anchors',
         'finding_evidence','guideline_chunks','language_reviews','login_attempts',
         'media_inspections','monitored_sources','passport_signatures','policy_simulations',
         'public_passport_index','regulatory_assessments','regulatory_requirements',
         'review_findings','review_tasks','rule_versions','scan_runs','trust_passports',
         'truth_drift_events','users','schema_migrations'
       ])
  LOOP
    EXECUTE format('ALTER TABLE %I.%I OWNER TO contexa_app', item.schema_name, item.table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM anon, authenticated', item.schema_name, item.table_name);
  END LOOP;

  FOR item IN
    SELECT ns.nspname AS schema_name, seq.relname AS sequence_name
      FROM pg_class seq
      JOIN pg_namespace ns ON ns.oid = seq.relnamespace
      JOIN pg_depend dep ON dep.objid = seq.oid AND dep.deptype IN ('a', 'i')
      JOIN pg_class tbl ON tbl.oid = dep.refobjid
     WHERE seq.relkind = 'S' AND ns.nspname = 'public'
       AND tbl.relname = ANY (ARRAY[
         'agent_runs','approved_facts','audit_events','auth_action_tokens','brand_assets',
         'brand_incidents','brand_rules','content_documents','decision_traces',
         'digital_twin_scenarios','evaluation_cases','evaluation_runs','evidence_archives',
         'evidence_graph_edges','evidence_graph_nodes','evidence_merkle_anchors',
         'finding_evidence','guideline_chunks','language_reviews','login_attempts',
         'media_inspections','monitored_sources','passport_signatures','policy_simulations',
         'public_passport_index','regulatory_assessments','regulatory_requirements',
         'review_findings','review_tasks','rule_versions','scan_runs','trust_passports',
         'truth_drift_events','users','schema_migrations'
       ])
  LOOP
    EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO contexa_app', item.schema_name, item.sequence_name);
    EXECUTE format('REVOKE ALL ON SEQUENCE %I.%I FROM anon, authenticated', item.schema_name, item.sequence_name);
  END LOOP;
END
$$;

-- ContexA uses its own authenticated API and app.workspace_id RLS context;
-- only the listed ContexA application tables above have browser-role grants revoked.

-- Sanity check: the API role must not bypass RLS.
DO $$
DECLARE role_flags record;
BEGIN
  SELECT rolsuper, rolbypassrls INTO role_flags FROM pg_roles WHERE rolname = 'contexa_app';
  IF role_flags.rolsuper OR role_flags.rolbypassrls THEN
    RAISE EXCEPTION 'contexa_app must be NOSUPERUSER and NOBYPASSRLS';
  END IF;
END
$$;
