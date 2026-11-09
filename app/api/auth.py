from fastapi import APIRouter, HTTPException, Request, Response

from app.core.db import audit, utc_now
from app.core.security import COOKIE_NAME, PASSWORD_HASHER, expires_at, random_token, token_hash, verify_password
from .models import LoginInput, PasswordInput

router = APIRouter(prefix="/api/auth")


def session_view(request, user, token):
    return {"user": {"id": user["id"], "username": user["username"], "must_change_password": bool(user["must_change_password"])},
            "csrf_token": request.app.state.security.csrf(token)}


def delete_cookie(response, settings):
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True,
                           samesite="none" if settings.cookie_secure else "lax")


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    state = request.app.state
    ip = request.client.host if request.client else "unknown"
    if not state.limiter.allow(ip, body.username):
        raise HTTPException(429, "登录尝试过于频繁，请五分钟后重试", headers={"Retry-After": "300"})
    with state.db.connection() as conn:
        # Serialize password verification/session creation against password
        # changes, so a stale password cannot mint a post-revocation session.
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1", (body.username,)).fetchone()
        # A runtime-only dummy hash avoids a fast username oracle; never an account.
        encoded = user["password_hash"] if user else state.dummy_password_hash
        valid = verify_password(encoded, body.password)
        if user is None or not valid:
            audit(conn, None, "login_failed", "auth")
            # Commit failure audit before returning an error.
            conn.commit()
            raise HTTPException(401, "用户名或密码错误")
        token = random_token()
        now = utc_now()
        conn.execute("UPDATE admin_users SET last_login_at=?,updated_at=? WHERE id=?", (now, now, user["id"]))
        if PASSWORD_HASHER.check_needs_rehash(encoded):
            conn.execute("UPDATE admin_users SET password_hash=? WHERE id=?", (PASSWORD_HASHER.hash(body.password), user["id"]))
        conn.execute("DELETE FROM admin_sessions WHERE expires_at<=? OR revoked_at IS NOT NULL", (now,))
        conn.execute("INSERT INTO admin_sessions(user_id,token_hash,expires_at) VALUES (?,?,?)", (user["id"], token_hash(token), expires_at(state.settings.session_seconds)))
        audit(conn, user["id"], "login", "auth")
    response.set_cookie(COOKIE_NAME, token, max_age=state.settings.session_seconds, path="/", secure=state.settings.cookie_secure,
                        httponly=True, samesite="none" if state.settings.cookie_secure else "lax")
    return session_view(request, user, token)


@router.get("/me")
def me(request: Request):
    return session_view(request, request.state.user, request.state.session_token)


@router.post("/logout")
def logout(request: Request, response: Response):
    with request.app.state.db.connection() as conn:
        conn.execute("UPDATE admin_sessions SET revoked_at=? WHERE id=?", (utc_now(), request.state.session_id))
        audit(conn, request.state.user["id"], "logout", "auth")
    delete_cookie(response, request.app.state.settings)
    return {"ok": True}


@router.post("/password")
def password(body: PasswordInput, request: Request, response: Response):
    user_id = request.state.user["id"]
    with request.app.state.db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
        if not verify_password(user["password_hash"], body.current_password):
            raise HTTPException(400, "当前密码不正确")
        if body.new_password == body.current_password:
            raise HTTPException(422, "新密码不得与当前密码相同")
        conn.execute("UPDATE admin_users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?",
                     (PASSWORD_HASHER.hash(body.new_password), utc_now(), user_id))
        conn.execute("UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (utc_now(), user_id))
        audit(conn, user_id, "password_changed", "auth")
    delete_cookie(response, request.app.state.settings)
    return {"ok": True}
