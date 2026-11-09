from fastapi import APIRouter, HTTPException, Request

from app.core.db import audit, public_row, utc_now
from .models import EgressPatch, nonnull

router = APIRouter(prefix="/api/egresses")

EGRESS_QUERY = """SELECT e.*,n.host,n.port,n.username,n.status AS node_status,n.is_enabled AS node_enabled
                  FROM egresses e LEFT JOIN nodes n ON n.id=e.node_id"""
EGRESS_FIELDS = ("id", "node_id", "kind", "name", "host", "port", "username", "priority", "is_enabled", "include_in_subscription", "is_default", "created_at")


def egress_view(row):
    result = public_row(row, EGRESS_FIELDS, {"is_enabled", "include_in_subscription", "is_default"})
    result["status"] = "unprovisioned" if row["kind"] == "local" else row["node_status"] or "configured"
    return result


def find_egress(conn, egress_id):
    row = conn.execute(EGRESS_QUERY + " WHERE e.id=?", (egress_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "出口不存在")
    return row


@router.get("")
def list_egresses(request: Request):
    with request.app.state.db.connection() as conn:
        rows = conn.execute(EGRESS_QUERY + " ORDER BY e.priority,e.id").fetchall()
    return {"items": [egress_view(row) for row in rows]}


@router.patch("/{egress_id}")
def patch_egress(egress_id: int, body: EgressPatch, request: Request):
    data = body.model_dump(exclude_unset=True)
    nonnull(data, data.keys())
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        find_egress(conn, egress_id)
        if data:
            fields = list(data)
            if data.get("is_enabled") is False:
                # Clear default in the same update: the SQL CHECK requires it.
                fields.append("is_default")
                data["is_default"] = 0
            fields.append("updated_at")
            data["updated_at"] = utc_now()
            conn.execute("UPDATE egresses SET " + ",".join(f"{name}=?" for name in fields) + " WHERE id=?", [data[name] for name in fields] + [egress_id])
            audit(conn, request.state.user["id"], "egress_updated", "egress", egress_id)
        result = egress_view(find_egress(conn, egress_id))
    return result


@router.post("/{egress_id}/default")
def default_egress(egress_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = find_egress(conn, egress_id)
        if not row["is_enabled"] or row["node_enabled"] == 0:
            raise HTTPException(409, "只有启用的出口及关联节点可设为默认")
        conn.execute("UPDATE egresses SET is_default=0,updated_at=? WHERE is_default=1", (utc_now(),))
        conn.execute("UPDATE egresses SET is_default=1,updated_at=? WHERE id=?", (utc_now(), egress_id))
        audit(conn, request.state.user["id"], "default_egress_changed", "egress", egress_id)
    return {"ok": True}


@router.api_route("/{egress_id}/check", methods=["POST", "PUT"])
def check_egress(egress_id: int, request: Request):
    with request.app.state.db.connection() as conn:
        find_egress(conn, egress_id)
    raise HTTPException(501, "出口检测及执行层尚未接入")
