-- ContexA full Round 3 additive PostgreSQL migration.
-- Run as a database migration role before the application role is put into service.
-- Requires PostgreSQL 16+ and pgvector. Runtime app code also performs safe create_all
-- and a small set of additive column checks, but this file is the explicit DBA record.
BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;

-- Existing table extensions
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE brand_rules ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) NOT NULL DEFAULT 'hashed-token-v1';
ALTER TABLE content_documents ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE content_documents ADD COLUMN IF NOT EXISTS scan_status VARCHAR(24) NOT NULL DEFAULT 'not_configured';
ALTER TABLE review_findings ADD COLUMN IF NOT EXISTS rule_version_id VARCHAR(36);
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS previous_hash VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS event_hash VARCHAR(64) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_review_findings_rule_version_id ON review_findings(rule_version_id);

CREATE TABLE IF NOT EXISTS rule_versions (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 rule_id VARCHAR(36) NOT NULL REFERENCES brand_rules(id) ON DELETE CASCADE,
 version_number INTEGER NOT NULL, snapshot JSON NOT NULL DEFAULT '{}'::json,
 change_note TEXT NOT NULL DEFAULT '', created_by VARCHAR(36), created_at TIMESTAMPTZ,
 CONSTRAINT uq_rule_version_number UNIQUE(rule_id,version_number)
);
CREATE INDEX IF NOT EXISTS ix_rule_versions_workspace_id ON rule_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_rule_versions_rule_id ON rule_versions(rule_id);

CREATE TABLE IF NOT EXISTS approved_facts (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, fact_key VARCHAR(120) NOT NULL,
 fact_type VARCHAR(40) NOT NULL DEFAULT 'other', entity_name VARCHAR(180) NOT NULL DEFAULT '',
 canonical_value TEXT NOT NULL, aliases JSON NOT NULL DEFAULT '[]'::json, currency VARCHAR(8), unit VARCHAR(60),
 source_document VARCHAR(255) NOT NULL, source_quote TEXT NOT NULL,
 source_document_id VARCHAR(36) REFERENCES content_documents(id) ON DELETE SET NULL,
 source_verified BOOLEAN NOT NULL DEFAULT FALSE, source_page INTEGER, valid_from TIMESTAMPTZ, valid_until TIMESTAMPTZ,
 status VARCHAR(20) NOT NULL DEFAULT 'draft', version_number INTEGER NOT NULL DEFAULT 1,
 supersedes_id VARCHAR(36) REFERENCES approved_facts(id), created_by VARCHAR(36) NOT NULL,
 approved_by VARCHAR(36), approved_at TIMESTAMPTZ, created_at TIMESTAMPTZ,
 CONSTRAINT uq_fact_version UNIQUE(workspace_id,fact_key,version_number)
);
CREATE INDEX IF NOT EXISTS ix_approved_facts_workspace_id ON approved_facts(workspace_id);
CREATE INDEX IF NOT EXISTS ix_approved_facts_fact_key ON approved_facts(fact_key);
CREATE INDEX IF NOT EXISTS ix_approved_facts_fact_type ON approved_facts(fact_type);

CREATE TABLE IF NOT EXISTS scan_runs (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 document_id VARCHAR(36) REFERENCES content_documents(id) ON DELETE SET NULL,
 initiated_by VARCHAR(36) NOT NULL, engine_mode VARCHAR(40) NOT NULL DEFAULT 'deterministic',
 ruleset_fingerprint VARCHAR(64) NOT NULL DEFAULT '', status VARCHAR(20) NOT NULL DEFAULT 'completed',
 total_findings INTEGER NOT NULL DEFAULT 0, verified_evidence INTEGER NOT NULL DEFAULT 0,
 unverifiable_evidence INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
 metrics JSON NOT NULL DEFAULT '{}'::json, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_scan_runs_workspace_id ON scan_runs(workspace_id);
CREATE INDEX IF NOT EXISTS ix_scan_runs_document_id ON scan_runs(document_id);

CREATE TABLE IF NOT EXISTS finding_evidence (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 finding_id VARCHAR(36) NOT NULL REFERENCES review_findings(id) ON DELETE CASCADE,
 scan_run_id VARCHAR(36) REFERENCES scan_runs(id) ON DELETE SET NULL,
 source_kind VARCHAR(40) NOT NULL, source_id VARCHAR(36) NOT NULL, source_version INTEGER,
 source_label VARCHAR(255) NOT NULL, source_quote TEXT NOT NULL, content_quote TEXT NOT NULL,
 locator JSON NOT NULL DEFAULT '{}'::json, verification_status VARCHAR(24) NOT NULL DEFAULT 'grounded',
 match_score FLOAT NOT NULL DEFAULT 1.0, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_finding_evidence_workspace_id ON finding_evidence(workspace_id);
CREATE INDEX IF NOT EXISTS ix_finding_evidence_finding_id ON finding_evidence(finding_id);

CREATE TABLE IF NOT EXISTS policy_simulations (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 rule_id VARCHAR(36) REFERENCES brand_rules(id) ON DELETE SET NULL,
 created_by VARCHAR(36) NOT NULL, rule_code VARCHAR(40) NOT NULL, proposed_pattern TEXT NOT NULL,
 documents_scanned INTEGER NOT NULL DEFAULT 0, documents_affected INTEGER NOT NULL DEFAULT 0,
 matches_found INTEGER NOT NULL DEFAULT 0, sample_matches JSON NOT NULL DEFAULT '[]'::json, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_policy_simulations_workspace_id ON policy_simulations(workspace_id);

CREATE TABLE IF NOT EXISTS evaluation_cases (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, case_code VARCHAR(60) NOT NULL,
 title VARCHAR(180) NOT NULL, content_text TEXT NOT NULL,
 expected_rule_codes JSON NOT NULL DEFAULT '[]'::json, category VARCHAR(50) NOT NULL DEFAULT 'general',
 is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ,
 CONSTRAINT uq_eval_case_code UNIQUE(workspace_id,case_code)
);
CREATE INDEX IF NOT EXISTS ix_evaluation_cases_workspace_id ON evaluation_cases(workspace_id);

CREATE TABLE IF NOT EXISTS evaluation_runs (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, initiated_by VARCHAR(36) NOT NULL,
 case_count INTEGER NOT NULL DEFAULT 0, true_positives INTEGER NOT NULL DEFAULT 0,
 false_positives INTEGER NOT NULL DEFAULT 0, false_negatives INTEGER NOT NULL DEFAULT 0,
 precision FLOAT NOT NULL DEFAULT 0.0, recall FLOAT NOT NULL DEFAULT 0.0, f1_score FLOAT NOT NULL DEFAULT 0.0,
 details JSON NOT NULL DEFAULT '[]'::json, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_workspace_id ON evaluation_runs(workspace_id);

CREATE TABLE IF NOT EXISTS review_tasks (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 document_id VARCHAR(36) NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
 assigned_role VARCHAR(40) NOT NULL, assigned_to VARCHAR(36), reason TEXT NOT NULL,
 priority VARCHAR(20) NOT NULL DEFAULT 'normal', status VARCHAR(20) NOT NULL DEFAULT 'open',
 due_at TIMESTAMPTZ, created_at TIMESTAMPTZ, completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_review_tasks_workspace_id ON review_tasks(workspace_id);
CREATE INDEX IF NOT EXISTS ix_review_tasks_document_id ON review_tasks(document_id);

CREATE TABLE IF NOT EXISTS guideline_chunks (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, source_document VARCHAR(255) NOT NULL,
 page_number INTEGER NOT NULL DEFAULT 1, chunk_index INTEGER NOT NULL DEFAULT 0,
 heading VARCHAR(255) NOT NULL DEFAULT '', source_sha256 VARCHAR(64) NOT NULL DEFAULT '',
 content TEXT NOT NULL, embedding VECTOR(1536), embedding_model VARCHAR(100) NOT NULL DEFAULT 'hashed-token-v1', created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_guideline_chunks_workspace_id ON guideline_chunks(workspace_id);
CREATE INDEX IF NOT EXISTS ix_guideline_chunks_embedding_hnsw ON guideline_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_guideline_chunks_content_fts ON guideline_chunks USING gin (to_tsvector('english',content));
CREATE INDEX IF NOT EXISTS ix_brand_rules_embedding_hnsw ON brand_rules USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS brand_assets (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, name VARCHAR(180) NOT NULL,
 category VARCHAR(40) NOT NULL DEFAULT 'other', filename VARCHAR(255) NOT NULL, stored_path TEXT NOT NULL,
 content_type VARCHAR(160) NOT NULL, size_bytes INTEGER NOT NULL DEFAULT 0, sha256 VARCHAR(64) NOT NULL,
 metadata_json JSON NOT NULL DEFAULT '{}'::json, file_data BYTEA, status VARCHAR(20) NOT NULL DEFAULT 'draft',
 version_number INTEGER NOT NULL DEFAULT 1, created_by VARCHAR(36) NOT NULL,
 approved_by VARCHAR(36), approved_at TIMESTAMPTZ, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_brand_assets_workspace_id ON brand_assets(workspace_id);
CREATE INDEX IF NOT EXISTS ix_brand_assets_sha256 ON brand_assets(sha256);

-- Unauthenticated auth workflow tables are intentionally not tenant-RLS protected:
-- they are accessed by one-time token hash before a workspace context is established.
CREATE TABLE IF NOT EXISTS auth_action_tokens (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80), user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
 email VARCHAR(255) NOT NULL, purpose VARCHAR(30) NOT NULL, token_hash VARCHAR(64) NOT NULL UNIQUE,
 payload JSON NOT NULL DEFAULT '{}'::json, expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_auth_action_tokens_workspace_id ON auth_action_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS ix_auth_action_tokens_user_id ON auth_action_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_auth_action_tokens_email ON auth_action_tokens(email);
CREATE INDEX IF NOT EXISTS ix_auth_action_tokens_purpose ON auth_action_tokens(purpose);

CREATE TABLE IF NOT EXISTS login_attempts (
 id VARCHAR(36) PRIMARY KEY, identity_hash VARCHAR(64) NOT NULL UNIQUE, failures INTEGER NOT NULL DEFAULT 0,
 window_started_at TIMESTAMPTZ NOT NULL, locked_until TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_login_attempts_identity_hash ON login_attempts(identity_hash);

-- Workspace row-level security. Application connections must not be superusers or
-- table owners bypassing FORCE RLS. `users`, `auth_action_tokens` and `login_attempts`
-- are intentionally handled by auth logic before/without a tenant DB context.
DO $$
DECLARE t TEXT;
BEGIN
 FOREACH t IN ARRAY ARRAY[
  'brand_rules','content_documents','audit_events','rule_versions','approved_facts',
  'scan_runs','finding_evidence','policy_simulations','evaluation_cases','evaluation_runs',
  'review_tasks','guideline_chunks','brand_assets'
 ] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('DROP POLICY IF EXISTS contexa_workspace_isolation ON %I',t);
  EXECUTE format('CREATE POLICY contexa_workspace_isolation ON %I USING (workspace_id = current_setting(''app.workspace_id'',true)) WITH CHECK (workspace_id = current_setting(''app.workspace_id'',true))',t);
 END LOOP;
END $$;
ALTER TABLE review_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_findings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS contexa_workspace_isolation ON review_findings;
CREATE POLICY contexa_workspace_isolation ON review_findings
 USING (EXISTS (SELECT 1 FROM content_documents d WHERE d.id = content_id AND d.workspace_id = current_setting('app.workspace_id',true)))
 WITH CHECK (EXISTS (SELECT 1 FROM content_documents d WHERE d.id = content_id AND d.workspace_id = current_setting('app.workspace_id',true)));

COMMIT;
