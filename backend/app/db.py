# -*- coding: utf-8 -*-
"""只读 SQL 执行器：SQLite（默认）/ PostgreSQL（DATABASE_URL 切换）。

统一遵守：只允许 SELECT / WITH、单语句、强制 LIMIT、超时保护、只读连接。
Postgres 侧额外启用 default_transaction_read_only + statement_timeout。
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from . import tracing
from .config import settings

# 用 ASCII 边界代替 \b：Python 默认 Unicode 语义下中文/下划线会被算作 \w，
# 会让「中文紧邻关键字」和 pragma_* 表值函数逃过检查。
_ASCII_L = r"(?<![A-Za-z0-9_])"
_ASCII_R = r"(?![A-Za-z0-9_])"
DANGEROUS = re.compile(
    _ASCII_L + r"(insert|update|delete|drop|alter|create|truncate|attach|detach|"
    r"pragma|vacuum|load_extension|raise|exec|begin|commit|rollback|reindex|"
    r"randomblob|zeroblob|copy|grant|revoke)" + _ASCII_R,
    re.IGNORECASE,
)
TOP_LIMIT = re.compile(_ASCII_L + r"limit" + _ASCII_R, re.IGNORECASE)
STR_LITERAL = re.compile(r"'(?:''|[^'])*'", re.DOTALL)
QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"|`[^`]*`', re.DOTALL)
LINE_COMMENT = re.compile(r"--[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
TABLE_REF = re.compile(_ASCII_L + r"(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


class SqlRejected(ValueError):
    pass


class SqlTimeout(RuntimeError):
    """查询超时：不是 SQL 语法错，不应触发「改写 SQL」重试。"""


def _mask(sql: str) -> str:
    """把字符串字面量 / 引号标识符 / 注释替换为等长空白，再做结构检查。"""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    out = STR_LITERAL.sub(blank, sql)
    out = QUOTED_IDENT.sub(blank, out)
    out = BLOCK_COMMENT.sub(blank, out)
    out = LINE_COMMENT.sub(blank, out)
    return out


def _top_level_limit(masked: str) -> bool:
    """只认最外层（括号深度 0）的 LIMIT；子查询里的 LIMIT 不算。"""
    buf, d = [], 0
    for ch in masked:
        if ch == "(":
            d += 1
            buf.append(" ")
            continue
        if ch == ")":
            d = max(0, d - 1)
            buf.append(" ")
            continue
        buf.append(ch if d == 0 else " ")
    return bool(TOP_LIMIT.search("".join(buf)))


def clean_sql(raw: str) -> str:
    sql = (raw or "").strip().rstrip(";").strip()
    if not sql:
        raise SqlRejected("SQL 为空")
    masked = _mask(sql)
    if ";" in masked:
        raise SqlRejected("只允许执行单条 SQL 语句")
    if not SQL_START.match(masked.strip()):
        raise SqlRejected("只允许 SELECT / WITH 查询，写操作一律禁止")
    hit = DANGEROUS.search(masked)
    if hit:
        raise SqlRejected(f"检测到禁止的关键字：{hit.group(0)}")
    # 合规策略里的额外禁写词（可在线编辑）
    from . import policy
    extra = policy.forbidden_hit(sql)
    if extra:
        raise SqlRejected(f"检测到禁止的关键字：{extra}")
    return sql


def sql_table_names(sql: str) -> set[str]:
    """提取 SQL 引用的表名，用于 few-shot 是否适配本轮可用表的校验。"""
    masked = _mask(sql or "")
    return {m.group(1).lower() for m in TABLE_REF.finditer(masked)}


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, float):
        return round(v, 6)
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return round(float(v), 6)
    except ImportError:  # pragma: no cover
        pass
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return str(v)


def _with_limit(sql: str, limit: int) -> tuple[str, str]:
    if _top_level_limit(_mask(sql)):
        return sql, sql
    return f"{sql} LIMIT {limit + 1}", f"{sql} LIMIT {limit}"


def _execute_sqlite(raw_sql: str, limit: int, timeout: int,
                    db_path: str | None = None) -> dict:
    sql = clean_sql(raw_sql)
    exec_sql, display_sql = _with_limit(sql, limit)
    path = db_path or str(settings.db_path)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    conn.execute(f"PRAGMA busy_timeout = {timeout}")
    started = time.perf_counter()
    deadline = started + timeout / 1000.0

    def _watchdog():
        return 1 if time.perf_counter() > deadline else 0

    conn.set_progress_handler(_watchdog, 2000)
    try:
        cur = conn.execute(exec_sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(limit + 1)
        elapsed = (time.perf_counter() - started) * 1000
        truncated = len(fetched) > limit
        rows = [[_jsonable(v) for v in row] for row in fetched[:limit]]
        return {
            "sql": display_sql,
            "sql_executed": exec_sql,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "elapsed_ms": round(elapsed, 2),
            "truncated": truncated,
            "dialect": "sqlite",
        }
    except sqlite3.Error as e:
        if "interrupted" in str(e).lower():
            raise SqlTimeout("查询超时，请缩小范围或加筛选条件") from e
        raise RuntimeError(f"SQL 执行失败：{str(e)[:200]}") from e
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def _execute_postgres(raw_sql: str, limit: int, timeout: int) -> dict:
    try:
        import psycopg  # type: ignore
    except ImportError as e:  # pragma: no cover - 取决于部署
        raise RuntimeError(
            'Postgres 模式需要安装驱动：pip install "psycopg[binary]"'
        ) from e
    sql = clean_sql(raw_sql)
    exec_sql, display_sql = _with_limit(sql, limit)
    started = time.perf_counter()
    try:
        with psycopg.connect(
            settings.DATABASE_URL,
            connect_timeout=max(3, min(15, timeout // 1000 or 3)),
            options=(
                f"-c statement_timeout={timeout} "
                "-c default_transaction_read_only=on"
            ),
        ) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute(exec_sql)
                columns = [d.name for d in (cur.description or [])]
                fetched = cur.fetchmany(limit + 1)
                elapsed = (time.perf_counter() - started) * 1000
                truncated = len(fetched) > limit
                rows = [[_jsonable(v) for v in row] for row in fetched[:limit]]
                return {
                    "sql": display_sql,
                    "sql_executed": exec_sql,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "elapsed_ms": round(elapsed, 2),
                    "truncated": truncated,
                    "dialect": "postgres",
                }
    except Exception as e:  # psycopg 异常类型很多，统一转成可回灌 Observation
        msg = str(e).lower()
        if "timeout" in msg or "canceling statement" in msg:
            raise SqlTimeout("查询超时，请缩小范围或加筛选条件") from e
        raise RuntimeError(f"SQL 执行失败：{str(e)[:200]}") from e


def execute_readonly(
    raw_sql: str,
    max_rows: int | None = None,
    timeout_ms: int | None = None,
    db_path: str | None = None,
) -> dict:
    """执行只读查询，返回 {columns, rows, row_count, elapsed_ms, truncated, sql}。

    db_path 显式传入时强制走 SQLite（BIRD 评估等场景）；否则按 DATABASE_URL 分派。
    """
    from . import policy
    pol = policy.policy()
    limit = max_rows or min(settings.MAX_RESULT_ROWS, int(pol.get("max_rows") or 500))
    timeout = timeout_ms or settings.SQL_TIMEOUT_MS
    use_pg = db_path is None and settings.is_postgres
    with tracing.span("db.execute", dialect="postgres" if use_pg else "sqlite") as sp:
        try:
            res = (_execute_postgres(raw_sql, limit, timeout) if use_pg
                   else _execute_sqlite(raw_sql, limit, timeout, db_path))
            # 敏感列脱敏（命中策略里登记的列名即打码）
            denied: list[str] = []
            for t in sql_table_names(raw_sql):
                denied.extend(policy.denied_columns_for(t))
            if denied:
                res["rows"], masked_cols = policy.mask_by_keywords(
                    res["columns"], res["rows"], denied)
                if masked_cols:
                    res["masked_columns"] = masked_cols
            sp.update(row_count=res["row_count"], truncated=res["truncated"], ok=True)
            return res
        except Exception as e:
            sp.update(ok=False, error=type(e).__name__)
            raise


def table_sample(name: str, n: int = 5) -> dict:
    """给前端「表结构浏览」用：返回前 n 行。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise SqlRejected("非法表名")
    return execute_readonly(f'SELECT * FROM "{name}" LIMIT {n}', max_rows=n)


def chart_hint(columns: list[str], rows: list[list[Any]]) -> dict | None:
    """根据结果形状给前端一个图表建议（前端据此自动画图）。"""
    if not rows or not columns or len(rows) < 2:
        return None
    if len(columns) < 2:
        return None
    first, second = rows[0][0], rows[0][1]
    numeric_second = isinstance(second, (int, float)) and not isinstance(second, bool)
    if not numeric_second:
        return None
    is_date = isinstance(first, str) and bool(re.match(r"^\d{4}(-\d{1,2})?", str(first)))
    return {
        "type": "line" if is_date and len(rows) >= 4 else "bar",
        "x": columns[0],
        "y": columns[1],
        "max_points": 30,
    }
