# -*- coding: utf-8 -*-
"""在线配置中心：白名单化地改 .env，写完立刻热生效，并留审计。

安全约束：
- 只有白名单里的键能改，密钥类键（KEY/PASSWORD/SECRET/TOKEN）一律拒绝；
- 写入前自动备份 .env（.env.bak-<ts>），原子替换，权限保持 600；
- 改完同步 patch 内存里的 settings，标「需要重启」的键除外；
- 每次写入写一条 audit_log。
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import audit
from .config import PROJECT_DIR, settings

SECRET_HINT = ("KEY", "PASSWORD", "SECRET")


def _is_secret(key: str) -> bool:
    """密钥类键：含 KEY/PASSWORD/SECRET，或名字就是 token（不是 *_MAX_TOKENS 这类计数键）。"""
    k = (key or "").upper()
    if any(h in k for h in SECRET_HINT):
        return True
    return k == "TOKEN" or k.endswith("_TOKEN") or k.endswith("_APIKEY")


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    group: str
    kind: str = "int"          # int / float / bool / str / enum
    lo: int | None = None
    hi: int | None = None
    options: tuple[str, ...] = ()
    desc: str = ""
    restart: bool = False
    hot: bool = True


SPECS: tuple[Spec, ...] = (
    # ---- 文本模型 ----
    Spec("LLM_MODEL", "主模型", "模型", "str", desc="主模型 ID（OpenAI 兼容）"),
    Spec("LLM_BASE_URL", "主模型地址", "模型", "str", desc="主模型 base URL"),
    Spec("LLM_PROVIDER", "主模型来源", "模型", "str", desc="仅作标识，写入 trace"),
    Spec("LLM_FALLBACK_MODEL", "兜底模型", "模型", "str", desc="主模型故障时自动切换"),
    Spec("LLM_FALLBACK_BASE_URL", "兜底地址", "模型", "str"),
    Spec("LLM_FALLBACK_PROVIDER", "兜底来源", "模型", "str"),
    Spec("LLM_TIMEOUT", "超时（秒）", "模型", "int", 10, 300, desc="单次模型请求超时"),
    Spec("LLM_MAX_TOKENS", "最大输出 token", "模型", "int", 256, 16384),
    Spec("LLM_TEMPERATURE", "温度", "模型", "float", 0.0, 2.0),
    Spec("INSIGHT_MAX_TOKENS", "洞察 token 上限", "模型", "int", 100, 3000),
    # ---- Agent ----
    Spec("AGENT_MODE", "运行模式", "Agent", "enum", options=("toolloop", "workflow")),
    Spec("MAX_AGENT_STEPS", "最大规划步数", "Agent", "int", 1, 20),
    Spec("MAX_TOOL_SQL", "单轮最多执行 SQL", "Agent", "int", 1, 10),
    Spec("TOP_K_TABLES", "选表 Top-K", "Agent", "int", 1, 20),
    Spec("COLUMN_LINK_TOPK", "每表返回列数", "Agent", "int", 2, 40),
    Spec("FEWSHOT_K", "few-shot 条数", "Agent", "int", 0, 6),
    Spec("MAX_SQL_RETRY", "SQL 重写次数", "Agent", "int", 0, 5),
    Spec("MAX_LLM_CALLS", "单轮 LLM 预算", "Agent", "int", 1, 20),
    Spec("HISTORY_TURNS", "注入历史轮数", "Agent", "int", 1, 20),
    Spec("FOLLOWUP_COUNT", "追问条数", "Agent", "int", 0, 6),
    Spec("INSIGHT_PREVIEW_ROWS", "洞察预览行数", "Agent", "int", 5, 100),
    Spec("AUTO_INSIGHT", "自动结论", "Agent", "bool"),
    Spec("EMPTY_RESULT_RETRY", "空结果重试", "Agent", "bool"),
    Spec("GUARD_ENABLED", "拒答护栏", "Agent", "bool"),
    Spec("GUARD_SUGGESTIONS", "建议问法条数", "Agent", "int", 0, 6),
    Spec("MEMORY_ENABLED", "用户偏好记忆", "Agent", "bool"),
    # ---- 结果与护栏 ----
    Spec("MAX_RESULT_ROWS", "结果行数上限", "结果与护栏", "int", 10, 5000),
    Spec("SQL_TIMEOUT_MS", "SQL 超时（毫秒）", "结果与护栏", "int", 200, 60000),
    Spec("FK_EXPAND_MAX", "外键闭包补表数", "结果与护栏", "int", 0, 10),
    # ---- 限流与观测 ----
    Spec("RATE_LIMIT_ENABLED", "接口限流", "限流与观测", "bool"),
    Spec("RATE_LIMIT_PER_MIN", "每分钟请求上限", "限流与观测", "int", 1, 1000),
    Spec("LOGIN_FAIL_LIMIT", "登录失败上限", "限流与观测", "int", 3, 50),
    Spec("TRACE_ENABLED", "落 trace", "限流与观测", "bool"),
    Spec("TRACE_RECENT", "内存保留 trace 数", "限流与观测", "int", 20, 2000),
    Spec("TOKEN_TTL_HOURS", "登录有效期（小时）", "限流与观测", "int", 1, 168),
    Spec("REBUILD_COOLDOWN", "索引重建冷却（秒）", "限流与观测", "int", 0, 86400),
    Spec("MAX_QA_HISTORY", "few-shot 库上限", "限流与观测", "int", 50, 10000),
)

SPEC_MAP = {s.key: s for s in SPECS}
GROUPS = ("模型", "Agent", "结果与护栏", "限流与观测")

# 需要重启才能生效的键（模块导入时读过的）
RESTART_KEYS = {"SECRET_KEY", "TEXT2SQL_DATA_DIR", "EMB_DIM", "TEXT2SQL_STATIC_DIR"}


def env_path() -> Path:
    override = os.getenv("TEXT2SQL_ENV_FILE")
    return Path(override) if override else PROJECT_DIR / ".env"


def _read_lines() -> list[str]:
    p = env_path()
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read_lines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _mask(key: str, value: str) -> str:
    if _is_secret(key):
        return "********" if value else ""
    return value


def current() -> dict[str, str]:
    """当前生效值（密钥掩码）。"""
    env = _read_env()
    out = {}
    for s in SPECS:
        v = getattr(settings, s.key, env.get(s.key, ""))
        if s.kind == "bool":
            v = "true" if bool(v) else "false"
        out[s.key] = _mask(s.key, str(v))
    return out


def catalog() -> dict:
    vals = current()
    groups = []
    for g in GROUPS:
        groups.append({
            "group": g,
            "items": [{
                "key": s.key, "label": s.label, "kind": s.kind,
                "min": s.lo, "max": s.hi, "options": list(s.options),
                "desc": s.desc, "restart": s.key in RESTART_KEYS,
                "value": vals.get(s.key, ""),
            } for s in SPECS if s.group == g],
        })
    return {"groups": groups, "env_path": str(env_path()),
            "editable": sorted(SPEC_MAP)}


def _coerce(spec: Spec, raw) -> str:
    if spec.kind == "int":
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{spec.key} 必须是整数")
        if spec.lo is not None and n < spec.lo:
            raise ValueError(f"{spec.key} 不能小于 {spec.lo}")
        if spec.hi is not None and n > spec.hi:
            raise ValueError(f"{spec.key} 不能大于 {spec.hi}")
        return str(n)
    if spec.kind == "float":
        try:
            f = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{spec.key} 必须是数字")
        if spec.lo is not None and f < spec.lo:
            raise ValueError(f"{spec.key} 不能小于 {spec.lo}")
        if spec.hi is not None and f > spec.hi:
            raise ValueError(f"{spec.key} 不能大于 {spec.hi}")
        return str(f)
    if spec.kind == "bool":
        v = str(raw).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return "true"
        if v in ("0", "false", "no", "off"):
            return "false"
        raise ValueError(f"{spec.key} 必须是 true/false")
    if spec.kind == "enum":
        v = str(raw).strip()
        if spec.options and v not in spec.options:
            raise ValueError(f"{spec.key} 只能取 {', '.join(spec.options)}")
        return v
    return str(raw).strip()


def _write_env(lines: list[str], changes: dict[str, str]) -> tuple[Path, list[str]]:
    """原子写 .env：替换已有键，保留注释与顺序；新键追加到末尾分组。"""
    p = env_path()
    backup = p.with_suffix(f".env.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    if p.exists():
        shutil.copy2(p, backup)
    out: list[str] = []
    seen = set()
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in changes:
                out.append(f"{k}={changes[k]}")
                seen.add(k)
                continue
        out.append(line)
    tail = [f"{k}={v}" for k, v in changes.items() if k not in seen]
    if tail:
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- 管理后台写入 ----")
        out.extend(tail)
    content = "\n".join(out).rstrip() + "\n"
    tmp = p.with_suffix(".env.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    try:
        st = p.stat()
        os.chown(tmp, st.st_uid, st.st_gid)
    except OSError:
        pass
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return backup, [f"{k}={v}" for k, v in changes.items()]


def apply(actor: str, changes: dict, note: str = "") -> dict:
    """校验并写入配置；能热生效的直接 patch 内存 settings。"""
    if not changes:
        raise ValueError("没有要修改的项")
    clean: dict[str, str] = {}
    for k, raw in changes.items():
        spec = SPEC_MAP.get(k)
        if not spec:
            raise ValueError(f"{k} 不在可改白名单内")
        if _is_secret(k):
            raise ValueError(f"{k} 属于密钥类配置，不允许在线修改")
        clean[k] = _coerce(spec, raw)
    before = {k: _mask(k, str(getattr(settings, k, ""))) for k in clean}
    _backup, written = _write_env(_read_lines(), clean)
    restart = []
    hot = []
    for k, v in clean.items():
        spec = SPEC_MAP[k]
        if k in RESTART_KEYS or spec.restart:
            restart.append(k)
            continue
        try:
            if spec.kind == "bool":
                object.__setattr__(settings, k, v == "true")
            elif spec.kind == "int":
                object.__setattr__(settings, k, int(v))
            elif spec.kind == "float":
                object.__setattr__(settings, k, float(v))
            else:
                object.__setattr__(settings, k, v)
            hot.append(k)
        except Exception:  # noqa: BLE001
            restart.append(k)
    os.environ.update(clean)
    audit.record(actor, "config.update", ",".join(sorted(clean)),
                 before=before, after=clean, effective=bool(hot),
                 note=note or f"热生效 {len(hot)} 项，需重启 {len(restart)} 项")
    return {"changed": clean, "written": written, "hot": hot,
            "restart_required": restart,
            "effective": bool(hot),
            "note": "已写入 .env 并热生效" if hot else "已写入 .env，需重启服务生效"}


# ---------------- 账号管理（写 AUTH_USERS） ----------------
def accounts() -> list[dict]:
    out = []
    for u, rec in settings.auth_users.items():
        out.append({"username": u, "role": rec["role"],
                    "password": "********"})
    return out


def set_accounts(actor: str, users: list[dict], note: str = "") -> dict:
    """整体覆盖账号表：[{username, password, role}]。密码留空表示不改。"""
    items: list[str] = []
    before = {u: r["role"] for u, r in settings.auth_users.items()}
    for u in users:
        name = str(u.get("username") or "").strip()
        pwd = str(u.get("password") or "")
        role = "admin" if str(u.get("role") or "user").lower() == "admin" else "user"
        if not name:
            continue
        if not pwd:
            old = settings.auth_users.get(name)
            if not old:
                raise ValueError(f"{name} 是新账号，必须给密码")
            pwd = old["password"]
        if "," in pwd or ":" in pwd:
            raise ValueError("密码不能包含逗号或冒号")
        items.append(f"{name}:{pwd}:{role}")
    if not items:
        raise ValueError("至少保留一个账号")
    _backup, _ = _write_env(_read_lines(), {"AUTH_USERS": ",".join(items)})
    object.__setattr__(settings, "AUTH_USERS", ",".join(items))
    os.environ["AUTH_USERS"] = ",".join(items)
    audit.record(actor, "accounts.update", "AUTH_USERS",
                 before=before, after={"users": [i.split(":")[0] for i in items]},
                 effective=True, note=note or "账号表已更新，旧 token 立即失效")
    return {"users": accounts()}
