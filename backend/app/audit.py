# -*- coding: utf-8 -*-
"""配置审计：所有管理端写操作（配置、账号、提示词、语义层、合规策略）都留痕。

审计表放在 app.db（与业务库分离），只追加不修改，记录谁在什么时候把什么改成了什么，
以及该变更是否已即时生效（hot apply）或需要重启服务。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .config import settings

_INIT = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(settings.app_db_path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 5000")
    return c


def _init() -> None:
    global _INIT
    if _INIT:
        return
    c = _conn()
    try:
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                actor TEXT,
                action TEXT,
                target TEXT,
                before TEXT,
                after TEXT,
                effective INTEGER DEFAULT 1,
                note TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(id DESC)")
        c.commit()
    finally:
        c.close()
    _INIT = True


def record(actor: str, action: str, target: str,
           before=None, after=None, effective: bool = True, note: str = "") -> int:
    """写一条审计记录；before/after 可以是 dict/list/标量。"""
    _init()
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO audit_log(ts,actor,action,target,before,after,effective,note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_now(), actor or "unknown", action, target,
             json.dumps(before, ensure_ascii=False, default=str) if before is not None else "",
             json.dumps(after, ensure_ascii=False, default=str) if after is not None else "",
             1 if effective else 0, (note or "")[:500]),
        )
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def recent(limit: int = 100, actor: str = "", action: str = "") -> list[dict]:
    _init()
    c = _conn()
    try:
        sql = "SELECT * FROM audit_log"
        args: list = []
        where = []
        if actor:
            where.append("actor = ?")
            args.append(actor)
        if action:
            where.append("action = ?")
            args.append(action)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        rows = c.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("before", "after"):
                try:
                    d[k] = json.loads(d.get(k) or "null")
                except (ValueError, TypeError):
                    d[k] = d.get(k) or ""
            d["effective"] = bool(d.get("effective"))
            out.append(d)
        return out
    finally:
        c.close()


def count() -> int:
    _init()
    c = _conn()
    try:
        return int(c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
    finally:
        c.close()
