# -*- coding: utf-8 -*-
"""语义层加载器：YAML 指标目录 → 可审计 prompt 块 / API catalog。

文件缺失或 YAML 解析失败时退回内置 BUSINESS_RULES，服务不中断。
"""
from __future__ import annotations

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
