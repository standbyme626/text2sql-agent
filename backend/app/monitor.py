# -*- coding: utf-8 -*-
"""监控聚合：趋势、用量与成本、失败分布、未命中问题、索引状态。

数据来源都在本地：traces.jsonl（span/token/延迟）、app.db（会话与消息）、
knowledge/（知识沉淀量）。不引入任何外部监控服务。
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .config import settings

# 每百万 token 单价（美元）；未知模型按 0 计
PRICING = {
    "deepseek-v4.1-flash": (0.15, 0.60),
    "deepseek-v4-flash": (0.15, 0.60),
    "baidu/ernie-5.5-flash-preview:free": (0.0, 0.0),
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.0, 0.0),
}


def _traces_path() -> Path:
    return settings.app_db_path.parent / "traces.jsonl"


def read_traces(max_lines: int = 5000) -> list[dict]:
    p = _traces_path()
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-max_lines:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def trends(days: int = 14) -> dict:
    """近 N 天按天的调用量、成功率、延迟、token。"""
    days = max(1, min(int(days or 14), 90))
    cutoff = time.time() - days * 86400
    buckets: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "ok": 0, "failed": 0, "refused": 0,
        "durations": [], "prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0})
    for t in read_traces():
        ts = float(t.get("started_at") or 0)
        if ts < cutoff:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        b = buckets[day]
        b["total"] += 1
        st = t.get("status")
        if st == "ok":
            b["ok"] += 1
        elif st == "refused":
            b["refused"] += 1
        else:
            b["failed"] += 1
        b["durations"].append(float(t.get("duration_ms") or 0))
        b["prompt_tokens"] += int(t.get("prompt_tokens") or 0)
        b["completion_tokens"] += int(t.get("completion_tokens") or 0)
        b["llm_calls"] += int(t.get("llm_calls") or 0)
    out = []
    for day in sorted(buckets):
        b = buckets[day]
        ds = sorted(b.pop("durations"))
        def pct(p):
            if not ds:
                return 0.0
            k = max(0, min(len(ds) - 1, int(round((p / 100) * (len(ds) - 1)))))
            return round(ds[k], 2)
        b["p50"] = pct(50)
        b["p95"] = pct(95)
        b["success_rate"] = round((b["ok"] + b["refused"]) / b["total"], 4) if b["total"] else 0
        out.append({"date": day, **b})
    return {"days": out, "window_days": days}


def usage() -> dict:
    """按 provider / 模型统计调用次数、token 与估算成本。"""
    per: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "errors": 0})
    for t in read_traces():
        for s in t.get("spans") or []:
            if s.get("name") != "llm.chat":
                continue
            prov, mod = s.get("provider"), s.get("model")
            key = f"{prov} / {mod}" if prov and mod else (mod or prov or "unknown")
            rec = per[key]
            rec["calls"] += 1
            rec["prompt_tokens"] += int(s.get("prompt_tokens") or 0)
            rec["completion_tokens"] += int(s.get("completion_tokens") or 0)
            if s.get("ok") is False:
                rec["errors"] += 1
    rows = []
    total_cost = 0.0
    for key, rec in per.items():
        model = key.split("/")[-1].strip()
        pin, pout = PRICING.get(model, (0.0, 0.0))
        cost = (rec["prompt_tokens"] / 1_000_000) * pin + \
               (rec["completion_tokens"] / 1_000_000) * pout
        total_cost += cost
        rows.append({**rec, "target": key, "cost_usd": round(cost, 6)})
    rows.sort(key=lambda r: -r["calls"])
    return {
        "providers": rows,
        "totals": {
            "calls": sum(r["calls"] for r in rows),
            "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
            "completion_tokens": sum(r["completion_tokens"] for r in rows),
            "errors": sum(r["errors"] for r in rows),
            "cost_usd": round(total_cost, 6),
        },
    }


def failures() -> dict:
    """失败分布：按 trace 状态 + 工具失败原因归类。"""
    statuses = Counter()
    tools = Counter()
    for t in read_traces():
        statuses[t.get("status") or "unknown"] += 1
        for s in t.get("spans") or []:
            if str(s.get("name", "")).startswith("tool.") and s.get("ok") is False:
                err = str(s.get("error") or "")[:60] or "未知错误"
                tools[err] += 1
    return {"status": dict(statuses), "tool_errors": dict(tools)}


def index_stats() -> dict:
    """向量索引状态：模式、表数、向量数、维度、文件大小与重建时间。"""
    p = settings.index_path
    stat = None
    try:
        st = p.stat()
        stat = {"size_kb": round(st.st_size / 1024, 1), "built_at": datetime.fromtimestamp(
            st.st_mtime).isoformat(timespec="seconds")}
    except OSError:
        pass
    return {
        "path": str(p),
        "exists": p.exists(),
        "mode": "vector" if p.exists() else "keyword",
        "detail": stat or {},
        "embedding_model": settings.EMB_MODEL,
        "embedding_dim": settings.EMB_DIM,
        "rebuild_cooldown": settings.REBUILD_COOLDOWN,
    }
