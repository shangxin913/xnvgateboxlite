import hmac
import logging
from pathlib import Path
import secrets
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, egresses, nodes, subscriptions, system
from app.core.config import ROOT, Settings
from app.core.db import Database, utc_now
from app.core.security import COOKIE_NAME, LoginLimiter, PASSWORD_HASHER, Security, token_hash


class NoAccessLogs(logging.Filter):
    """Suppress path-bearing access records, including subscription bearer URLs."""
    def filter(self, record):
        return False


def create_app(data_dir: Path | None = None, cookie_secure: bool | None = None) -> FastAPI:
    settings = Settings.load(data_dir, cookie_secure)
    db = Database(settings.data_dir)
    db.initialize()
    security = Security(db)
    application = FastAPI(title="XNV GateBox Lite", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    application.state.settings = settings
    application.state.db = db
    application.state.security = security
    application.state.limiter = LoginLimiter()
    application.state.dummy_password_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, NoAccessLogs) for f in logger.filters):
        logger.addFilter(NoAccessLogs())

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        path = request.url.path
        normalized = path.rstrip("/")
        management = path == "/api" or path.startswith("/api/")
        subscription = path == "/sub" or path.startswith("/sub/")
        response = None
        login = normalized == "/api/auth/login" and request.method == "POST"
        if management and not login:
            token = request.cookies.get(COOKIE_NAME, "")
            user = None
            if 40 <= len(token) <= 128 and token.isascii():
                with db.connection() as conn:
                    row = conn.execute("""SELECT u.*,s.id AS session_id FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id
                        WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.is_active=1""", (token_hash(token), utc_now())).fetchone()
                    user = dict(row) if row is not None else None
            if user is None:
                response = JSONResponse({"detail": "请先登录"}, status_code=401)
            else:
                request.state.user = user
                request.state.session_id = user["session_id"]
                request.state.session_token = token
                if user["must_change_password"] and normalized not in {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}:
                    response = JSONResponse({"detail": "请先修改初始密码"}, status_code=403)
                elif request.method not in {"GET", "HEAD", "OPTIONS"}:
                    supplied = request.headers.get("x-csrf-token", "")
                    if not supplied.isascii() or not hmac.compare_digest(supplied, security.csrf(token)):
                        response = JSONResponse({"detail": "CSRF 校验失败，请刷新登录状态后重试"}, status_code=403)
        if response is None:
            response = await call_next(request)
        if management or subscription:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.middleware("http")
    async def private_failure_response(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Avoid Uvicorn's exception traceback containing a bearer-token URL.
            # Log only an exception class, never arguments, paths or payloads.
            logging.getLogger("gatebox").error("request_failed type=%s", type(exc).__name__)
            status = 503 if isinstance(exc, sqlite3.OperationalError) else 500
            detail = "数据库暂时不可用，请稍后重试" if status == 503 else "内部错误，请检查服务配置或从完整备份恢复"
            return JSONResponse({"detail": detail}, status_code=status,
                                headers={"Cache-Control": "private, no-store", "Pragma": "no-cache", "Expires": "0",
                                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default includes submitted password values in errors.
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        detail = exc.detail
        if detail == "Not Found":
            detail = "接口或资源不存在"
        elif detail == "Method Not Allowed":
            detail = "此接口不支持该请求方法"
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @application.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "数据库暂时不可用，请稍后重试"}, status_code=503)

    @application.get("/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    for router in (auth.router, nodes.router, egresses.router, subscriptions.router, system.router):
        application.include_router(router)

    web = ROOT / "web"

    @application.get("/assets/{asset_path:path}", include_in_schema=False)
    def frontend_asset(asset_path: str):
        root = (web / "assets").resolve()
        path = (root / asset_path).resolve()
        if ".." in Path(asset_path).parts or not path.is_relative_to(root) or not path.is_file():
            return JSONResponse({"detail": "静态资源不存在"}, status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @application.get("/static/{asset_path:path}", include_in_schema=False)
    def static_asset(asset_path: str):
        root = (web / "static").resolve()
        path = (root / asset_path).resolve()
        if ".." in Path(asset_path).parts or not path.is_relative_to(root) or not path.is_file():
            return JSONResponse({"detail": "静态资源不存在"}, status_code=404)
        return FileResponse(path)

    @application.get("/manus-routes.json", include_in_schema=False)
    def routes_manifest():
        file = web / "manus-routes.json"
        if not file.is_file():
            return JSONResponse({"detail": "路由清单尚未提供"}, status_code=404)
        return FileResponse(file, media_type="application/json")

    def spa():
        file = web / "index.html"
        if not file.is_file():
            return JSONResponse({"detail": "管理界面静态文件尚未提供"}, status_code=503)
        return FileResponse(file, media_type="text/html", headers={"Cache-Control": "no-cache"})

    for path in ("/", "/login", "/nodes", "/egresses", "/subscriptions", "/tasks", "/settings", "/pool"):
        application.add_api_route(path, spa, methods=["GET"], include_in_schema=False)
    return application
