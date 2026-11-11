# -*- coding: utf-8 -*-
"""合规与只读策略：把"只读闸门"从代码里的硬编码变成可审计、可在线编辑的配置。

policy.yaml：
  forbidden_keywords: [attach, vacuum]     # 额外禁写词（在原有黑名单之外）
  denied_columns:                            # 敏感列：命中即脱敏
    customers: [phone, id_card]
    orders: []
  mask_value: "***"
  max_rows: 500                              # 覆盖 MAX_RESULT_ROWS 的硬上限
  audit_sql: true                            # 记录被拒绝的 SQL
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from .config import BACKEND_DIR, settings

POLICY_FILE = Path(os.getenv("TEXT2SQL_POLICY_FILE")
                   or str(BACKEND_DIR / "policy.yaml"))

DEFAULT = {
    "forbidden_keywords": ["attach", "detach", "vacuum", "reindex"],
    "denied_columns": {
        "customers": ["phone", "id_card", "email"],
        "orders": [],
        "products": [],
    },
    "mask_value": "***",
    "max_rows": 500,
    "audit_sql": True,
}

_cache: dict | None = None
_cache_mtime = -1.0


def _load() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = POLICY_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data = dict(DEFAULT)
    if POLICY_FILE.exists():
        try:
            import yaml  # type: ignore
            raw = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:  # noqa: BLE001
            pass
    if not isinstance(data.get("denied_columns"), dict):
        data["denied_columns"] = {}
    _cache, _cache_mtime = data, mtime
    return data


def policy() -> dict:
    d = _load()
    return {
        "forbidden_keywords": list(d.get("forbidden_keywords") or []),
        "denied_columns": {k: list(v or []) for k, v in (d.get("denied_columns") or {}).items()},
        "mask_value": str(d.get("mask_value") or "***"),
        "max_rows": int(d.get("max_rows") or settings.MAX_RESULT_ROWS),
        "audit_sql": bool(d.get("audit_sql", True)),
        "source": str(POLICY_FILE),
    }


def save_policy(new: dict, actor: str = "") -> dict:
    import yaml  # type: ignore
    clean = {
        "forbidden_keywords": [str(x).strip() for x in (new.get("forbidden_keywords") or [])
                               if str(x).strip()],
        "denied_columns": {str(k): [str(x).strip() for x in (v or []) if str(x).strip()]
                           for k, v in (new.get("denied_columns") or {}).items()},
        "mask_value": str(new.get("mask_value") or "***"),
        "max_rows": max(10, min(5000, int(new.get("max_rows") or 500))),
        "audit_sql": bool(new.get("audit_sql", True)),
    }
    if POLICY_FILE.exists():
        shutil.copy2(POLICY_FILE,
                     POLICY_FILE.with_suffix(f".yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    tmp = POLICY_FILE.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    os.replace(tmp, POLICY_FILE)
    reset_cache()
    from . import audit
    audit.record(actor, "policy.update", str(POLICY_FILE),
                 before=policy(), after=clean, effective=True)
    return policy()


def reset_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = -1.0


def forbidden_hit(sql: str) -> str:
    """命中额外禁写词返回词本身，否则空串。"""
    low = (sql or "").lower()
    for kw in policy()["forbidden_keywords"]:
        k = str(kw).lower().strip()
        if k and re.search(r"\b" + re.escape(k) + r"\b", low):
            return str(kw)
    return ""


def denied_columns_for(table: str) -> list[str]:
    p = policy()
    return [str(c).lower() for c in (p["denied_columns"].get(table) or [])]


def mask_rows(table: str, columns: list[str], rows: list[list]) -> tuple[list[list], list[str]]:
    """命中敏感列的单元格脱敏；返回 (新行, 被脱敏列名)。"""
    denied = denied_columns_for(table)
    return mask_by_keywords(columns, rows, denied)


def mask_by_keywords(columns: list[str], rows: list[list],
                     denied: list[str]) -> tuple[list[list], list[str]]:
    """按敏感关键词脱敏（列名包含关键词即打码）。"""
    denied = [str(d).lower() for d in (denied or []) if str(d).strip()]
    if not denied or not rows:
        return rows, []
    hit = [c for c in columns if any(d in str(c).lower() for d in denied)]
    if not hit:
        return rows, []
    idx = [i for i, c in enumerate(columns) if c in hit]
    mask = policy()["mask_value"]
    out = []
    for r in rows:
        nr = list(r)
        for i in idx:
            if i < len(nr) and nr[i] not in (None, ""):
                nr[i] = mask
        out.append(nr)
    return out, hit
