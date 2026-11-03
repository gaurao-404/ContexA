-- ContexA Round 3 additive PostgreSQL migration.
-- Run after the existing ContexA base schema. The application also creates these
-- tables through SQLAlchemy metadata at startup; this file is a reviewable DBA aid.
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE review_findings
  ADD COLUMN IF NOT EXISTS rule_version_id VARCHAR(36);
CREATE INDEX IF NOT EXISTS ix_review_findings_rule_version_id
  ON review_findings(rule_version_id);

CREATE TABLE IF NOT EXISTS rule_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  rule_id VARCHAR(36) NOT NULL REFERENCES brand_rules(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  snapshot JSON NOT NULL DEFAULT '{}'::json,
  change_note TEXT NOT NULL DEFAULT '',
  created_by VARCHAR(36),
  created_at TIMESTAMPTZ,
  CONSTRAINT uq_rule_version_number UNIQUE(rule_id, version_number)
);
CREATE INDEX IF NOT EXISTS ix_rule_versions_workspace_id ON rule_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_rule_versions_rule_id ON rule_versions(rule_id);

CREATE TABLE IF NOT EXISTS approved_facts (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  fact_key VARCHAR(120) NOT NULL,
  fact_type VARCHAR(40) NOT NULL DEFAULT 'other',
  entity_name VARCHAR(180) NOT NULL DEFAULT '',
  canonical_value TEXT NOT NULL,
  aliases JSON NOT NULL DEFAULT '[]'::json,
  currency VARCHAR(8),
  unit VARCHAR(60),
  source_document VARCHAR(255) NOT NULL,
  source_quote TEXT NOT NULL,
  source_document_id VARCHAR(36) REFERENCES content_documents(id) ON DELETE SET NULL,
  source_verified BOOLEAN NOT NULL DEFAULT FALSE,
  source_page INTEGER,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  version_number INTEGER NOT NULL DEFAULT 1,
  supersedes_id VARCHAR(36) REFERENCES approved_facts(id),
  created_by VARCHAR(36) NOT NULL,
  approved_by VARCHAR(36),
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ,
  CONSTRAINT uq_fact_version UNIQUE(workspace_id, fact_key, version_number)
);
CREATE INDEX IF NOT EXISTS ix_approved_facts_workspace_id ON approved_facts(workspace_id);
CREATE INDEX IF NOT EXISTS ix_approved_facts_fact_key ON approved_facts(fact_key);
CREATE INDEX IF NOT EXISTS ix_approved_facts_fact_type ON approved_facts(fact_type);

CREATE TABLE IF NOT EXISTS scan_runs (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  document_id VARCHAR(36) REFERENCES content_documents(id) ON DELETE SET NULL,
  initiated_by VARCHAR(36) NOT NULL,
  engine_mode VARCHAR(40) NOT NULL DEFAULT 'deterministic',
  ruleset_fingerprint VARCHAR(64) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'completed',
  total_findings INTEGER NOT NULL DEFAULT 0,
  verified_evidence INTEGER NOT NULL DEFAULT 0,
  unverifiable_evidence INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  metrics JSON NOT NULL DEFAULT '{}'::json,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_scan_runs_workspace_id ON scan_runs(workspace_id);
CREATE INDEX IF NOT EXISTS ix_scan_runs_document_id ON scan_runs(document_id);

CREATE TABLE IF NOT EXISTS finding_evidence (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  finding_id VARCHAR(36) NOT NULL REFERENCES review_findings(id) ON DELETE CASCADE,
  scan_run_id VARCHAR(36) REFERENCES scan_runs(id) ON DELETE SET NULL,
  source_kind VARCHAR(40) NOT NULL,
  source_id VARCHAR(36) NOT NULL,
  source_version INTEGER,
  source_label VARCHAR(255) NOT NULL,
  source_quote TEXT NOT NULL,
  content_quote TEXT NOT NULL,
  locator JSON NOT NULL DEFAULT '{}'::json,
  verification_status VARCHAR(24) NOT NULL DEFAULT 'grounded',
  match_score FLOAT NOT NULL DEFAULT 1.0,
  created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_finding_evidence_workspace_id ON finding_evidence(workspace_id);
CREATE INDEX IF NOT EXISTS ix_finding_evidence_finding_id ON finding_evidence(finding_id);

CREATE TABLE IF NOT EXISTS policy_simulations (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  rule_id VARCHAR(36) REFERENCES brand_rules(id) ON DELETE SET NULL,
  created_by VARCHAR(36) NOT NULL,
  rule_code VARCHAR(40) NOT NULL,
  proposed_pattern TEXT NOT NULL,
  documents_scanned INTEGER NOT NULL DEFAULT 0,
  documents_affected INTEGER NOT NULL DEFAULT 0,
  matches_found INTEGER NOT NULL DEFAULT 0,
  sample_matches JSON NOT NULL DEFAULT '[]'::json,
  created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_policy_simulations_workspace_id ON policy_simulations(workspace_id);

CREATE TABLE IF NOT EXISTS evaluation_cases (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  case_code VARCHAR(60) NOT NULL,
  title VARCHAR(180) NOT NULL,
  content_text TEXT NOT NULL,
  expected_rule_codes JSON NOT NULL DEFAULT '[]'::json,
  category VARCHAR(50) NOT NULL DEFAULT 'general',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ,
  CONSTRAINT uq_eval_case_code UNIQUE(workspace_id, case_code)
);
CREATE INDEX IF NOT EXISTS ix_evaluation_cases_workspace_id ON evaluation_cases(workspace_id);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  initiated_by VARCHAR(36) NOT NULL,
  case_count INTEGER NOT NULL DEFAULT 0,
  true_positives INTEGER NOT NULL DEFAULT 0,
  false_positives INTEGER NOT NULL DEFAULT 0,
  false_negatives INTEGER NOT NULL DEFAULT 0,
  precision FLOAT NOT NULL DEFAULT 0.0,
  recall FLOAT NOT NULL DEFAULT 0.0,
  f1_score FLOAT NOT NULL DEFAULT 0.0,
  details JSON NOT NULL DEFAULT '[]'::json,
  created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_workspace_id ON evaluation_runs(workspace_id);

CREATE TABLE IF NOT EXISTS review_tasks (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  document_id VARCHAR(36) NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
  assigned_role VARCHAR(40) NOT NULL,
  assigned_to VARCHAR(36),
  reason TEXT NOT NULL,
  priority VARCHAR(20) NOT NULL DEFAULT 'normal',
  status VARCHAR(20) NOT NULL DEFAULT 'open',
  due_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_review_tasks_workspace_id ON review_tasks(workspace_id);
CREATE INDEX IF NOT EXISTS ix_review_tasks_document_id ON review_tasks(document_id);
