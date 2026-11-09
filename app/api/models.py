import hashlib
import ipaddress
import json
import re
import unicodedata
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.db import public_row


def no_controls(value: str) -> str:
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
        raise ValueError("不得包含控制字符")
    return value


def normalize_name(value: str) -> str:
    value = no_controls(value).strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("名称须为 1–100 个字符")
    return value


def normalize_host(value: str) -> str:
    value = no_controls(value)
    if value != value.strip() or not value or len(value) > 253:
        raise ValueError("host 必须为合法域名或 IP")
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
        if ":" not in value:
            raise ValueError("方括号仅允许用于 IPv6")
    if any(c in value for c in "/\\@?#%") or any(c.isspace() for c in value):
        raise ValueError("host 不允许 URL、路径或控制字符")
    try:
        return ipaddress.ip_address(value).compressed.lower()
    except ValueError:
        if ":" in value or re.fullmatch(r"[0-9.]+", value):
            raise ValueError("无效 IP 地址") from None
    try:
        result = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("无效 IDNA 域名") from None
    if len(result) > 253 or not result:
        raise ValueError("无效域名长度")
    for label in result.split("."):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label):
            raise ValueError("无效域名标签")
    return result


def auth_username(value: str | None):
    if value is None or value == "":
        return None
    no_controls(value)
    if ":" in value or not value.strip() or len(value) > 128:
        raise ValueError("用户名不能为空白、含冒号或超过 128 字符")
    return value


def country(value: str | None):
    if value in (None, ""):
        return None
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError("国家代码须为两位大写字母")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("新密码不能全部为空白")
        return value


class NodeCreate(Input):
    display_name: str
    host: str
    port: int = Field(ge=1, le=65535, strict=True)
    username: str | None = None
    password: str | None = Field(default=None, max_length=1024)
    country_code: str | None = None
    city: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    is_enabled: bool = Field(default=True, strict=True)
    _name = field_validator("display_name")(normalize_name)
    _host = field_validator("host")(normalize_host)
    _username = field_validator("username")(auth_username)
    _country = field_validator("country_code")(country)


class NodePatch(Input):
    display_name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535, strict=True)
    username: str | None = None
    password: str | None = Field(default=None, max_length=1024)
    country_code: str | None = None
    city: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    is_enabled: bool | None = Field(default=None, strict=True)
    clear_auth: bool = Field(default=False, strict=True)

    @field_validator("display_name", "host")
    @classmethod
    def validate_strings(cls, value, info):
        if value is None:
            raise ValueError("字段不能为 null")
        return normalize_name(value) if info.field_name == "display_name" else normalize_host(value)

    _username = field_validator("username")(auth_username)
    _country = field_validator("country_code")(country)


class EgressPatch(Input):
    name: str | None = None
    priority: int | None = Field(default=None, ge=0, le=1000, strict=True)
    is_enabled: bool | None = Field(default=None, strict=True)
    include_in_subscription: bool | None = Field(default=None, strict=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if value is None:
            raise ValueError("名称不能为 null")
        return normalize_name(value)


class SubscriptionCreate(Input):
    name: str
    require_healthy: bool = Field(default=False, strict=True)
    country_codes: list[str] = Field(default_factory=list, max_length=250)
    _name = field_validator("name")(normalize_name)

    @field_validator("country_codes")
    @classmethod
    def validate_countries(cls, values):
        if any(country(v) is None for v in values):
            raise ValueError("国家代码不能为空")
        return sorted(set(values))


class SettingsPatch(Input):
    node_check_concurrency: int | None = Field(default=None, ge=1, le=16, strict=True)
    node_check_timeout_seconds: int | None = Field(default=None, ge=5, le=120, strict=True)
    subscription_require_healthy: bool | None = Field(default=None, strict=True)
    source_refresh_interval_seconds: int | None = Field(default=None, ge=1800, le=86400, strict=True)


class SchedulePatch(Input):
    interval_seconds: int | None = Field(default=None, ge=1800, le=2147483647, strict=True)
    is_enabled: bool | None = Field(default=None, strict=True)


def nonnull(data, fields):
    for name in fields:
        if name in data and data[name] is None:
            raise HTTPException(422, f"{name} 不能为 null")


def fingerprint(protocol, host, port, username):
    return hashlib.sha256(json.dumps([protocol, host, port, username or ""], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def reject_self_reference(request: Request, host: str, port: int):
    own_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::", request.url.hostname or ""}
    server = request.scope.get("server")
    own_ports = {request.url.port or (443 if request.url.scheme == "https" else 80)}
    if server:
        own_hosts.add(str(server[0]))
        if server[1]:
            own_ports.add(int(server[1]))
    try:
        if ipaddress.ip_address(host).is_loopback:
            own_hosts.add(host)
    except ValueError:
        pass
    if host in own_hosts and port in own_ports:
        raise HTTPException(422, "节点不得引用本服务自身地址及端口")


NODE_FIELDS = ("id", "source_type", "protocol", "display_name", "country_code", "city", "host", "port", "username", "notes", "status", "is_enabled", "first_seen_at", "last_check_at", "last_success_at", "latency_ms", "created_at", "updated_at")


def node_view(row):
    result = public_row(row, NODE_FIELDS, {"is_enabled"})
    result["has_password"] = row["secret_ref"] is not None
    return result


def find_node(conn, node_id):
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "节点不存在")
    return row
