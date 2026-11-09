-- SQLite 3 / UTC timestamps. Connection must enable foreign_keys and WAL.
BEGIN;
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('string','integer','boolean','json')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0,1)),
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE admin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sessions_expiry ON admin_sessions(expires_at,revoked_at);
CREATE TABLE secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE source_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK (source_type IN ('vpngate_official','vpngate_mirror','manual_import')),
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    http_status INTEGER,
    content_sha256 TEXT,
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count>=0),
    accepted INTEGER NOT NULL DEFAULT 0 CHECK (accepted IN (0,1)),
    error_code TEXT,
    error_message TEXT,
    raw_file_path TEXT
);
CREATE INDEX idx_snapshots_time ON source_snapshots(fetched_at DESC);
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    source_snapshot_id INTEGER REFERENCES source_snapshots(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('vpngate','manual')),
    protocol TEXT NOT NULL CHECK (protocol IN ('openvpn','socks5')),
    display_name TEXT NOT NULL,
    country_code TEXT,
    city TEXT,
    host TEXT NOT NULL,
    port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
    username TEXT,
    secret_ref INTEGER REFERENCES secrets(id) ON DELETE RESTRICT,
    config_path TEXT,
    notes TEXT NOT NULL DEFAULT '',
    source_latency_ms INTEGER CHECK (source_latency_ms IS NULL OR source_latency_ms>=0),
    source_speed_bps INTEGER CHECK (source_speed_bps IS NULL OR source_speed_bps>=0),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','queued','checking','healthy','unhealthy','blocked','expired')),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_check_at TEXT,
    last_success_at TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms>=0),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures>=0),
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((source_type='manual' AND protocol='socks5') OR (source_type='vpngate' AND protocol='openvpn')),
    CHECK ((username IS NULL AND secret_ref IS NULL) OR (username IS NOT NULL AND secret_ref IS NOT NULL))
);
CREATE INDEX idx_nodes_status ON nodes(status,is_enabled);
CREATE INDEX idx_nodes_country ON nodes(source_type,country_code);
CREATE INDEX idx_nodes_check ON nodes(last_check_at);
CREATE TABLE node_metadata (
    node_id INTEGER PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    raw_json TEXT,
    raw_config_sha256 TEXT,
    parser_version TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL CHECK (job_type IN ('source_refresh','node_check','egress_check','subscription_build','cleanup','backup')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled','abandoned')),
    lock_key TEXT,
    requested_by INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    payload_json TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current>=0),
    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total>=0),
    scheduled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_jobs_lock ON jobs(lock_key) WHERE lock_key IS NOT NULL AND status IN ('queued','running');
CREATE INDEX idx_jobs_queue ON jobs(status,scheduled_at);
CREATE TABLE node_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    check_type TEXT NOT NULL CHECK (check_type IN ('tcp','socks5','openvpn','egress')),
    status TEXT NOT NULL CHECK (status IN ('running','passed','failed','timeout','cancelled')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms>=0),
    observed_ip TEXT,
    observed_country_code TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms>=0),
    error_code TEXT,
    error_message TEXT,
    evidence_json TEXT
);
CREATE INDEX idx_checks_node_time ON node_checks(node_id,started_at DESC);
CREATE TABLE egresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER UNIQUE REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('local','socks5','vpngate')),
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100 CHECK (priority BETWEEN 0 AND 1000),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    include_in_subscription INTEGER NOT NULL DEFAULT 1 CHECK (include_in_subscription IN (0,1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    last_check_id INTEGER REFERENCES node_checks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((kind='local' AND node_id IS NULL) OR (kind IN ('socks5','vpngate') AND node_id IS NOT NULL)),
    CHECK (is_default=0 OR is_enabled=1)
);
CREATE UNIQUE INDEX uq_egress_local ON egresses(kind) WHERE kind='local';
CREATE UNIQUE INDEX uq_egress_default ON egresses(is_default) WHERE is_default=1;
CREATE INDEX idx_egress_order ON egresses(is_enabled,priority);
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL CHECK (job_type IN ('source_refresh','node_check','egress_check','cleanup','backup')),
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds>=1800),
    is_enabled INTEGER NOT NULL DEFAULT 0 CHECK (is_enabled IN (0,1)),
    next_run_at TEXT,
    last_run_at TEXT,
    last_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE subscription_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope_json TEXT NOT NULL DEFAULT '{}',
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    expires_at TEXT,
    last_used_at TEXT,
    created_by INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT
);
CREATE TABLE subscription_builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL REFERENCES subscription_tokens(id) ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format IN ('v2ray','clash','mihomo')),
    node_count INTEGER NOT NULL DEFAULT 0 CHECK (node_count>=0),
    content_sha256 TEXT,
    file_path TEXT,
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE subscription_access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER REFERENCES subscription_tokens(id) ON DELETE SET NULL,
    format TEXT,
    http_status INTEGER,
    node_count INTEGER,
    accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sub_access_time ON subscription_access_logs(accessed_at DESC);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    detail_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_time ON audit_logs(created_at DESC);
INSERT INTO app_settings(key,value,value_type) VALUES
 ('node_check_concurrency','4','integer'),
 ('node_check_timeout_seconds','45','integer'),
 ('subscription_require_healthy','false','boolean'),
 ('source_refresh_interval_seconds','3600','integer');
INSERT INTO egresses(kind,name,is_enabled,include_in_subscription,priority) VALUES ('local','VPS 本机直出',0,0,0);
INSERT INTO schedules(name,job_type,interval_seconds) VALUES
 ('VPN Gate 来源刷新','source_refresh',3600),
 ('节点链路检测','node_check',3600),
 ('历史记录清理','cleanup',86400);
INSERT INTO schema_migrations(version) VALUES (1);
COMMIT;
