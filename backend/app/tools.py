# -*- coding: utf-8 -*-
"""Agent 工具注册表（OpenAI function calling / MCP 共用的单一真相）。

工具只做三件事：检索 schema、只读执行 SQL、查询受治理指标；外加显式记忆写入。
所有工具结果都是可序列化 JSON，失败也作为 Observation 返回而不是抛异常，
这样模型可以像 2026 的数据 Agent 一样「执行 → 看结果 → 修正」。
"""
from __future__ import annotations

import json

from . import db, semantic, tracing
from .config import settings

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_schema",
            "description": (
                "检索业务库的表与字段。初始上下文只有 Top-K 张表；"
                "需要更多表、或 SQL 报缺表/缺列时调用。返回 DDL 与相关列。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，中文业务语义即可"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "在只读连接上执行一条 SELECT/WITH 查询并返回结果预览。"
                "任何 SQL 在给出结论前都必须先执行验证；报错或 0 行时根据错误修正后重试。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_metrics",
            "description": "列出受治理的业务指标口径（GMV/销量/客单价等）与标准 JOIN 关系。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_preference",
            "description": (
                "仅当用户明确说「记住/以后/默认」时，写入一条长期偏好（如默认只看有效订单）。"
                "不要从普通问题里擅自推断偏好。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 300}},
                "required": ["text"],
            },
        },
    },
]


class ToolContext:
    def __init__(self, idx, store=None, question: str = "",
                 session_id: str = "", owner: str = "",
                 boost: list[str] | None = None, qvec: list[float] | None = None):
        self.idx = idx
        self.store = store
        self.question = question
        self.session_id = session_id
        self.owner = owner
        self.boost = boost or []
        self.qvec = qvec
        self.sql_count = 0
        self.executed: list[dict] = []


def tool_names() -> list[str]:
    return [t["function"]["name"] for t in TOOL_SPECS]


def _preview(res: dict, limit: int | None = None) -> dict:
    n = limit or settings.TOOL_ROW_PREVIEW
    return {
        "ok": True,
        "sql": res.get("sql", ""),
        "columns": res.get("columns", []),
        "rows": res.get("rows", [])[:n],
        "row_count": res.get("row_count", 0),
        "truncated": bool(res.get("truncated")),
        "elapsed_ms": res.get("elapsed_ms", 0),
    }


async def execute(ctx: ToolContext, name: str, args: dict | None = None) -> dict:
    args = args or {}
    with tracing.span(f"tool.{name}", tool=name) as sp:
        try:
            result = await _dispatch(ctx, name, args)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)[:200]}
        sp.update(ok=bool(result.get("ok")), error=result.get("error"))
        return result


async def _dispatch(ctx: ToolContext, name: str, args: dict) -> dict:
    if name == "search_schema":
        query = str(args.get("query") or ctx.question or "").strip()
        top_k = max(1, min(12, int(args.get("top_k") or settings.TOP_K_TABLES)))
        tables = await ctx.idx.search(
            query, top_k=top_k, boost=ctx.boost, qvec=ctx.qvec, expand_fks=True)
        names = [t["name"] for t in tables]
        colmap = {t["name"]: t.get("matched_columns") or [] for t in tables}
        return {
            "ok": True,
            "tables": [{k: t.get(k) for k in ("name", "cn", "domain", "score",
                                              "matched_columns", "fk_added")}
                       for t in tables],
            "context": ctx.idx.prompt_context(names, colmap),
        }

    if name == "run_sql":
        if ctx.sql_count >= settings.MAX_TOOL_SQL:
            return {"ok": False,
                    "error": f"SQL 执行次数已达上限（{settings.MAX_TOOL_SQL} 次），请基于已有结果作答。"}
        ctx.sql_count += 1
        sql = str(args.get("sql") or "").strip()
        if not sql:
            return {"ok": False, "error": "sql 参数为空"}
        try:
            res = db.execute_readonly(sql)
        except (db.SqlRejected, db.SqlTimeout, RuntimeError) as e:
            return {
                "ok": False,
                "sql": sql,
                "error": str(e)[:200],
                "hint": "若是 no such table/column，请先调用 search_schema 扩大候选表再重写。",
            }
        ctx.executed.append(res)
        return _preview(res)

    if name == "list_metrics":
        cat = semantic.catalog()
        return {
            "ok": True,
            "metrics": [
                {k: m.get(k) for k in ("id", "name", "synonyms", "table", "expr",
                                       "valid_filter", "unit", "notes")}
                for m in cat["metrics"]
            ],
            "joins": cat["joins"],
        }

    if name == "remember_preference":
        if not settings.MEMORY_ENABLED or ctx.store is None or not ctx.owner:
            return {"ok": False, "error": "长期记忆未启用"}
        text = str(args.get("text") or "").strip()
        if len(text) < 2:
            return {"ok": False, "error": "偏好内容太短"}
        ctx.store.add_memory(ctx.owner, text[:300])
        return {"ok": True, "text": text[:300]}

    return {"ok": False, "error": f"未知工具：{name}"}


def observation(result: dict) -> str:
    """压缩成模型可读的 tool message，避免把 500 行结果塞回 prompt。"""
    return json.dumps(result, ensure_ascii=False, default=str)
