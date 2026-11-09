"""One-time initialization; passwords are never accepted via process argv."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

from app.core.config import Settings
from app.core.db import Database, audit
from app.core.security import PASSWORD_HASHER, Security
from app.api.models import auth_username


def bootstrap_admin(data_dir: Path, username: str, password: str) -> int:
    validated_username = auth_username(username)
    if validated_username is None or len(validated_username) > 64:
        raise ValueError("管理员用户名须为 1–64 个字符且不含冒号或控制字符")
    if not isinstance(password, str) or not 12 <= len(password) <= 128 or not password.strip():
        raise ValueError("管理员密码须为 12–128 个字符且不能全部为空白")
    settings = Settings.load(data_dir=data_dir)
    db = Database(settings.data_dir)
    db.initialize()
    Security(db)
    encoded = PASSWORD_HASHER.hash(password)
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
            raise ValueError("管理员已存在，拒绝重复初始化")
        user_id = conn.execute("INSERT INTO admin_users(username,password_hash,must_change_password) VALUES (?,?,1)", (username, encoded)).lastrowid
        assert user_id is not None
        audit(conn, user_id, "admin_initialized", "auth")
    return user_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="XNV GateBox Lite 私密管理员初始化")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="生成随机初始密码并写入权限 0600 的新文件")
    init.add_argument("--username", default="admin")
    init.add_argument("--output", required=True, type=Path)
    init.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output
    if not output.is_absolute():
        parser.error("--output 必须为绝对私密文件路径")
    fd = None
    created = False
    try:
        # O_EXCL rejects existing files and symlinks; do not overwrite credentials.
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        os.fchmod(fd, 0o600)
        password = secrets.token_urlsafe(32)
        settings = Settings.load(data_dir=args.data_dir)
        # Persist the file before committing account creation. An interrupted
        # bootstrap never leaves an account whose generated password was lost.
        payload = json.dumps({"username": args.username, "password": password, "must_change_password": True}, ensure_ascii=False, indent=2) + "\n"
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        bootstrap_admin(settings.data_dir, args.username, password)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        if fd is not None:
            os.close(fd)
        if created:
            output.unlink(missing_ok=True)
        # Errors contain no generated password, key or ciphertext.
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1
    print("管理员已初始化，初始凭据已写入指定私密文件；首次登录必须修改密码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
