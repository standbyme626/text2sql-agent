# -*- coding: utf-8 -*-
"""会话、消息、历史问答（含向量）持久化，独立 app.db，不碰业务库。"""
from __future__ import annotations

import json
import re
import sqlite3
from array import array
from datetime import datetime

from .config import settings
from .db import sql_table_names
from .embedding import cosine

_ZH = re.compile(r"[\u4e00-\u9fff]")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _grams(s: str) -> set[str]:
    s = (s or "").lower()
    return {s[i:i + 2] for i in range(len(s) - 1) if s[i:i + 2].strip()}


def _is_zh(s) -> bool:
    t = re.sub(r"\s+", "", str(s or ""))
    if not t:
        return False
    zh = len(_ZH.findall(t))
    en = len(re.findall(r"[A-Za-z]{2,}", t))
    return zh >= 2 and en <= max(3, zh)


def _to_blob(vec: list[float] | None) -> bytes | None:
    if not vec:
        return None
    return array("f", [float(x) for x in vec]).tobytes()


def _from_blob(b) -> list[float]:
    if not b:
        return []
    a = array("f")
    a.frombytes(b)
    return list(a)


class Store:
    def __init__(self):
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(settings.app_db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout = 5000")
        return c

    def _init(self) -> None:
        c = self._conn()
        try:
            c.execute("PRAGMA journal_mode = WAL")   # 并发 SSE 读写不再互相锁
            c.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    owner TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    sql TEXT,
                    tables TEXT,
                    payload TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS qa_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    question TEXT,
                    sql TEXT,
                    tables TEXT,
                    vector BLOB,
                    is_test INTEGER DEFAULT 0,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS user_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT,
                    UNIQUE(owner, text)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_owner ON user_memory(owner, id);
            """)
            # 幂等迁移：老库补列
            cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
            if "payload" not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN payload TEXT")
            scols = {r[1] for r in c.execute("PRAGMA table_info(sessions)")}
            if "owner" not in scols:
                c.execute("ALTER TABLE sessions ADD COLUMN owner TEXT")
            qcols = {r[1] for r in c.execute("PRAGMA table_info(qa_history)")}
            for col in ("session_id", "tables", "is_test"):
                if col not in qcols:
                    c.execute(f"ALTER TABLE qa_history ADD COLUMN {col} "
                              + ("INTEGER DEFAULT 0" if col == "is_test" else "TEXT"))
            # 依赖新增列的索引必须在 ALTER TABLE 之后建（老库迁移路径）
            c.execute("CREATE INDEX IF NOT EXISTS idx_qa_session ON qa_history(session_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_qa_test ON qa_history(is_test)")
            c.commit()
            self._secure_files()
        finally:
            c.close()

    def _secure_files(self) -> None:
        import os
        for name in ("app.db", "app.db-wal", "app.db-shm", "schema_index.json", ".secret_key"):
            p = settings.app_db_path.parent / name
            if p.exists():
                try:
                    os.chmod(p, 0o600)
                except OSError:
                    pass

    # ---------- 会话归属 ----------
    def _owner_of(self, c: sqlite3.Connection, sid: str) -> str | None:
        row = c.execute("SELECT owner FROM sessions WHERE session_id=?", (sid,)).fetchone()
        return (row["owner"] or "") if row else None

    def _visible(self, owner: str | None, row_owner: str | None) -> bool:
        # owner 为空 = 历史遗留会话，保持可读；新建会话一律带 owner
        return not row_owner or not owner or row_owner == owner

    # ---------- 会话 ----------
    def ensure_session(self, sid: str, title: str = "", owner: str = "") -> None:
        c = self._conn()
        try:
            c.execute(
                "INSERT OR IGNORE INTO sessions(session_id,title,owner,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (sid, title or "新会话", owner, _now(), _now()),
            )
            c.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (_now(), sid))
            if owner:
                c.execute("UPDATE sessions SET owner=? WHERE session_id=? AND "
                          "(owner IS NULL OR owner='')", (owner, sid))
            c.commit()
        finally:
            c.close()

    def list_sessions(self, limit: int = 30, owner: str | None = None) -> list[dict]:
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows if self._visible(owner, r["owner"])]
        finally:
            c.close()

    def delete_session(self, sid: str, owner: str | None = None) -> None:
        c = self._conn()
        try:
            if not self._visible(owner, self._owner_of(c, sid)):
                return
            c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            c.execute("DELETE FROM qa_history WHERE session_id=?", (sid,))  # 级联清理 few-shot
            c.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
            c.commit()
        finally:
            c.close()

    # ---------- 消息 ----------
    def add_message(self, sid: str, role: str, content: str,
                    sql: str = "", tables: list[str] | None = None,
                    payload: dict | None = None) -> int:
        c = self._conn()
        try:
            cur = c.execute(
                "INSERT INTO messages(session_id,role,content,sql,tables,payload,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, role, content, sql,
                 json.dumps(tables or [], ensure_ascii=False),
                 json.dumps(payload or {}, ensure_ascii=False, default=str),
                 _now()),
            )
            c.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (_now(), sid))
            if role == "user" and content:
                c.execute(
                    "UPDATE sessions SET title=? WHERE session_id=? AND title='新会话'",
                    (content[:40], sid),
                )
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()

    def patch_message(self, mid: int, content: str | None = None,
                      payload_patch: dict | None = None) -> None:
        """在原消息上补齐结论 / 重跑结果，保持消息 id 稳定、不产生第二条。"""
        if not mid:
            return
        c = self._conn()
        try:
            row = c.execute("SELECT content,payload FROM messages WHERE id=?", (mid,)).fetchone()
            if not row:
                return
            try:
                p = json.loads(row["payload"] or "{}")
                if not isinstance(p, dict):
                    p = {}
            except (ValueError, TypeError):
                p = {}
            p.update(payload_patch or {})
            c.execute("UPDATE messages SET content=?, payload=? WHERE id=?",
                      (content if content is not None else row["content"],
                       json.dumps(p, ensure_ascii=False, default=str), mid))
            c.commit()
        finally:
            c.close()

    def add_answer(self, sid: str, content: str, sql: str, tables: list[str],
                   payload: dict, question: str, vector: list[float] | None,
                   table_names: list[str] | None = None) -> int:
        """一次回答 = assistant 消息 + few-shot 写入，放进同一个事务。"""
        c = self._conn()
        try:
            cur = c.execute(
                "INSERT INTO messages(session_id,role,content,sql,tables,payload,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, "assistant", content, sql, json.dumps(tables, ensure_ascii=False),
                 json.dumps(payload, ensure_ascii=False, default=str), _now()),
            )
            c.execute(
                "INSERT INTO qa_history(session_id,question,sql,tables,vector,is_test,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, question, sql, json.dumps(table_names or tables, ensure_ascii=False),
                 _to_blob(vector), 0, _now()),
            )
            # few-shot 库设保留上限，防止无限膨胀
            c.execute(
                "DELETE FROM qa_history WHERE id NOT IN "
                "(SELECT id FROM qa_history ORDER BY id DESC LIMIT ?)",
                (settings.MAX_QA_HISTORY,),
            )
            c.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (_now(), sid))
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()

    def patch_rerun(self, sid: str, message_id: int, result: dict) -> bool:
        """前端编辑 SQL 重跑后回写结果，刷新 / 切会话不再丢失。"""
        if not message_id:
            return False
        c = self._conn()
        try:
            row = c.execute("SELECT payload,sql FROM messages WHERE id=? AND session_id=?",
                            (message_id, sid)).fetchone()
            if not row:
                return False
            try:
                p = json.loads(row["payload"] or "{}")
                if not isinstance(p, dict):
                    p = {}
            except (ValueError, TypeError):
                p = {}
            p["result"] = result
            p["insight"] = None          # 数据变了，旧结论失效
            p["rerun_count"] = int(p.get("rerun_count") or 0) + 1
            c.execute("UPDATE messages SET sql=?, payload=? WHERE id=?",
                      (result.get("sql") or row["sql"],
                       json.dumps(p, ensure_ascii=False, default=str), message_id))
            c.commit()
            return True
        finally:
            c.close()

    def message_with_question(self, mid: int,
                              owner: str | None = None) -> dict | None:
        """取一条消息 + 它前面最近一条用户问题，供「确认回答进知识库」使用。"""
        c = self._conn()
        try:
            row = c.execute(
                "SELECT id,session_id,role,content,sql,tables,payload,created_at "
                "FROM messages WHERE id=?", (mid,)).fetchone()
            if not row:
                return None
            if not self._visible(owner, self._owner_of(c, row["session_id"])):
                return None
            q = c.execute(
                "SELECT content FROM messages WHERE session_id=? AND role='user' "
                "AND id<? ORDER BY id DESC LIMIT 1",
                (row["session_id"], mid)).fetchone()
            d = dict(row)
            d["question"] = (q["content"] if q else "") or ""
            d["owner"] = self._owner_of(c, row["session_id"]) or ""
            try:
                d["tables"] = json.loads(d.get("tables") or "[]")
            except (ValueError, TypeError):
                d["tables"] = []
            return d
        finally:
            c.close()

    def count_sessions(self) -> int:
        c = self._conn()
        try:
            return int(c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        finally:
            c.close()

    def message_id_for(self, sid: str, nth_assistant: int) -> int:
        """按「本会话第 N 条 assistant」定位消息 id，供前端重跑回写。"""
        c = self._conn()
        try:
            rows = c.execute("SELECT id FROM messages WHERE session_id=? AND role='assistant' "
                             "ORDER BY id", (sid,)).fetchall()
            return int(rows[nth_assistant]["id"]) if 0 <= nth_assistant < len(rows) else 0
        finally:
            c.close()

    def get_history(self, sid: str, turns: int = 6,
                    owner: str | None = None) -> list[dict]:
        c = self._conn()
        try:
            if not self._visible(owner, self._owner_of(c, sid)):
                return []
            rows = c.execute(
                "SELECT id,role,content,sql,tables,payload FROM messages WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?", (sid, turns * 2)
            ).fetchall()
            out = []
            for r in reversed(rows):
                d = dict(r)
                try:
                    t = json.loads(d.get("tables") or "[]")
                    d["tables"] = t if isinstance(t, list) else []
                except (ValueError, TypeError):
                    d["tables"] = []
                try:
                    p = json.loads(d.get("payload") or "{}")
                except (ValueError, TypeError):
                    p = {}
                if not isinstance(p, dict):   # 合法 JSON 但不是对象，旧版本会 500
                    p = {}
                d["result"] = p.get("result") if isinstance(p.get("result"), dict) else None
                d["guidance"] = p.get("guidance")
                d["skip_history"] = bool(d["guidance"])   # 拒答不进模型上下文，但前端仍要显示
                ins = p.get("insight")
                non_chinese = False
                if ins and isinstance(ins, dict) and not _is_zh(ins.get("summary") or ""):
                    ins = None
                    non_chinese = True
                d["insight"] = ins if isinstance(ins, dict) else None
                content = d.get("content") or ""
                if content and not content.startswith("已生成并执行 SQL") and not _is_zh(content):
                    d["content"] = ""
                    non_chinese = True
                d["non_chinese"] = non_chinese
                td = p.get("tables_detail")
                d["tables_detail"] = td if isinstance(td, list) else []
                d["rerun_count"] = p.get("rerun_count") or 0
                d["steps"] = p.get("steps") if isinstance(p.get("steps"), list) else []
                d["trace_id"] = p.get("trace_id") or ""
                d["agent_mode"] = p.get("agent_mode") or ""
                d.pop("payload", None)
                out.append(d)
            return out
        finally:
            c.close()

    def last_tables(self, sid: str) -> list[str]:
        """只取最近一条「真正命中过表」的 assistant；拒答的 [] 不清空继承。"""
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT tables,payload FROM messages WHERE session_id=? AND role='assistant' "
                "ORDER BY id DESC LIMIT 20", (sid,)
            ).fetchall()
            for r in rows:
                try:
                    t = json.loads(r["tables"] or "[]")
                except (ValueError, TypeError):
                    t = []
                if not isinstance(t, list) or not t:
                    continue
                p = r["payload"] or ""
                if '"guidance"' in p:
                    continue
                return t
            return []
        finally:
            c.close()

    # ---------- 未命中 / 失败聚合（管理端）----------
    def unmatched(self, limit: int = 50) -> list[dict]:
        """聚合"没答好"的问题：护栏拒答、0 行、错误、未完成。"""
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,session_id,role,content,payload,created_at FROM messages "
                "ORDER BY id DESC LIMIT ?", (max(200, limit * 40),)).fetchall()
        finally:
            c.close()
        last_user: dict[str, str] = {}
        out: list[dict] = []
        for r in rows:
            sid = r["session_id"]
            if r["role"] == "user":
                last_user[sid] = r["content"] or ""
                continue
            reason = ""
            try:
                p = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                p = {}
            if not isinstance(p, dict):
                p = {}
            if p.get("guidance"):
                reason = "refused"
            else:
                res = p.get("result") if isinstance(p.get("result"), dict) else None
                if res is not None:
                    if int(res.get("row_count") or 0) == 0:
                        reason = "zero_rows"
                    elif res.get("error"):
                        reason = "sql_error"
            if not reason and (r["content"] or "").startswith("（本次回答未完成"):
                reason = "incomplete"
            if not reason:
                continue
            out.append({
                "message_id": r["id"],
                "session_id": sid,
                "question": last_user.get(sid, ""),
                "reason": reason,
                "created_at": r["created_at"],
                "sql": p.get("result", {}).get("sql", "") if isinstance(
                    p.get("result"), dict) else "",
            })
            if len(out) >= limit:
                break
        return out

    # ---------- 用户长期记忆 ----------
    def add_memory(self, owner: str, text: str) -> int:
        if not owner or not text:
            return 0
        c = self._conn()
        try:
            cur = c.execute(
                "INSERT OR IGNORE INTO user_memory(owner,text,created_at) VALUES (?,?,?)",
                (owner, text.strip()[:300], _now()),
            )
            c.execute(
                "DELETE FROM user_memory WHERE owner=? AND id NOT IN "
                "(SELECT id FROM user_memory WHERE owner=? ORDER BY id DESC LIMIT 100)",
                (owner, owner),
            )
            c.commit()
            return int(cur.lastrowid or 0)
        finally:
            c.close()

    def list_memory(self, owner: str, limit: int = 50) -> list[dict]:
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,text,created_at FROM user_memory WHERE owner=? "
                "ORDER BY id DESC LIMIT ?", (owner, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    def delete_memory(self, owner: str, mid: int) -> bool:
        c = self._conn()
        try:
            cur = c.execute("DELETE FROM user_memory WHERE owner=? AND id=?", (owner, mid))
            c.commit()
            return cur.rowcount > 0
        finally:
            c.close()

    def clear_memory(self, owner: str) -> None:
        c = self._conn()
        try:
            c.execute("DELETE FROM user_memory WHERE owner=?", (owner,))
            c.commit()
        finally:
            c.close()

    def relevant_memory(self, question: str, owner: str, k: int = 3) -> list[str]:
        """按中文二元组重合度召回偏好；不做向量调用，零额度。"""
        if not owner or not question:
            return []
        rows = self.list_memory(owner, 200)
        qg = _grams(question)
        scored = []
        for r in rows:
            hit = len(qg & _grams(r["text"]))
            if hit:
                scored.append((hit, r["text"]))
        scored.sort(key=lambda x: -x[0])
        out = [t for _, t in scored[:k]]
        # 关键词没命中时也要注入最近偏好（例如「默认只看广东」与问题无字面重合）
        for r in rows:
            if len(out) >= k:
                break
            if r["text"] not in out:
                out.append(r["text"])
        return out[:k]

    # ---------- 历史问答 few-shot ----------
    def add_qa(self, question: str, sql: str, vector: list[float] | None,
               session_id: str = "", table_names: list[str] | None = None,
               is_test: bool = False) -> None:
        c = self._conn()
        try:
            c.execute(
                "INSERT INTO qa_history(session_id,question,sql,tables,vector,is_test,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (session_id, question, sql,
                 json.dumps(table_names or [], ensure_ascii=False),
                 _to_blob(vector), 1 if is_test else 0, _now()),
            )
            c.commit()
        finally:
            c.close()

    def cleanup_test_qa(self) -> None:
        c = self._conn()
        try:
            c.execute("DELETE FROM qa_history WHERE is_test=1")
            c.commit()
        finally:
            c.close()

    def similar(self, question: str, qvec: list[float] | None, k: int = 2,
                allowed_tables: set[str] | None = None) -> list[dict]:
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT question,sql,tables,vector FROM qa_history WHERE is_test=0 "
                "ORDER BY id DESC LIMIT ?", (max(k * 20, settings.MAX_QA_HISTORY),)
            ).fetchall()
        finally:
            c.close()
        qg = _grams(question)
        out = []
        for r in rows:
            if r["question"] == question or not r["sql"]:
                continue
            # few-shot 的 SQL 只能引用本轮可用的表，否则模型照抄会违反「只准用给定表」
            if allowed_tables:
                try:
                    declared = json.loads(r["tables"] or "[]")
                except (ValueError, TypeError):
                    declared = []
                used = set(str(x).lower() for x in declared) or sql_table_names(r["sql"])
                if not used or not used.issubset(allowed_tables):
                    continue
            hit = len(qg & _grams(r["question"]))
            ks = min(1.0, hit / max(2.0, len(qg) * 0.7))
            try:
                vs = cosine(qvec, _from_blob(r["vector"])) if qvec else 0.0
            except ValueError:   # 维度不一致的旧数据直接跳过
                continue
            score = (0.65 * max(0.0, vs) + 0.35 * ks) if qvec else ks
            if score > 0.30:
                out.append({"question": r["question"], "sql": r["sql"],
                            "score": round(float(score), 4)})
        out.sort(key=lambda x: -x["score"])
        return out[:k]
