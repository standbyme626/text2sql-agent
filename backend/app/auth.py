# -*- coding: utf-8 -*-
"""轻量鉴权：HMAC 签名 token + 统一失败限流 + 撤销表。

- token 走独立头 X-App-Token；同时兼容 Authorization: Basic / Bearer
- 所有凭据校验失败都按 IP 计数，不再只限 /api/login（防止用 Basic 分支绕过爆破防护）
- token 绑定 password_version：改密码或轮换 SECRET_KEY 后旧 token 立即失效
- /api/logout 可主动撤销当前 token
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time

from fastapi import Depends, Header, HTTPException, Request

from .config import settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()


def make_token(username: str) -> str:
    payload = {"u": username, "r": settings.role_of(username),
               "pv": settings.password_version,
               "exp": int(time.time()) + settings.TOKEN_TTL_HOURS * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def check_token(token: str) -> bool:
    return bool(token_user(token))


def token_user(token: str) -> str:
    """校验签名 / 有效期 / 用户名 / 密码版本 / 撤销列表，返回用户名。"""
    try:
        if is_revoked(token):
            return ""
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return ""
        p = json.loads(_unb64(body))
        if p.get("exp", 0) <= int(time.time()):
            return ""
        if p.get("pv") != settings.password_version:
            return ""
        user = str(p.get("u", ""))
        if not user or user not in settings.auth_users:
            return ""
        return user
    except Exception:
        return ""


def verify_login(username: str, password: str) -> bool:
    rec = settings.auth_users.get(username)
    if not rec or not rec.get("password"):
        return False
    return hmac.compare_digest(password, rec["password"])


# ---------- 撤销表（进程内，重启即清空；改密由 password_version 兜底） ----------
_REVOKED: set[str] = set()
_REVOKED_LOCK = threading.Lock()


def revoke_token(token: str) -> None:
    if not token:
        return
    with _REVOKED_LOCK:
        _REVOKED.add(token)
        if len(_REVOKED) > 4096:  # 防止无限增长
            _REVOKED.clear()


def is_revoked(token: str) -> bool:
    with _REVOKED_LOCK:
        return token in _REVOKED


# ---------- 登录失败限流（统一给所有凭据校验入口使用） ----------
_LOGIN_FAILS: dict[str, tuple[int, float]] = {}
_LOGIN_LOCK = threading.Lock()
_LOGIN_MAX_FAILS = settings.LOGIN_FAIL_LIMIT
_LOGIN_WINDOW = 60.0
_LOGIN_MAX_IPS = 2048


def _gc(now: float) -> None:
    for ip, (_, first) in list(_LOGIN_FAILS.items()):
        if now - first > _LOGIN_WINDOW:
            _LOGIN_FAILS.pop(ip, None)
    while len(_LOGIN_FAILS) > _LOGIN_MAX_IPS:
        _LOGIN_FAILS.pop(next(iter(_LOGIN_FAILS)), None)


def login_blocked(ip: str) -> bool:
    now = time.time()
    with _LOGIN_LOCK:
        _gc(now)
        rec = _LOGIN_FAILS.get(ip)
        return bool(rec and rec[0] >= settings.LOGIN_FAIL_LIMIT)


def note_login_failure(ip: str) -> None:
    now = time.time()
    with _LOGIN_LOCK:
        _gc(now)
        count, first = _LOGIN_FAILS.get(ip, (0, now))
        if now - first > _LOGIN_WINDOW:
            count, first = 0, now
        _LOGIN_FAILS[ip] = (count + 1, first)


def clear_login_failures(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(ip, None)


# ---------- 通用限流（保护高消耗端点） ----------
_HITS: dict[str, list[float]] = {}
_HITS_LOCK = threading.Lock()


def rate_ok(key: str, per_min: int | None = None) -> bool:
    limit = per_min or settings.RATE_LIMIT_PER_MIN
    if not settings.RATE_LIMIT_ENABLED:
        return True
    now = time.time()
    with _HITS_LOCK:
        arr = [t for t in _HITS.get(key, []) if now - t < 60]
        if len(arr) >= limit:
            _HITS[key] = arr
            return False
        arr.append(now)
        _HITS[key] = arr
        if len(_HITS) > _LOGIN_MAX_IPS:
            for k in list(_HITS)[:512]:
                _HITS.pop(k, None)
        return True


def client_ip(request: Request) -> str:
    """只信任反代追加的最后一跳，不采信客户端可伪造的最左 XFF。"""
    xr = request.headers.get("x-real-ip", "").strip()
    if xr:
        return xr
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_app_token: str | None = Header(default=None, alias="X-App-Token"),
) -> str:
    """返回已认证用户名，供会话归属判断使用。"""
    if not settings.auth_enabled:
        return "anonymous"

    ip = client_ip(request)
    if x_app_token:
        user = token_user(x_app_token)
        if user:
            return user
        note_login_failure(ip)
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录或凭据缺失")

    low = authorization.lower()
    if low.startswith("basic "):
        try:
            raw = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
            user, pw = raw.split(":", 1)
            if verify_login(user, pw):
                clear_login_failures(ip)
                return user
        except Exception:  # noqa: BLE001
            pass
        if login_blocked(ip):
            raise HTTPException(429, "尝试次数过多，请 1 分钟后再试")
        note_login_failure(ip)
        raise HTTPException(status_code=401, detail="Basic 凭据无效")

    if low.startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user = token_user(token)
        if user:
            return user
    note_login_failure(ip)
    raise HTTPException(status_code=401, detail="token 无效或已过期")


def require_admin(user: str = Depends(require_auth)) -> str:
    """管理端网关：只有 admin 角色可进；无鉴权模式（本地 mock/自测）放行。"""
    if not settings.auth_enabled:
        return user
    if settings.role_of(user) != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
