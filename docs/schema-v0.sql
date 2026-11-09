PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

BEGIN;

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'string'
        CHECK (value_type IN ('string', 'integer', 'boolean', 'json')),
    is_secret INTEGER NOT NULL DEFAULT 0 CHECK (is_secret IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0, 1)),
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    ip_address TEXT,
    user_agent TEXT,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_user ON admin_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at, revoked_at);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK (source_type IN ('vpngate_official', 'vpngate_mirror', 'manual_import')),
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    http_status INTEGER,
    content_sha256 TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0 CHECK (accepted IN (0, 1)),
    error_code TEXT,
    error_message TEXT,
    raw_file_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_snapshots_fetched ON source_snapshots(fetched_at DESC);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    source_snapshot_id INTEGER REFERENCES source_snapshots(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('vpngate', 'manual')),
    protocol TEXT NOT NULL CHECK (protocol IN ('openvpn', 'socks5', 'local')),
    display_name TEXT,
    country_code TEXT,
    country_name TEXT,
    city TEXT,
    host TEXT,
    port INTEGER CHECK (port IS NULL OR (port BETWEEN 1 AND 65535)),
    username TEXT,
    secret_ref TEXT,
    config_path TEXT,
    source_latency_ms INTEGER CHECK (source_latency_ms IS NULL OR source_latency_ms >= 0),
    source_speed_bps INTEGER CHECK (source_speed_bps IS NULL OR source_speed_bps >= 0),
    source_uptime_ratio REAL CHECK (source_uptime_ratio IS NULL OR (source_uptime_ratio >= 0 AND source_uptime_ratio <= 1)),
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'queued', 'checking', 'healthy', 'unhealthy', 'blocked', 'expired')),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    is_manually_blocked INTEGER NOT NULL DEFAULT 0 CHECK (is_manually_blocked IN (0, 1)),
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_check_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_nodes_status_enabled ON nodes(status, is_enabled);
CREATE INDEX IF NOT EXISTS idx_nodes_source_country ON nodes(source_type, country_code);
CREATE INDEX IF NOT EXISTS idx_nodes_last_check ON nodes(last_check_at);
CREATE INDEX IF NOT EXISTS idx_nodes_last_seen ON nodes(last_seen_at);

CREATE TABLE IF NOT EXISTS node_metadata (
    node_id INTEGER PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    raw_json TEXT,
    raw_config_sha256 TEXT,
    parser_version TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS node_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    job_id INTEGER,
    check_type TEXT NOT NULL CHECK (check_type IN ('tcp', 'socks5', 'openvpn', 'egress')),
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'timeout', 'cancelled')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    observed_ip TEXT,
    observed_country_code TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_code TEXT,
    error_message TEXT,
    evidence_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_node_checks_node_time ON node_checks(node_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_node_checks_status ON node_checks(status, started_at DESC);

CREATE TABLE IF NOT EXISTS egresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('local', 'socks5', 'vpngate')),
    name TEXT NOT NULL,
    host TEXT,
    port INTEGER CHECK (port IS NULL OR (port BETWEEN 1 AND 65535)),
    username TEXT,
    secret_ref TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    include_in_subscription INTEGER NOT NULL DEFAULT 1 CHECK (include_in_subscription IN (0, 1)),
    last_check_id INTEGER REFERENCES node_checks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (kind = 'local' AND node_id IS NULL) OR
        (kind IN ('socks5', 'vpngate') AND node_id IS NOT NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_egresses_name ON egresses(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_egresses_enabled_priority ON egresses(is_enabled, priority);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL CHECK (job_type IN ('source_refresh', 'node_check', 'egress_check', 'subscription_build', 'cleanup', 'backup')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'abandoned')),
    lock_key TEXT,
    requested_by INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    payload_json TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current >= 0),
    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total >= 0),
    scheduled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_lock
    ON jobs(lock_key)
    WHERE lock_key IS NOT NULL AND status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_jobs_status_schedule ON jobs(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(job_type, created_at DESC);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL CHECK (job_type IN ('source_refresh', 'node_check', 'egress_check', 'cleanup', 'backup')),
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 1800),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    next_run_at TEXT,
    last_run_at TEXT,
    last_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscription_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL CHECK (format IN ('v2ray', 'clash', 'mihomo')),
    scope_json TEXT NOT NULL DEFAULT '{}',
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    expires_at TEXT,
    last_used_at TEXT,
    created_by INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_subscription_tokens_active ON subscription_tokens(is_enabled, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS subscription_builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL REFERENCES subscription_tokens(id) ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format IN ('v2ray', 'clash', 'mihomo')),
    node_count INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT,
    file_path TEXT,
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_subscription_builds_token_time ON subscription_builds(token_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS subscription_access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER REFERENCES subscription_tokens(id) ON DELETE SET NULL,
    format TEXT,
    ip_address TEXT,
    user_agent TEXT,
    http_status INTEGER,
    node_count INTEGER,
    accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_subscription_access_time ON subscription_access_logs(accessed_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    ip_address TEXT,
    detail_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_time ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum TEXT
);

INSERT OR IGNORE INTO app_settings(key, value, value_type, is_secret) VALUES
    ('app_name', 'XNV GateBox Lite', 'string', 0),
    ('node_check_concurrency', '4', 'integer', 0),
    ('node_check_timeout_seconds', '45', 'integer', 0),
    ('source_refresh_interval_seconds', '3600', 'integer', 0),
    ('node_retention_days', '7', 'integer', 0),
    ('subscription_require_healthy', 'true', 'boolean', 0),
    ('allow_local_egress', 'true', 'boolean', 0);

INSERT OR IGNORE INTO schedules(name, job_type, interval_seconds, is_enabled)
VALUES
    ('default-source-refresh', 'source_refresh', 3600, 1),
    ('default-node-check', 'node_check', 3600, 1),
    ('default-cleanup', 'cleanup', 86400, 1);

COMMIT;
