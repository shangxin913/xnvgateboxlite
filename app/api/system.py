import json

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.db import audit, public_row, utc_now
from .egresses import find_egress
from .models import SchedulePatch, SettingsPatch, node_view, nonnull

router = APIRouter(prefix="/api")
AUDIT_FIELDS = ("id", "action", "resource_type", "resource_id", "created_at")
SCHEDULE_FIELDS = ("id", "name", "job_type", "interval_seconds", "is_enabled", "last_run_at", "next_run_at")
JOB_FIELDS = ("id", "job_type", "status", "error_code", "progress_current", "progress_total", "scheduled_at", "started_at", "finished_at", "created_at")


def settings_view(conn):
    return {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key,value FROM app_settings")}


@router.get("/dashboard")
def dashboard(request: Request):
    with request.app.state.db.connection() as conn:
        stats = {}
        for key, query in {
            "nodes_total": "SELECT COUNT(*) FROM nodes",
            "nodes_enabled": "SELECT COUNT(*) FROM nodes WHERE is_enabled=1",
            "nodes_healthy": "SELECT COUNT(*) FROM nodes WHERE status='healthy'",
            "egresses_total": "SELECT COUNT(*) FROM egresses",
            "egresses_enabled": "SELECT COUNT(*) FROM egresses WHERE is_enabled=1",
            "subscriptions_active": "SELECT COUNT(*) FROM subscription_tokens WHERE is_enabled=1 AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP)"}.items():
            stats[key] = conn.execute(query).fetchone()[0]
        recent_nodes = [node_view(r) for r in conn.execute("SELECT * FROM nodes ORDER BY id DESC LIMIT 5")]
        recent_audit = [public_row(r, ("action", "resource_type", "created_at")) for r in conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 8")]
        default = conn.execute("SELECT id FROM egresses WHERE is_default=1").fetchone()
    return {"stats": stats, "recent_nodes": recent_nodes, "recent_audit": recent_audit,
            "runtime": {"platform": "Ubuntu 24.04 target", "version": "0.1.0", "executor_ready": False, "vpngate_ready": False, "checker_ready": False, "default_egress_id": default[0] if default else None}}


@router.get("/settings")
def get_settings(request: Request):
    with request.app.state.db.connection() as conn:
        return settings_view(conn)


@router.patch("/settings")
def patch_settings(body: SettingsPatch, request: Request):
    data = body.model_dump(exclude_unset=True)
    nonnull(data, data.keys())
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for name, value in data.items():
            conn.execute("UPDATE app_settings SET value=?,updated_at=? WHERE key=?", (json.dumps(value), utc_now(), name))
        if data:
            audit(conn, request.state.user["id"], "settings_updated", "settings")
        return settings_view(conn)


@router.get("/jobs")
def jobs(request: Request):
    with request.app.state.db.connection() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
    return {"items": [public_row(r, JOB_FIELDS) for r in rows]}


@router.get("/schedules")
def schedules(request: Request):
    with request.app.state.db.connection() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY id").fetchall()
    return {"items": [public_row(r, SCHEDULE_FIELDS, {"is_enabled"}) for r in rows]}


@router.patch("/schedules/{schedule_id}")
def patch_schedule(schedule_id: int, body: SchedulePatch, request: Request):
    data = body.model_dump(exclude_unset=True)
    nonnull(data, data.keys())
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "计划不存在")
        if data.get("is_enabled"):
            raise HTTPException(501, "计划执行器尚未接入，当前阶段不能启用周期任务")
        if data:
            data["updated_at"] = utc_now()
            data["next_run_at"] = None
            fields = list(data)
            conn.execute("UPDATE schedules SET " + ",".join(f"{name}=?" for name in fields) + " WHERE id=?", [data[name] for name in fields] + [schedule_id])
            audit(conn, request.state.user["id"], "schedule_updated", "schedule", schedule_id)
        result = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
    return public_row(result, SCHEDULE_FIELDS, {"is_enabled"})


@router.get("/pool/summary")
def pool_summary(request: Request):
    with request.app.state.db.connection() as conn:
        counts = conn.execute("SELECT COUNT(*) AS total,COALESCE(SUM(status='new'),0) AS new,COALESCE(SUM(status='healthy'),0) AS healthy FROM nodes WHERE source_type='vpngate'").fetchone()
        last_fetch = conn.execute("SELECT MAX(fetched_at) FROM source_snapshots WHERE accepted=1 AND source_type IN ('vpngate_official','vpngate_mirror')").fetchone()[0]
    from app.core.db import timestamp
    return {**dict(counts), "last_fetch_at": timestamp(last_fetch), "available": False, "message": "VPN Gate 抓取适配器尚未接入"}


@router.get("/audit")
def audit_list(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    with request.app.state.db.connection() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [public_row(row, AUDIT_FIELDS) for row in rows]}


@router.api_route("/pool/refresh", methods=["POST", "PUT"])
@router.api_route("/sources/refresh", methods=["POST", "PUT"])
def source_refresh():
    raise HTTPException(501, "VPN Gate 抓取适配器尚未接入")


@router.post("/jobs")
@router.post("/jobs/run")
@router.post("/schedules/{schedule_id}/run")
def run_job():
    raise HTTPException(501, "后台执行器尚未接入，不会创建假成功任务")


@router.post("/executor/apply")
def apply_executor():
    raise HTTPException(501, "VPS 接入监听、隧道及出口执行层尚未接入")
