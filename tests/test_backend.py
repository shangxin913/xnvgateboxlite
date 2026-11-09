"""All database/key/credential reads in this module are isolated tmp_path data."""
import base64
import json
import logging
import stat
from urllib.parse import unquote, urlsplit

from fastapi.testclient import TestClient
import pytest
import yaml

from app import create_app
from app.cli import bootstrap_admin, main as cli_main
from app.core.config import ROOT
from app.core.security import COOKIE_NAME, token_hash
from app.services.checker import UnavailableNodeChecker
from app.services.executor import UnavailableEgressExecutor
from app.services.source_fetcher import VPNGateSourceFetcher

INITIAL = "Initial-Testing-Password!"
CHANGED = "Changed-Testing-Password!"


def log_in(client, password=INITIAL):
    result = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert result.status_code == 200, result.text
    return result.json()["csrf_token"]


@pytest.fixture
def initial(tmp_path):
    app = create_app(tmp_path / "data", cookie_secure=False)
    bootstrap_admin(tmp_path / "data", "admin", INITIAL)
    with TestClient(app) as client:
        yield client, app, tmp_path


@pytest.fixture
def ready(initial):
    client, app, directory = initial
    csrf = log_in(client)
    result = client.post("/api/auth/password", headers={"X-CSRF-Token": csrf}, json={"current_password": INITIAL, "new_password": CHANGED})
    assert result.status_code == 200, result.text
    csrf = log_in(client, CHANGED)
    client.headers["X-CSRF-Token"] = csrf
    return client, app, directory


def add_node(client, **changes):
    body = {"display_name": "东京节点", "host": "proxy.example.com", "port": 1080, "username": "alice", "password": "socks-secret:测试@#", "country_code": "JP", "is_enabled": True}
    body.update(changes)
    response = client.post("/api/nodes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def add_subscription(client, **changes):
    body = {"name": "私密订阅", "require_healthy": False, "country_codes": []}
    body.update(changes)
    result = client.post("/api/subscriptions", json=body)
    assert result.status_code == 201, result.text
    return result.json()


def egress_for(client, node_id):
    return next(e for e in client.get("/api/egresses").json()["items"] if e["node_id"] == node_id)


def test_empty_runtime_has_no_default_admin(tmp_path):
    app = create_app(tmp_path / "empty", cookie_secure=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/dashboard").status_code == 401
        assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
        with app.state.db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 0
            local = conn.execute("SELECT * FROM egresses").fetchone()
            assert local["kind"] == "local" and local["is_enabled"] == 0
            assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_forced_password_csrf_and_logout(initial):
    client, app, _ = initial
    assert client.get("/api/auth/me").status_code == 401
    csrf = log_in(client)
    session = client.cookies.get(COOKIE_NAME)
    assert client.get("/api/auth/me").json()["user"]["must_change_password"] is True
    assert client.get("/api/dashboard").json()["detail"] == "请先修改初始密码"
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/password", json={"current_password": INITIAL, "new_password": CHANGED}).status_code == 403
    assert client.post("/api/auth/password", headers={"X-CSRF-Token": "wrong"}, json={"current_password": INITIAL, "new_password": CHANGED}).status_code == 403
    csrf2 = log_in(client)
    second_session = client.cookies.get(COOKIE_NAME)
    assert csrf2 != csrf
    assert client.post("/api/auth/password", headers={"X-CSRF-Token": csrf}, json={"current_password": INITIAL, "new_password": CHANGED}).status_code == 403
    result = client.post("/api/auth/password", headers={"X-CSRF-Token": csrf2}, json={"current_password": INITIAL, "new_password": CHANGED})
    assert result.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    for old_token in (session, second_session):
        assert client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={old_token}"}).status_code == 401
    csrf = log_in(client, CHANGED)
    assert client.get("/api/auth/me").json()["user"]["must_change_password"] is False
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401
    with app.state.db.connection() as conn:
        row = conn.execute("SELECT password_hash FROM admin_users").fetchone()
        assert row[0].startswith("$argon2id$") and CHANGED not in row[0]


def test_session_hash_expiry_and_csrf_binding(ready):
    client, app, _ = ready
    token = client.cookies.get(COOKIE_NAME)
    with app.state.db.connection() as conn:
        row = conn.execute("SELECT * FROM admin_sessions WHERE revoked_at IS NULL").fetchone()
        assert row["token_hash"] == token_hash(token)
        assert token not in json.dumps(dict(row))
        conn.execute("UPDATE admin_sessions SET expires_at='2000-01-01 00:00:00' WHERE id=?", (row["id"],))
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit(initial):
    client, _, _ = initial
    for _ in range(5):
        result = client.post("/api/auth/login", json={"username": "admin", "password": "incorrect-password"})
        assert result.status_code == 401
    limited = client.post("/api/auth/login", json={"username": "admin", "password": INITIAL})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "300"


def test_secure_cookie_and_explicit_local_override(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEBOX_COOKIE_SECURE", raising=False)
    app = create_app(tmp_path / "secure")
    bootstrap_admin(tmp_path / "secure", "admin", INITIAL)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": INITIAL})
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=none" in cookie
        assert client.get("/api/auth/me").status_code == 200
    local = create_app(tmp_path / "local", cookie_secure=False)
    bootstrap_admin(tmp_path / "local", "admin", INITIAL)
    with TestClient(local) as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": INITIAL})
        cookie = response.headers["set-cookie"].lower()
        assert "samesite=lax" in cookie and "secure" not in cookie
        assert client.get("/api/auth/me").status_code == 200


def test_storage_permissions_and_repeat_initialize(ready):
    client, app, _ = ready
    node = add_node(client)
    assert stat.S_IMODE(app.state.settings.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((app.state.settings.data_dir / "master.key").stat().st_mode) == 0o600
    assert stat.S_IMODE(app.state.db.path.stat().st_mode) == 0o600
    app.state.db.initialize()
    with app.state.db.connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(*) FROM egresses WHERE kind='local'").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM nodes").fetchone()[0] == node["id"]


def test_node_crud_encryption_and_no_leak(ready):
    client, app, _ = ready
    node = add_node(client)
    assert node["status"] == "new" and node["has_password"] is True
    assert node["last_check_at"] is None and node["latency_ms"] is None
    for path in ("/api/nodes", f"/api/nodes/{node['id']}", "/api/dashboard", "/api/egresses", "/api/audit"):
        result = client.get(path)
        assert result.status_code == 200
        assert "socks-secret" not in result.text and "secret_ref" not in result.text and "ciphertext" not in result.text
        assert "no-store" in result.headers["cache-control"]
    egress = egress_for(client, node["id"])
    assert egress["kind"] == "socks5"
    with app.state.db.connection() as conn:
        secret = conn.execute("SELECT * FROM secrets").fetchone()
        assert "socks-secret" not in secret["ciphertext"]
        assert app.state.security.decrypt(secret["ciphertext"]) == "socks-secret:测试@#"
        conn.execute("UPDATE nodes SET status='healthy',last_check_at=CURRENT_TIMESTAMP,last_success_at=CURRENT_TIMESTAMP,latency_ms=10 WHERE id=?", (node["id"],))
    response = client.patch(f"/api/nodes/{node['id']}", json={"notes": "备注", "is_enabled": False, "password": "   "})
    assert response.status_code == 200 and response.json()["status"] == "healthy"
    assert response.json()["has_password"] is True
    response = client.patch(f"/api/nodes/{node['id']}", json={"host": "changed.example.com", "password": ""})
    assert response.status_code == 200 and response.json()["status"] == "new"
    assert response.json()["last_check_at"] is None and response.json()["last_success_at"] is None and response.json()["latency_ms"] is None
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 1
    response = client.patch(f"/api/nodes/{node['id']}", json={"password": "Replacement:秘密"})
    assert response.status_code == 200
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 1
        assert app.state.security.decrypt(conn.execute("SELECT ciphertext FROM secrets").fetchone()[0]) == "Replacement:秘密"
    assert client.delete(f"/api/nodes/{node['id']}").json() == {"ok": True}
    assert client.get(f"/api/nodes/{node['id']}").status_code == 404
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM egresses WHERE node_id IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_node_clear_auth_and_pair_validation(ready):
    client, app, _ = ready
    node = add_node(client)
    assert client.patch(f"/api/nodes/{node['id']}", json={"username": None}).status_code == 422
    assert client.patch(f"/api/nodes/{node['id']}", json={"clear_auth": True, "password": "not-empty"}).status_code == 422
    result = client.patch(f"/api/nodes/{node['id']}", json={"clear_auth": True})
    assert result.json()["has_password"] is False and result.json()["username"] is None
    assert client.patch(f"/api/nodes/{node['id']}", json={"username": "new-user"}).status_code == 422
    result = client.patch(f"/api/nodes/{node['id']}", json={"username": "new-user", "password": "New:密码"})
    assert result.status_code == 200 and result.json()["has_password"] is True
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 1


@pytest.mark.parametrize("changes", [
    {"host": "https://example.com"}, {"host": "example.com/path"}, {"host": "foo\nbar"}, {"host": "999.999.999.999"},
    {"host": "[example.com]"}, {"host": "bad_label.example"}, {"host": "fe80::1%eth0"},
    {"host": "testserver", "port": 80}, {"host": "127.0.0.1", "port": 80},
    {"port": 0}, {"port": 65536}, {"port": True}, {"display_name": " "}, {"display_name": "x" * 101},
    {"display_name": "bad\nname"}, {"country_code": "jp"}, {"notes": "x" * 1001},
    {"username": "has:colon"}, {"username": "one", "password": None}, {"username": None, "password": "secret"},
])
def test_node_input_validation(ready, changes):
    client, _, _ = ready
    body = {"display_name": "验证节点", "host": "valid.example", "port": 1080, "username": None, "password": None}
    body.update(changes)
    assert client.post("/api/nodes", json=body).status_code == 422


def test_validation_errors_never_echo_password(ready):
    client, _, _ = ready
    secret = "PRIVATE" * 200
    result = client.post("/api/nodes", json={"display_name": "验证", "host": "valid.example", "port": 1080, "password": secret})
    assert result.status_code == 422 and secret not in result.text and '"input"' not in result.text
    admin_secret = "ADMINPRIVATE" * 20
    result = client.post("/api/auth/password", json={"current_password": CHANGED, "new_password": admin_secret})
    assert result.status_code == 422 and admin_secret not in result.text


def test_fingerprint_canonical_unique_and_transaction_rollback(ready):
    client, app, _ = ready
    first = add_node(client, host="[2001:DB8:0:0::1]")
    assert first["host"] == "2001:db8::1"
    duplicate = client.post("/api/nodes", json={"display_name": "重复", "host": "2001:db8::1", "port": 1080, "username": "alice", "password": "other-secret"})
    assert duplicate.status_code == 409
    second = add_node(client, host="PROXY.Example.COM.", username=None, password=None)
    assert second["host"] == "proxy.example.com"
    third = add_node(client, host="例子.测试", username=None, password=None)
    assert third["host"].startswith("xn--")
    conflict = client.patch(f"/api/nodes/{second['id']}", json={"host": first["host"], "username": "alice", "password": "new-secret"})
    assert conflict.status_code == 409
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM egresses").fetchone()[0] == 4
    assert client.get("/api/nodes?q=东京&page_size=1").json()["total"] == 3
    assert len(client.get("/api/nodes?page_size=1&page=2").json()["items"]) == 1
    assert client.get("/api/nodes?status=healthy").json()["total"] == 0
    assert client.get("/api/nodes?protocol=openvpn").json()["total"] == 0


def test_subscriptions_special_characters_ipv6_and_yaml(ready):
    client, app, _ = ready
    username, password = "用 户@/#?%", "pa:ss@/#?%\n'\"密码"
    name = "节点 / #? ' \" 东京"
    node = add_node(client, display_name=name, host="[2001:DB8::123]", username=username, password=password)
    subscription = add_subscription(client)
    assert subscription["node_count"] == 1
    listed = client.get("/api/subscriptions")
    assert subscription["token"] not in listed.text and "token_hash" not in listed.text
    with app.state.db.connection() as conn:
        row = conn.execute("SELECT * FROM subscription_tokens").fetchone()
        assert row["token_hash"] == token_hash(subscription["token"])
        assert subscription["token"] not in json.dumps(dict(row))
    uri_preview = client.get(f"/api/subscriptions/{subscription['id']}/preview?format=v2ray").json()
    uri = uri_preview["content"]
    parts = urlsplit(uri)
    assert parts.hostname == "2001:db8::123" and parts.port == 1080
    assert unquote(parts.fragment) == name
    encoded_credentials = parts.netloc.split("@", 1)[0]
    decoded = base64.urlsafe_b64decode(encoded_credentials + "=" * (-len(encoded_credentials) % 4)).decode()
    assert decoded == username + ":" + password
    with TestClient(app) as public:
        response = public.get(subscription["paths"]["v2ray"])
        assert response.status_code == 200
        assert base64.b64decode(response.text).decode() == uri
        assert "no-store" in response.headers["cache-control"]
        for format_name in ("clash", "mihomo"):
            response = public.get(subscription["paths"][format_name])
            document = yaml.safe_load(response.text)
            proxy = document["proxies"][0]
            assert proxy["name"] == name and proxy["server"] == "2001:db8::123"
            assert proxy["username"] == username and proxy["password"] == password
            assert proxy["udp"] is False and "DIRECT" not in document["proxy-groups"][0]["proxies"]
    preview = client.get(f"/api/subscriptions/{subscription['id']}/preview?format=clash")
    assert preview.json()["node_count"] == 1 and preview.json()["warnings"]
    assert "no-store" in preview.headers["cache-control"]
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT last_used_at FROM subscription_tokens").fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM subscription_access_logs").fetchone()[0] == 3


def test_subscription_filter_enable_healthy_country_and_revoke(ready):
    client, app, _ = ready
    node = add_node(client)
    egress = egress_for(client, node["id"])
    regular = add_subscription(client)
    healthy = add_subscription(client, require_healthy=True)
    country_filtered = add_subscription(client, country_codes=["US"])
    assert client.get(f"/api/subscriptions/{healthy['id']}/preview").json()["node_count"] == 0
    assert client.get(f"/api/subscriptions/{country_filtered['id']}/preview").json()["node_count"] == 0
    with app.state.db.connection() as conn:
        conn.execute("UPDATE nodes SET status='healthy' WHERE id=?", (node["id"],))
    assert client.get(f"/api/subscriptions/{healthy['id']}/preview").json()["node_count"] == 1
    for target, key in ((f"/api/nodes/{node['id']}", "is_enabled"), (f"/api/egresses/{egress['id']}", "is_enabled"), (f"/api/egresses/{egress['id']}", "include_in_subscription")):
        assert client.patch(target, json={key: False}).status_code == 200
        preview = client.get(f"/api/subscriptions/{regular['id']}/preview").json()
        assert preview["node_count"] == 0
        document = yaml.safe_load(preview["content"])
        assert document["proxies"] == [] and document["proxy-groups"][0]["proxies"] == ["REJECT"]
        assert "DIRECT" not in preview["content"]
        assert client.patch(target, json={key: True}).status_code == 200
    assert client.delete(f"/api/subscriptions/{regular['id']}").status_code == 200
    assert client.get(regular["paths"]["clash"]).status_code == 404
    assert client.get(f"/api/subscriptions/{regular['id']}/preview").status_code == 404
    assert client.get("/sub/" + "x" * 64 + "/clash").status_code == 404
    assert client.get(healthy["paths"]["clash"].replace("/clash", "/invalid")).status_code == 404
    with app.state.db.connection() as conn:
        conn.execute("UPDATE subscription_tokens SET expires_at='2000-01-01 00:00:00' WHERE id=?", (healthy["id"],))
    assert client.get(healthy["paths"]["clash"]).status_code == 404


def test_unauthenticated_socks_and_duplicate_yaml_names(ready):
    client, _, _ = ready
    add_node(client, username=None, password=None, display_name="重复名字")
    add_node(client, host="other.example", username=None, password=None, display_name="重复名字")
    subscription = add_subscription(client)
    result = client.get(f"/api/subscriptions/{subscription['id']}/preview?format=v2ray").json()["content"]
    assert all("@" not in urlsplit(line).netloc for line in result.splitlines())
    result = yaml.safe_load(client.get(subscription["paths"]["clash"]).text)
    names = [p["name"] for p in result["proxies"]]
    assert len(set(names)) == 2
    assert all("password" not in p and "username" not in p for p in result["proxies"])


def test_default_egress_and_delete_cleanup(ready):
    client, app, _ = ready
    first = add_node(client)
    second = add_node(client, host="second.example")
    e1, e2 = egress_for(client, first["id"]), egress_for(client, second["id"])
    local = next(e for e in client.get("/api/egresses").json()["items"] if e["kind"] == "local")
    assert local["status"] == "unprovisioned" and local["is_enabled"] is False
    assert client.post(f"/api/egresses/{local['id']}/default").status_code == 409
    assert client.post(f"/api/egresses/{e1['id']}/default").status_code == 200
    assert client.post(f"/api/egresses/{e2['id']}/default").status_code == 200
    items = client.get("/api/egresses").json()["items"]
    assert sum(e["is_default"] for e in items) == 1
    assert client.patch(f"/api/egresses/{e2['id']}", json={"is_enabled": False}).status_code == 200
    assert client.get("/api/dashboard").json()["runtime"]["default_egress_id"] is None
    assert client.post(f"/api/egresses/{e1['id']}/default").status_code == 200
    assert client.delete(f"/api/nodes/{first['id']}").status_code == 200
    assert client.get("/api/dashboard").json()["runtime"]["default_egress_id"] is None
    assert client.patch(f"/api/egresses/{local['id']}", json={"is_enabled": True, "include_in_subscription": True}).status_code == 200
    assert client.post(f"/api/egresses/{local['id']}/default").status_code == 200
    subscription = add_subscription(client)
    assert subscription["node_count"] == 0  # second egress disabled; local never emitted
    with app.state.db.connection() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert client.patch(f"/api/egresses/{e2['id']}", json={"priority": 1001}).status_code == 422


@pytest.mark.parametrize("field,invalid,valid", [
    ("node_check_concurrency", 0, 16), ("node_check_concurrency", 17, 1),
    ("node_check_timeout_seconds", 4, 120), ("node_check_timeout_seconds", 121, 5),
    ("source_refresh_interval_seconds", 1799, 86400), ("source_refresh_interval_seconds", 86401, 1800),
    ("subscription_require_healthy", "true", True),
])
def test_setting_ranges(ready, field, invalid, valid):
    client, _, _ = ready
    previous = client.get("/api/settings").json()
    assert client.patch("/api/settings", json={field: invalid}).status_code == 422
    assert client.get("/api/settings").json() == previous
    result = client.patch("/api/settings", json={field: valid})
    assert result.status_code == 200 and result.json()[field] == valid
    assert client.patch("/api/settings", json={field: None}).status_code == 422


def test_framework_501_and_real_empty_counts(ready):
    client, _, _ = ready
    node = add_node(client)
    egress = egress_for(client, node["id"])
    assert client.get("/api/jobs").json() == {"items": []}
    schedules = client.get("/api/schedules").json()["items"]
    assert len(schedules) == 3 and all(not item["is_enabled"] for item in schedules)
    schedule_id = schedules[0]["id"]
    assert client.patch(f"/api/schedules/{schedule_id}", json={"interval_seconds": 1799}).status_code == 422
    assert client.patch(f"/api/schedules/{schedule_id}", json={"interval_seconds": 7200}).json()["interval_seconds"] == 7200
    assert client.patch(f"/api/schedules/{schedule_id}", json={"interval_seconds": 8000, "is_enabled": True}).status_code == 501
    assert client.get("/api/schedules").json()["items"][0]["interval_seconds"] == 7200
    for path in (f"/api/nodes/{node['id']}/check", "/api/nodes/check", "/api/nodes/check-all", f"/api/egresses/{egress['id']}/check", "/api/pool/refresh", "/api/sources/refresh", "/api/jobs", "/api/jobs/run", f"/api/schedules/{schedule_id}/run", "/api/executor/apply"):
        assert client.post(path).status_code == 501, path
    assert client.put(f"/api/nodes/{node['id']}/check").status_code == 501
    assert client.get("/api/jobs").json() == {"items": []}
    pool = client.get("/api/pool/summary").json()
    assert pool["total"] == 0 and pool["available"] is False and pool["last_fetch_at"] is None
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["nodes_total"] == 1 and dashboard["stats"]["nodes_healthy"] == 0
    assert not any(dashboard["runtime"][name] for name in ("executor_ready", "checker_ready", "vpngate_ready"))
    with pytest.raises(NotImplementedError):
        VPNGateSourceFetcher().fetch("https://source.invalid")
    with pytest.raises(NotImplementedError):
        UnavailableNodeChecker().check({}, timeout_seconds=45)
    with pytest.raises(NotImplementedError):
        UnavailableEgressExecutor().apply([], None)


def test_csrf_all_writes_no_store_and_unknown_routes(ready):
    client, _, _ = ready
    node = add_node(client)
    csrf = client.headers.pop("X-CSRF-Token")
    for method, path, body in (("POST", "/api/subscriptions", {"name": "bad"}), ("PATCH", "/api/settings", {"node_check_concurrency": 3}), ("DELETE", f"/api/nodes/{node['id']}", None), ("POST", "/api/pool/refresh", None)):
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method, path, **kwargs)
        assert response.status_code == 403 and "no-store" in response.headers["cache-control"]
    client.headers["X-CSRF-Token"] = csrf
    assert client.get("/api/unknown").status_code == 404
    assert "text/html" not in client.get("/api/unknown").headers["content-type"]
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/static/../plan.md").status_code == 404
    assert client.get("/static/%2e%2e/%2e%2e/migrations/001_initial.sql").status_code == 404
    for path in ("/", "/login", "/nodes", "/egresses", "/subscriptions", "/tasks", "/settings", "/pool"):
        response = client.get(path)
        assert response.status_code == (200 if (ROOT / "web/index.html").exists() else 503)
        assert "x-frame-options" not in response.headers
    manifest = client.get("/manus-routes.json")
    assert manifest.status_code == (200 if (ROOT / "web/manus-routes.json").exists() else 404)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "secret URL", (), None)
    assert logging.getLogger("uvicorn.access").filter(record) is False


def test_cli_private_output_and_refuse_existing(tmp_path, capsys):
    data, output = tmp_path / "cli-data", tmp_path / "initial-private.json"
    assert cli_main(["init", "--username", "admin", "--data-dir", str(data), "--output", str(output)]) == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    credentials = json.loads(output.read_text())
    assert len(credentials["password"]) >= 32 and credentials["must_change_password"] is True
    captured = capsys.readouterr()
    assert credentials["password"] not in captured.out and credentials["password"] not in captured.err
    app = create_app(data, cookie_secure=False)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"username": "admin", "password": credentials["password"]}).status_code == 200
    original = output.read_text()
    assert cli_main(["init", "--data-dir", str(data), "--output", str(output)]) == 1
    assert output.read_text() == original
    duplicate = tmp_path / "duplicate-private.json"
    assert cli_main(["init", "--data-dir", str(data), "--output", str(duplicate)]) == 1
    assert not duplicate.exists()
    with pytest.raises(ValueError, match="已存在"):
        bootstrap_admin(data, "second-admin", INITIAL)
    with pytest.raises(SystemExit):
        cli_main(["init", "--data-dir", str(data), "--output", "relative-file"])


def test_connections_close_and_lost_key_refuses_recreation(ready):
    import sqlite3
    client, app, _ = ready
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    key_path = app.state.settings.data_dir / "master.key"
    key_path.unlink()
    with pytest.raises(RuntimeError, match="主密钥丢失"):
        create_app(app.state.settings.data_dir, cookie_secure=False)
    assert not key_path.exists()


def test_subscription_failure_is_private_and_logs_no_bearer(ready, caplog):
    client, app, _ = ready
    add_node(client)
    subscription = add_subscription(client)
    with app.state.db.connection() as conn:
        conn.execute("UPDATE secrets SET ciphertext='invalid-ciphertext'")
    response = client.get(subscription["paths"]["clash"])
    assert response.status_code == 500
    assert "no-store" in response.headers["cache-control"]
    assert subscription["token"] not in response.text and "invalid-ciphertext" not in response.text
    assert subscription["token"] not in caplog.text and "invalid-ciphertext" not in caplog.text
