-- Run against the production/staging database using the same role as ContexA.
-- Expected result: every workspace-owned table has ENABLE + FORCE RLS and the
-- contexa_workspace_isolation policy with both USING and WITH CHECK predicates.
-- Public passport verification metadata and identity lookup are intentionally
-- outside workspace RLS and must remain inaccessible to anon/authenticated roles.

SELECT current_user AS application_role, r.rolsuper, r.rolbypassrls
FROM pg_roles r WHERE r.rolname = current_user;

WITH expected(table_name) AS (VALUES
  ('brand_rules'),
  ('content_documents'),
  ('audit_events'),
  ('rule_versions'),
  ('approved_facts'),
  ('scan_runs'),
  ('finding_evidence'),
  ('policy_simulations'),
  ('evaluation_cases'),
  ('evaluation_runs'),
  ('review_tasks'),
  ('guideline_chunks'),
  ('brand_assets'),
  ('review_findings'),
  ('monitored_sources'),
  ('truth_drift_events'),
  ('trust_passports'),
  ('media_inspections'),
  ('agent_runs'),
  ('digital_twin_scenarios'),
  ('language_reviews'),
  ('regulatory_requirements'),
  ('regulatory_assessments'),
  ('brand_incidents'),
  ('evidence_graph_nodes'),
  ('evidence_graph_edges'),
  ('decision_traces'),
  ('evidence_archives'),
  ('evidence_merkle_anchors')
)
SELECT e.table_name, COALESCE(c.relrowsecurity, false) AS rls_enabled,
       COALESCE(c.relforcerowsecurity, false) AS force_rls_enabled,
       (p.policyname = 'contexa_workspace_isolation'
        AND p.qual ILIKE '%app.workspace_id%'
        AND p.with_check ILIKE '%app.workspace_id%') AS policy_valid
FROM expected e
LEFT JOIN pg_class c ON c.relname = e.table_name AND c.relkind = 'r'
  AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = current_schema())
LEFT JOIN pg_policies p ON p.schemaname = current_schema()
  AND p.tablename = e.table_name
  AND p.policyname = 'contexa_workspace_isolation'
ORDER BY e.table_name;

-- Verify browser roles have no direct access to ContexA internals.
SELECT table_name, grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = current_schema()
  AND grantee IN ('anon', 'authenticated')
  AND table_name IN ('users', 'auth_action_tokens', 'brand_rules', 'content_documents',
                     'audit_events', 'trust_passports', 'agent_runs', 'decision_traces')
ORDER BY table_name, grantee, privilege_type;

-- Run ops/verify_postgres_rls.py after metadata checks. It inserts temporary
-- sentinel rows in two workspaces and verifies each tenant sees only its own.
