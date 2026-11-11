# -*- coding: utf-8 -*-
"""语义层加载器：YAML 指标目录 → 可审计 prompt 块 / API catalog。

文件缺失或 YAML 解析失败时退回内置 BUSINESS_RULES，服务不中断。
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import settings

FALLBACK_RULES = """【业务口径（优先于字面理解）】
- 销售额 / GMV / 营收：优先用 orders.pay_amount（实付金额）；按商品拆分时用 order_items.line_total。
- 统计有效成交时，排除 orders.status 为 cancelled、refunded 的订单。
- 销量：order_items.quantity 求和；客单价 ≈ 有效订单实付金额 / 订单数。
- 日期字段是 TEXT(YYYY-MM-DD)，按月份统计用 strftime('%Y-%m', order_date)。
- 金额单位为元，聚合结果用 ROUND(..., 2)；状态值只能用给定「可选值」，不要臆造。
"""

_cache: dict | None = None
_cache_mtime: float = -1.0
_load_error = ""


def _path() -> Path:
    return Path(settings.SEMANTIC_FILE)


def load() -> dict:
    global _cache, _cache_mtime, _load_error
    p = _path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data: dict = {}
    if p.exists():
        try:
            text = p.read_text(encoding="utf-8")
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(text) or {}
            except ImportError:
                import json
                data = json.loads(text)
        except Exception as e:  # noqa: BLE001
            _load_error = f"语义层加载失败：{type(e).__name__}"
            data = {}
    else:
        _load_error = "语义层文件不存在，使用内置口径"
    if not isinstance(data, dict):
        data = {}
    _cache, _cache_mtime = data, mtime
    return data


def last_error() -> str:
    return _load_error


def metrics() -> list[dict]:
    raw = load().get("metrics") or []
    return [m for m in raw if isinstance(m, dict) and m.get("name")]


def catalog() -> dict:
    d = load()
    return {
        "version": d.get("version", 0),
        "metrics": metrics(),
        "joins": d.get("joins") or [],
        "business_rules": d.get("business_rules") or [],
        "dialects": d.get("dialects") or {},
        "source": str(_path()),
        "error": _load_error,
    }


def _relevant(question: str) -> list[dict]:
    q = (question or "").lower()
    out = []
    for m in metrics():
        syn = [str(s).lower() for s in (m.get("synonyms") or [])]
        if any(s and s in q for s in syn) or str(m.get("name", "")).lower() in q:
            out.append(m)
    return out[:6]


def prompt_block(question: str = "", dialect: str | None = None) -> str:
    """生成注入 system prompt 的口径块（只放与问题相关的指标，控制 token）。"""
    d = load()
    if not d:
        return FALLBACK_RULES
    lines = ["【受治理指标层（业务口径优先于字面理解）】"]
    for r in d.get("business_rules") or []:
        lines.append(f"- {r}")
    picked = _relevant(question)
    if picked:
        lines.append("【本轮可能用到的指标定义】")
        for m in picked:
            expr = m.get("expr") or ""
            flt = m.get("valid_filter")
            note = m.get("notes")
            lines.append(
                f"- {m.get('name')}（{m.get('id')}）：{expr}"
                + (f"；过滤：{flt}" if flt else "")
                + (f"；{note}" if note else "")
            )
    joins = d.get("joins") or []
    if joins:
        lines.append("【标准 JOIN 关系（必须按此连接）】")
        for j in joins[:10]:
            lines.append(f"- {j.get('on')}")
    dialect = dialect or settings.db_dialect
    dd = (d.get("dialects") or {}).get(dialect) or {}
    if dd:
        lines.append(
            f"【当前方言 {dialect}】按月用 {dd.get('date_month')}；"
            f"按天用 {dd.get('date_day')}。"
        )
    return "\n".join(lines) + "\n"


# ---------------- 写路径：在线编辑语义层（带备份与审计） ----------------
def save(data: dict, actor: str = "") -> dict:
    """整体写回语义层文件：先备份，原子替换。"""
    import yaml  # type: ignore
    before = catalog()
    clean = {
        "version": int(data.get("version") or before.get("version") or 1),
        "business_rules": [str(x) for x in (data.get("business_rules") or []) if str(x).strip()],
        "metrics": [m for m in (data.get("metrics") or []) if isinstance(m, dict) and m.get("id")],
        "joins": [j for j in (data.get("joins") or []) if isinstance(j, dict)],
        "dialects": data.get("dialects") or {},
    }
    p = _path()
    if p.exists():
        shutil.copy2(p, p.with_suffix(f".yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    os.replace(tmp, p)
    reset_cache()
    from . import audit
    audit.record(actor, "semantic.update", str(p),
                 before={"metrics": len(before.get("metrics") or []),
                         "rules": len(before.get("business_rules") or [])},
                 after={"metrics": len(clean["metrics"]),
                        "rules": len(clean["business_rules"])},
                 effective=True)
    return catalog()


def reset_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = -1.0


# ---------------- 编译层：指标 → 确定性 SQL 片段（Wren AI 式 MDL 编译） ----------------
def metric_by_id(mid: str) -> dict | None:
    for m in metrics():
        if str(m.get("id")) == str(mid):
            return m
    return None


def compiled_metric(mid: str, dialect: str | None = None) -> dict | None:
    """把受治理指标编译成可执行的 SQL 片段（表达式 + 过滤 + 表 + 粒度）。"""
    m = metric_by_id(mid)
    if not m:
        return None
    tables = list(m.get("tables") or ([m.get("table")] if m.get("table") else []))
    expr = str(m.get("expr") or "")
    filt = str(m.get("valid_filter") or "")
    grain = str(m.get("grain") or "")
    notes = str(m.get("notes") or "")
    return {
        "id": m.get("id"), "name": m.get("name"), "expr": expr,
        "valid_filter": filt, "tables": tables, "unit": m.get("unit"),
        "grain": grain, "notes": notes, "dialect": dialect or settings.db_dialect,
        "sql_snippet": _snippet(expr, filt, tables),
    }


def _snippet(expr: str, filt: str, tables: list[str]) -> str:
    if not expr:
        return ""
    base = tables[0] if tables else ""
    parts = [expr]
    if filt:
        parts.append(f"WHERE {filt}")
    return " ".join(parts) + (f"  -- 表：{', '.join(tables)}" if tables else "")


def compile_question(question: str, dialect: str | None = None) -> dict:
    """按问题匹配指标并编译出计划（dry-plan 的数据基础）。"""
    q = (question or "").lower()
    hit = None
    for m in metrics():
        syn = [str(x).lower() for x in (m.get("synonyms") or [])]
        name = str(m.get("name", "")).lower()
        if any(s and s in q for s in syn) or (name and name in q) \
                or str(m.get("id", "")).lower() in q:
            hit = m
            break
    if not hit:
        return {"matched": False, "metric": None, "sql_snippet": "",
                "tables": [], "reason": "未匹配到受治理指标，模型将按自由口径生成"}
    c = compiled_metric(hit.get("id"), dialect)
    c = c or {}
    c.update({"matched": True,
              "reason": f"命中指标「{hit.get('name')}」，请优先复用该表达式与过滤条件"})
    return c


def compile_prompt(question: str, dialect: str | None = None) -> str:
    """把编译结果渲染成可注入 prompt 的一段（只放命中的指标，控制 token）。"""
    c = compile_question(question, dialect)
    if not c.get("matched"):
        return ""
    lines = ["【已解析的受治理指标（编译结果，优先照抄，不要另起口径）】"]
    lines.append(f"- 指标：{c.get('name')}（{c.get('id')}）")
    lines.append(f"- 表达式：{c.get('expr')}")
    if c.get("valid_filter"):
        lines.append(f"- 有效过滤：{c.get('valid_filter')}")
    lines.append(f"- 涉及表：{', '.join(c.get('tables') or [])}")
    if c.get("notes"):
        lines.append(f"- 注意：{c.get('notes')}")
    return "\n".join(lines) + "\n"
