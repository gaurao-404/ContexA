-- ContexA PostgreSQL + pgvector reference schema.
-- The running FastAPI application creates the equivalent tables via SQLAlchemy.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(140) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  role VARCHAR(40) NOT NULL DEFAULT 'Creator',
  password_hash VARCHAR(255) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);

CREATE TABLE IF NOT EXISTS brand_rules (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  code VARCHAR(40) NOT NULL,
  title VARCHAR(180) NOT NULL,
  category VARCHAR(50) NOT NULL,
  rule_clause TEXT NOT NULL,
  source_document VARCHAR(255) NOT NULL,
  pattern TEXT,
  severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical','warning','info')),
  suggested_fix TEXT NOT NULL,
  embedding vector(1536),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  CONSTRAINT uq_workspace_rule_code UNIQUE(workspace_id, code)
);
CREATE INDEX IF NOT EXISTS ix_brand_rules_workspace_id ON brand_rules(workspace_id);
CREATE INDEX IF NOT EXISTS brand_rules_embedding_hnsw ON brand_rules USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS content_documents (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  filename VARCHAR(255) NOT NULL,
  stored_path TEXT NOT NULL,
  content_type VARCHAR(160) NOT NULL,
  content_text TEXT NOT NULL DEFAULT '',
  pages_json JSON NOT NULL DEFAULT '[]'::json,
  page_count INTEGER NOT NULL DEFAULT 1,
  status VARCHAR(40) NOT NULL DEFAULT 'IN_REVIEW',
  compliance_score INTEGER NOT NULL DEFAULT 100,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_content_documents_workspace_id ON content_documents(workspace_id);

CREATE TABLE IF NOT EXISTS review_findings (
  id VARCHAR(36) PRIMARY KEY,
  content_id VARCHAR(36) NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
  rule_id VARCHAR(36) REFERENCES brand_rules(id),
  severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical','warning','info')),
  finding_type VARCHAR(50) NOT NULL,
  flagged_text TEXT NOT NULL,
  page_number INTEGER NOT NULL DEFAULT 1,
  location_bbox JSON,
  reasoning TEXT NOT NULL,
  suggested_fix TEXT NOT NULL,
  applied_text TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','dismissed','edited')),
  dismissal_reason TEXT,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_review_findings_content_id ON review_findings(content_id);
CREATE INDEX IF NOT EXISTS review_findings_content_status ON review_findings(content_id, status, severity);

CREATE TABLE IF NOT EXISTS audit_events (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(80) NOT NULL,
  actor_id VARCHAR(36) NOT NULL,
  actor_name VARCHAR(140) NOT NULL,
  action VARCHAR(100) NOT NULL,
  entity_type VARCHAR(60) NOT NULL,
  entity_id VARCHAR(36) NOT NULL,
  detail JSON NOT NULL DEFAULT '{}'::json,
  created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_audit_events_workspace_id ON audit_events(workspace_id);
