import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.db import audit, utc_now
from .models import NodeCreate, NodePatch, find_node, fingerprint, node_view, nonnull, reject_self_reference

router = APIRouter(prefix="/api/nodes")


def conflict():
    return HTTPException(409, "相同协议、地址、端口和用户名的节点已存在")


@router.get("")
def list_nodes(request: Request, q: str = Query(default="", max_length=100),
               protocol: Literal["", "socks5", "openvpn"] = "",
               status: Literal["", "new", "queued", "checking", "healthy", "unhealthy", "blocked", "expired"] = "",
               page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    clauses, values = [], []
    if q:
        clauses.append("(display_name LIKE ? ESCAPE '\\' OR host LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')")
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        values.extend([pattern] * 3)
    if protocol:
        clauses.append("protocol=?")
        values.append(protocol)
    if status:
        clauses.append("status=?")
        values.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with request.app.state.db.connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM nodes" + where, values).fetchone()[0]
        items = conn.execute("SELECT * FROM nodes" + where + " ORDER BY id DESC LIMIT ? OFFSET ?", values + [page_size, (page - 1) * page_size]).fetchall()
    return {"items": [node_view(row) for row in items], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_node(body: NodeCreate, request: Request):
    data = body.model_dump()
    reject_self_reference(request, data["host"], data["port"])
    username = data["username"]
    password = data["password"] or None
    if password is not None and not password.strip():
        password = None
    if bool(username) != bool(password):
        raise HTTPException(422, "认证用户名和密码须同时提供或均为空")
    try:
        with request.app.state.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            secret_id = None
            if password is not None:
                secret_id = conn.execute("INSERT INTO secrets(ciphertext) VALUES (?)", (request.app.state.security.encrypt(password),)).lastrowid
            node_id = conn.execute("""INSERT INTO nodes(fingerprint,source_type,protocol,display_name,country_code,city,host,port,username,secret_ref,notes,is_enabled)
                VALUES (?,'manual','socks5',?,?,?,?,?,?,?,?,?)""",
                (fingerprint("socks5", data["host"], data["port"], username), data["display_name"], data["country_code"], data["city"],
                 data["host"], data["port"], username, secret_id, data["notes"] or "", int(data["is_enabled"]))).lastrowid
            conn.execute("INSERT INTO egresses(node_id,kind,name,is_enabled) VALUES (?,'socks5',?,?)", (node_id, data["display_name"], int(data["is_enabled"])))
            audit(conn, request.state.user["id"], "node_created", "node", node_id)
            result = node_view(find_node(conn, node_id))
    except sqlite3.IntegrityError:
        raise conflict() from None
    return result


@router.get("/{node_id}")
def get_node(node_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        return node_view(find_node(conn, node_id))


@router.patch("/{node_id}")
def patch_node(node_id: int, body: NodePatch, request: Request):
    changes = body.model_dump(exclude_unset=True)
    nonnull(changes, ("port", "is_enabled"))
    if changes.get("clear_auth") and (changes.get("username") or (changes.get("password") or "").strip()):
        raise HTTPException(422, "clear_auth 不可同时提供认证凭据")
    try:
        with request.app.state.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = dict(find_node(conn, node_id))
            merged = previous.copy()
            for name in ("display_name", "host", "port", "country_code", "city", "notes", "is_enabled", "username"):
                if name in changes:
                    merged[name] = changes[name]
            merged["notes"] = merged["notes"] or ""
            reject_self_reference(request, merged["host"], merged["port"])
            old_secret = previous["secret_ref"]
            secret_id = old_secret
            incoming_password = changes.get("password")
            new_password = incoming_password if incoming_password and incoming_password.strip() else None
            if changes.get("clear_auth"):
                merged["username"], secret_id = None, None
            elif new_password is not None:
                secret_id = conn.execute("INSERT INTO secrets(ciphertext) VALUES (?)", (request.app.state.security.encrypt(new_password),)).lastrowid
            if (merged["username"] is None) != (secret_id is None):
                raise HTTPException(422, "认证用户名和密码须成对；清空请使用 clear_auth")
            connection_changed = any(merged[k] != previous[k] for k in ("host", "port", "username"))
            if new_password is not None:
                connection_changed = connection_changed or old_secret is None or request.app.state.security.decrypt(conn.execute("SELECT ciphertext FROM secrets WHERE id=?", (old_secret,)).fetchone()[0]) != new_password
            connection_changed = connection_changed or secret_id is None and old_secret is not None
            merged["secret_ref"] = secret_id
            merged["fingerprint"] = fingerprint(merged["protocol"], merged["host"], merged["port"], merged["username"])
            merged["updated_at"] = utc_now()
            fields = ["display_name", "host", "port", "country_code", "city", "notes", "is_enabled", "username", "secret_ref", "fingerprint", "updated_at"]
            if connection_changed:
                merged.update(status="new", last_check_at=None, last_success_at=None, latency_ms=None, consecutive_failures=0)
                fields += ["status", "last_check_at", "last_success_at", "latency_ms", "consecutive_failures"]
                conn.execute("UPDATE egresses SET last_check_id=NULL,updated_at=? WHERE node_id=?", (utc_now(), node_id))
            conn.execute("UPDATE nodes SET " + ",".join(f"{f}=?" for f in fields) + " WHERE id=?", [merged[f] for f in fields] + [node_id])
            if not merged["is_enabled"]:
                conn.execute("UPDATE egresses SET is_default=0,updated_at=? WHERE node_id=? AND is_default=1", (utc_now(), node_id))
            if old_secret is not None and old_secret != secret_id:
                conn.execute("DELETE FROM secrets WHERE id=?", (old_secret,))
            audit(conn, request.state.user["id"], "node_updated", "node", node_id)
            result = node_view(find_node(conn, node_id))
    except sqlite3.IntegrityError:
        raise conflict() from None
    return result


@router.delete("/{node_id}")
def delete_node(node_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = find_node(conn, node_id)
        secret_id = row["secret_ref"]
        conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        if secret_id is not None:
            conn.execute("DELETE FROM secrets WHERE id=?", (secret_id,))
        audit(conn, request.state.user["id"], "node_deleted", "node", node_id)
    return {"ok": True}


@router.api_route("/{node_id}/check", methods=["POST", "PUT"])
def check_node(node_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        find_node(conn, node_id)
    raise HTTPException(501, "链路检测器尚未接入；配置保存不代表链路可用")


@router.api_route("/check", methods=["POST", "PUT"])
@router.api_route("/check-all", methods=["POST", "PUT"])
def check_all():
    raise HTTPException(501, "链路检测器尚未接入")
