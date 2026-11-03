-- ContexA Round 4 additive PostgreSQL migration: collaboration, compliance history, hot-path indexes.
-- Mirrors migration 2026_11_01_04_collaboration_analytics_indexes (the app also applies it automatically).
-- Run as a migration role before the application role serves traffic.
BEGIN;

CREATE TABLE IF NOT EXISTS notifications (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, user_id VARCHAR(36) NOT NULL,
 kind VARCHAR(40) NOT NULL, title VARCHAR(200) NOT NULL, body TEXT NOT NULL DEFAULT '',
 entity_type VARCHAR(40), entity_id VARCHAR(64), actor_id VARCHAR(36),
 read_at TIMESTAMPTZ, created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_notifications_workspace_id ON notifications(workspace_id);
CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications(created_at);

CREATE TABLE IF NOT EXISTS comments (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL,
 entity_type VARCHAR(20) NOT NULL, entity_id VARCHAR(36) NOT NULL, parent_id VARCHAR(36),
 author_id VARCHAR(36) NOT NULL, author_name VARCHAR(140) NOT NULL, body TEXT NOT NULL,
 mentions JSON NOT NULL DEFAULT '[]'::json, resolved BOOLEAN NOT NULL DEFAULT FALSE,
 is_deleted BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ, edited_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_comments_workspace_id ON comments(workspace_id);
CREATE INDEX IF NOT EXISTS ix_comments_entity_id ON comments(entity_id);
CREATE INDEX IF NOT EXISTS ix_comments_parent_id ON comments(parent_id);

CREATE TABLE IF NOT EXISTS compliance_snapshots (
 id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(80) NOT NULL, snapshot_date VARCHAR(10) NOT NULL,
 integrity_score INTEGER NOT NULL DEFAULT 100, total_documents INTEGER NOT NULL DEFAULT 0,
 publish_ready INTEGER NOT NULL DEFAULT 0, open_findings INTEGER NOT NULL DEFAULT 0,
 critical_findings INTEGER NOT NULL DEFAULT 0, warning_findings INTEGER NOT NULL DEFAULT 0,
 open_tasks INTEGER NOT NULL DEFAULT 0, active_rules INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ,
 CONSTRAINT uq_snapshot_workspace_day UNIQUE (workspace_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS ix_compliance_snapshots_workspace_id ON compliance_snapshots(workspace_id);

-- Hot-path composite indexes
CREATE INDEX IF NOT EXISTS ix_docs_ws_status_updated ON content_documents (workspace_id, status, updated_at);
CREATE INDEX IF NOT EXISTS ix_findings_content_status_sev ON review_findings (content_id, status, severity);
CREATE INDEX IF NOT EXISTS ix_audit_ws_created ON audit_events (workspace_id, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_ws_entity ON audit_events (workspace_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_tasks_ws_status ON review_tasks (workspace_id, status, priority);
CREATE INDEX IF NOT EXISTS ix_notifications_user_unread ON notifications (user_id, read_at, created_at);
CREATE INDEX IF NOT EXISTS ix_comments_entity ON comments (workspace_id, entity_type, entity_id, created_at);

-- Tenant isolation (same policy as every other workspace-owned table)
DO $$
DECLARE t TEXT;
BEGIN
 FOREACH t IN ARRAY ARRAY['notifications','comments','compliance_snapshots'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('DROP POLICY IF EXISTS contexa_workspace_isolation ON %I',t);
  EXECUTE format('CREATE POLICY contexa_workspace_isolation ON %I USING (workspace_id = current_setting(''app.workspace_id'',true)) WITH CHECK (workspace_id = current_setting(''app.workspace_id'',true))',t);
 END LOOP;
END $$;

INSERT INTO schema_migrations (version, applied_at) VALUES ('2026_11_01_04_collaboration_analytics_indexes', now())
ON CONFLICT (version) DO NOTHING;
COMMIT;
