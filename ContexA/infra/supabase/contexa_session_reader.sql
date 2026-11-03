-- Run as the Supabase database owner/postgres role after confirming the target project.
-- This creates a read-only identity for immediate Supabase sign-out revocation checks.
-- The application does NOT receive direct SELECT access to auth.sessions.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'contexa_session_reader') THEN
    CREATE ROLE contexa_session_reader
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS contexa_private AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA contexa_private FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM contexa_session_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE ALL ON TABLES FROM contexa_session_reader;

-- A non-exposed, owner-executed view reveals only the two identifiers required
-- to match a verified JWT's session_id and sub claims.
CREATE OR REPLACE VIEW contexa_private.active_auth_sessions
  WITH (security_barrier = true)
AS
  SELECT id, user_id FROM auth.sessions;
ALTER VIEW contexa_private.active_auth_sessions OWNER TO postgres;
REVOKE ALL ON contexa_private.active_auth_sessions FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA contexa_private TO contexa_session_reader;
GRANT SELECT ON contexa_private.active_auth_sessions TO contexa_session_reader;

-- Set the secret out-of-band (do not commit it):
-- ALTER ROLE contexa_session_reader WITH LOGIN PASSWORD '<strong random password>';
-- Then configure SUPABASE_SESSION_DATABASE_URL using this username and password,
-- the same project's direct database host, and sslmode=require.
