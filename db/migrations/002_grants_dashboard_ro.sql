-- Read-only grants for the Streamlit dashboard (phase 5). The role itself
-- is created by db/init/01_bootstrap.sh (it needs a password from env).
-- If the dashboard is ever compromised, all it can do is SELECT.
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;
