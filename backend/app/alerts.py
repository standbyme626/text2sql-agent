# -*- coding: utf-8 -*-
"""告警规则与 SLO：规则写在 alerts.yaml（可在线编辑），每次打开总览实时评估。

规则格式：
  - id: p95_latency
    name: P95 延迟超阈值
    metric: latency_p95        # 见 METRICS
    op: ">"
    threshold: 60000
    level: amber               # rose / amber / info
    enabled: true
    desc: 单轮问答 P95 超过 60s
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import os

from .config import BACKEND_DIR

RULES_FILE = Path(os.getenv("TEXT2SQL_ALERTS_FILE")
                  or str(BACKEND_DIR / "alerts.yaml"))

DEFAULT_RULES = [
    {"id": "success_rate", "name": "成功率过低", "metric": "success_rate", "op": "<",
     "threshold": 0.9, "level": "rose", "enabled": True,
     "desc": "工具调用成功率低于 90%"},
    {"id": "p95_latency", "name": "P95 延迟超阈值", "metric": "latency_p95", "op": ">",
     "threshold": 60000, "level": "amber", "enabled": True,
     "desc": "单轮问答 P95 超过 60s"},
    {"id": "tool_failures", "name": "工具失败偏多", "metric": "tool_failures", "op": ">",
     "threshold": 3, "level": "amber", "enabled": True,
     "desc": "最近窗口内工具失败次数偏多"},
    {"id": "knowledge_empty", "name": "知识库未沉淀", "metric": "knowledge_empty", "op": ">=",
     "threshold": 1, "level": "info", "enabled": True,
     "desc": "还没有正式知识样例，few-shot 只靠自动积累"},
    {"id": "index_keyword", "name": "向量索引未就绪", "metric": "index_keyword", "op": ">=",
     "threshold": 1, "level": "amber", "enabled": True,
     "desc": "当前按关键词选表，向量索引不可用"},
    {"id": "fallback_missing", "name": "缺兜底模型", "metric": "fallback_missing", "op": ">=",
     "threshold": 1, "level": "amber", "enabled": True,
     "desc": "主模型故障时没有可切换的兜底模型"},
    {"id": "refusal_rate", "name": "拒答率偏高", "metric": "refusal_rate", "op": ">",
     "threshold": 0.3, "level": "info", "enabled": True,
     "desc": "超过三成提问被护栏拦下，可能是问法或知识覆盖问题"},
]

METRICS = {
    "success_rate", "refusal_rate", "error_rate", "latency_p50", "latency_p95",
    "tool_failures", "sql_failures", "traces", "llm_calls", "avg_llm_calls",
    "prompt_tokens", "knowledge_empty", "index_keyword", "fallback_missing",
    "semantic_error",
}


def _fallback_rules() -> list[dict]:
    return [dict(r) for r in DEFAULT_RULES]


def rules() -> list[dict]:
    p = RULES_FILE
    if not p.exists():
        return _fallback_rules()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
        if not isinstance(data, list):
            return _fallback_rules()
        out = []
        for r in data:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            if r.get("metric") not in METRICS:
                continue
            out.append({
                "id": str(r["id"]),
                "name": str(r.get("name") or r["id"]),
                "metric": str(r["metric"]),
                "op": str(r.get("op") or ">"),
                "threshold": r.get("threshold", 0),
                "level": str(r.get("level") or "amber"),
                "enabled": bool(r.get("enabled", True)),
                "desc": str(r.get("desc") or ""),
            })
        return out or _fallback_rules()
    except Exception:  # noqa: BLE001
        return _fallback_rules()


def save_rules(new_rules: list[dict], actor: str = "") -> list[dict]:
    """校验并原子写回 alerts.yaml。"""
    clean = []
    for r in new_rules or []:
        if not isinstance(r, dict):
            continue
        if r.get("metric") not in METRICS:
            raise ValueError(f"未知指标：{r.get('metric')}")
        if str(r.get("op")) not in ("<", ">", ">=", "<=", "==", "!="):
            raise ValueError("比较符只能是 < > >= <= == !=")
        clean.append({
            "id": str(r.get("id") or f"rule_{len(clean)+1}"),
            "name": str(r.get("name") or r.get("id") or "规则"),
            "metric": str(r["metric"]),
            "op": str(r["op"]),
            "threshold": r.get("threshold", 0),
            "level": str(r.get("level") or "amber"),
            "enabled": bool(r.get("enabled", True)),
            "desc": str(r.get("desc") or ""),
        })
    import yaml  # type: ignore
    p = RULES_FILE
    if p.exists():
        shutil.copy2(p, p.with_suffix(f".yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    os.replace(tmp, p)
    from . import audit
    audit.record(actor, "alerts.update", str(p),
                 before={"rules": rules()}, after={"rules": clean}, effective=True)
    return clean


def _value(metric: str, ctx: dict):
    metrics = ctx.get("metrics") or {}
    status = ctx.get("status") or {}
    if metric == "success_rate":
        return metrics.get("success_rate")
    if metric == "refusal_rate":
        return metrics.get("refusal_rate")
    if metric == "error_rate":
        return 1.0 - float(metrics.get("success_rate") or 0.0)
    if metric == "latency_p50":
        return (metrics.get("latency_ms") or {}).get("p50")
    if metric == "latency_p95":
        return (metrics.get("latency_ms") or {}).get("p95")
    if metric == "tool_failures":
        return metrics.get("tool_failures")
    if metric == "sql_failures":
        return max(0, int(metrics.get("sql_executions") or 0)
                   - int(metrics.get("sql_errors") or 0))
    if metric == "traces":
        return metrics.get("traces")
    if metric == "llm_calls":
        return metrics.get("llm_calls")
    if metric == "avg_llm_calls":
        return metrics.get("avg_llm_calls")
    if metric == "prompt_tokens":
        return metrics.get("prompt_tokens")
    if metric == "knowledge_empty":
        return 0 if (ctx.get("knowledge") or {}).get("sql") else 1
    if metric == "index_keyword":
        return 1 if status.get("index_mode") != "vector" else 0
    if metric == "fallback_missing":
        return 0 if len(status.get("llm_chain") or []) > 1 else 1
    if metric == "semantic_error":
        return 1 if status.get("semantic_error") else 0
    return None


_OPS = {
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate(ctx: dict) -> list[dict]:
    """按规则评估当前状态，返回命中的告警。"""
    out = []
    for r in rules():
        if not r.get("enabled"):
            continue
        val = _value(r["metric"], ctx)
        if val is None:
            continue
        try:
            hit = _OPS[r["op"]](float(val), float(r["threshold"]))
        except (TypeError, ValueError):
            continue
        if hit:
            out.append({
                "id": r["id"], "name": r["name"], "level": r["level"],
                "metric": r["metric"], "op": r["op"], "threshold": r["threshold"],
                "value": val, "desc": r["desc"],
            })
    order = {"rose": 0, "amber": 1, "info": 2}
    out.sort(key=lambda a: order.get(a["level"], 3))
    return out


def slo(ctx: dict) -> dict:
    """服务等级目标视图：可用性、延迟达标率、错误预算。"""
    metrics = ctx.get("metrics") or {}
    traces = int(metrics.get("traces") or 0)
    target_p95 = 60000.0
    p95 = float((metrics.get("latency_ms") or {}).get("p95") or 0.0)
    success = float(metrics.get("success_rate") or 0.0) if traces else None
    budget = 0.001  # 允许 0.1% 失败
    used = max(0.0, 1.0 - success)
    return {
        "availability": round(success * 100, 2) if success is not None else None,
        "availability_target": 99.9,
        "latency_p95_ms": p95,
        "latency_target_ms": target_p95,
        "latency_ok": p95 <= target_p95,
        "error_budget_pct": round(budget * 100, 3),
        "error_budget_used_pct": round(used * 100, 3) if success is not None else 0.0,
        "error_budget_remaining_pct": round(max(0.0, budget - used) * 100, 3),
        "traces": traces,
    }
