import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.core.db import audit, public_row, utc_now
from app.core.security import random_token, token_hash
from app.services.subscription_builder import build_subscription, select_nodes, token_scope
from .models import SubscriptionCreate

router = APIRouter()
FORMATS = {"v2ray", "clash", "mihomo"}


def find_token(conn, subscription_id):
    row = conn.execute("SELECT * FROM subscription_tokens WHERE id=?", (subscription_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "订阅不存在")
    return row


def valid_token(row):
    return row is not None and bool(row["is_enabled"]) and row["revoked_at"] is None and (row["expires_at"] is None or row["expires_at"] > utc_now())


def subscription_view(conn, row):
    result = public_row(row, ("id", "name", "is_enabled", "created_at", "last_used_at", "revoked_at"), {"is_enabled"})
    result["scope"] = token_scope(row)
    result["node_count"] = len(select_nodes(conn, result["scope"])) if valid_token(row) else 0
    return result


@router.get("/api/subscriptions")
def list_subscriptions(request: Request):
    with request.app.state.db.connection() as conn:
        rows = conn.execute("SELECT * FROM subscription_tokens ORDER BY id DESC").fetchall()
        return {"items": [subscription_view(conn, row) for row in rows]}


@router.post("/api/subscriptions", status_code=201)
def create_subscription(body: SubscriptionCreate, request: Request):
    token = random_token()
    scope = {"require_healthy": body.require_healthy, "country_codes": body.country_codes}
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        subscription_id = conn.execute("INSERT INTO subscription_tokens(name,token_hash,scope_json,created_by) VALUES (?,?,?,?)",
                                       (body.name, token_hash(token), json.dumps(scope), request.state.user["id"])).lastrowid
        count = len(select_nodes(conn, scope))
        audit(conn, request.state.user["id"], "subscription_created", "subscription", subscription_id)
    return {"id": subscription_id, "name": body.name, "token": token, "paths": {name: f"/sub/{token}/{name}" for name in sorted(FORMATS)}, "node_count": count}


@router.delete("/api/subscriptions/{subscription_id}")
def revoke_subscription(subscription_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = find_token(conn, subscription_id)
        if row["revoked_at"] is None:
            conn.execute("UPDATE subscription_tokens SET is_enabled=0,revoked_at=? WHERE id=?", (utc_now(), subscription_id))
            audit(conn, request.state.user["id"], "subscription_revoked", "subscription", subscription_id)
    return {"ok": True}


@router.get("/api/subscriptions/{subscription_id}/preview")
def preview_subscription(subscription_id: int, request: Request, format: Literal["clash", "mihomo", "v2ray"] = "clash"):
    with request.app.state.db.connection() as conn:
        row = find_token(conn, subscription_id)
        if not valid_token(row):
            raise HTTPException(404, "订阅已撤销或已失效")
        content, count, warnings = build_subscription(conn, request.app.state.security, row, format)
    return {"content": content, "node_count": count, "format": format, "warnings": warnings}


@router.get("/sub/{token}/{format_name}")
def get_subscription(token: str, format_name: str, request: Request):
    if format_name not in FORMATS or not 40 <= len(token) <= 128:
        raise HTTPException(404, "订阅不存在或已失效")
    with request.app.state.db.connection() as conn:
        # Serialize against revocation; once revoke returns, future reads fail.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM subscription_tokens WHERE token_hash=?", (token_hash(token),)).fetchone()
        if not valid_token(row):
            raise HTTPException(404, "订阅不存在或已失效")
        content, count, _ = build_subscription(conn, request.app.state.security, row, format_name, encoded=True)
        conn.execute("UPDATE subscription_tokens SET last_used_at=? WHERE id=?", (utc_now(), row["id"]))
        conn.execute("INSERT INTO subscription_access_logs(token_id,format,http_status,node_count) VALUES (?,?,200,?)", (row["id"], format_name, count))
        conn.execute("INSERT INTO subscription_builds(token_id,format,node_count,content_sha256) VALUES (?,?,?,?)",
                     (row["id"], format_name, count, hashlib.sha256(content.encode("utf-8")).hexdigest()))
    return Response(content, media_type="text/plain" if format_name == "v2ray" else "application/yaml", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
