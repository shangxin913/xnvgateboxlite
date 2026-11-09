"""Only the two documented environment settings are consulted."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cookie_secure: bool
    session_seconds: int = 12 * 60 * 60

    @classmethod
    def load(cls, data_dir: Path | None = None, cookie_secure: bool | None = None):
        directory = Path(data_dir if data_dir is not None else os.environ.get("GATEBOX_DATA_DIR", ROOT / ".runtime")).expanduser().resolve()
        if cookie_secure is None:
            value = os.environ.get("GATEBOX_COOKIE_SECURE", "true").lower()
            if value not in {"true", "false"}:
                raise ValueError("GATEBOX_COOKIE_SECURE 必须为 true 或 false")
            cookie_secure = value == "true"
        return cls(directory, cookie_secure)
