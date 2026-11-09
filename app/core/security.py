from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from threading import Lock
import time

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
COOKIE_NAME = "gatebox_session"


class Security:
    def __init__(self, database):
        key_path = database.data_dir / "master.key"
        with database.initialization_lock():
            if key_path.is_symlink():
                raise RuntimeError("主密钥不得使用符号链接")
            if not key_path.exists():
                # Never silently replace a lost key in an initialized deployment.
                with database.connection() as conn:
                    if conn.execute("SELECT 1 FROM secrets LIMIT 1").fetchone() or conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
                        raise RuntimeError("主密钥丢失；请从备份恢复，不可重新生成")
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(Fernet.generate_key())
                        output.flush()
                        os.fsync(output.fileno())
                except BaseException:
                    key_path.unlink(missing_ok=True)
                    raise
            os.chmod(key_path, 0o600)
            self._key = key_path.read_bytes()
        self._fernet = Fernet(self._key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")

    def csrf(self, token: str) -> str:
        return hmac.new(self._key, token.encode("ascii"), hashlib.sha256).hexdigest()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def expires_at(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


class LoginLimiter:
    """Per-process, bounded sliding windows; no fake jobs or background threads.

    Five attempts per identity/IP in five minutes, twenty per IP. This VPS
    phase runs a single Uvicorn process; multi-worker deployments need a shared
    reverse-proxy limiter or a persisted distributed limiter.
    """
    def __init__(self):
        self._buckets = OrderedDict()
        self._lock = Lock()

    def allow(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        keys = (("ip", ip, 20), ("identity", ip + "\0" + username.casefold(), 5))
        with self._lock:
            selected = []
            for namespace, value, maximum in keys:
                key = (namespace, value)
                bucket = self._buckets.setdefault(key, deque())
                self._buckets.move_to_end(key)
                while bucket and bucket[0] <= now - 300:
                    bucket.popleft()
                selected.append((bucket, maximum))
            allowed = all(len(bucket) < maximum for bucket, maximum in selected)
            # Even a blocked identity consumes IP budget, preventing enumeration.
            for bucket, maximum in selected:
                if len(bucket) < maximum:
                    bucket.append(now)
            while len(self._buckets) > 4096:
                self._buckets.popitem(last=False)
            return allowed


def random_token() -> str:
    return secrets.token_urlsafe(48)
