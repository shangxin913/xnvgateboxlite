"""stdlib SQLite: every connection owns a transaction and is always closed."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import sqlite3

from .config import ROOT


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def timestamp(value):
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 19 and value[10] == " ":
        return value.replace(" ", "T") + "Z"
    return value


def public_row(row, fields, boolean_fields=()):
    result = {name: row[name] for name in fields}
    for name, value in list(result.items()):
        if name in boolean_fields:
            result[name] = bool(value)
        elif name.endswith("_at"):
            result[name] = timestamp(value)
    return result


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "app.db"

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def initialization_lock(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data_dir, 0o700)
        fd = os.open(self.data_dir / ".initialize.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def initialize(self):
        with self.initialization_lock():
            # Pre-create with private permissions, including WAL's inherited mode.
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            with self.connection() as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "schema_migrations" not in tables:
                    if tables:
                        raise RuntimeError("数据库结构不完整；拒绝覆盖现有数据库")
                    conn.executescript((ROOT / "migrations" / "001_initial.sql").read_text(encoding="utf-8"))
                elif conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone() is None:
                    raise RuntimeError("数据库版本不受支持")
            for suffix in ("", "-wal", "-shm"):
                path = Path(str(self.path) + suffix)
                if path.exists():
                    os.chmod(path, 0o600)


def audit(conn, user_id, action, resource_type, resource_id=None):
    # Deliberately do not persist request payloads, credentials or tokens.
    conn.execute("INSERT INTO audit_logs(user_id,action,resource_type,resource_id) VALUES (?,?,?,?)",
                 (user_id, action, resource_type, str(resource_id) if resource_id is not None else None))
