# -*- coding: utf-8 -*-
"""轻量可观测层：trace / span / token 统计 / 延迟分位 / 工具失败率。

不引入 OTel SDK：输出 OTel 语义兼容的 JSONL（trace_id / span 名称 / 起止时间 /
属性），需要接 Langfuse / OTel Collector 时直接按行转发即可。数据落在
DATA_DIR/traces.jsonl（600），内存保留最近 N 条供 /api/metrics 聚合。
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .config import settings

_current: ContextVar["Trace | None"] = ContextVar("text2sql_trace", default=None)
_lock = threading.Lock()
_recent: "OrderedDict[str, dict]" = OrderedDict()


@dataclass
class Trace:
    name: str
    session_id: str = ""
    owner: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    started_at: float = field(default_factory=time.time)
    started_perf: float = field(default_factory=time.perf_counter)
    spans: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    meta: dict = field(default_factory=dict)
    status: str = "ok"
    finished: bool = False


def current() -> Trace | None:
    return _current.get()


def start_trace(name: str, session_id: str = "", owner: str = "") -> Trace:
    tr = Trace(name=name, session_id=session_id, owner=owner)
    _current.set(tr)
    return tr


@contextmanager
def span(name: str, **attrs):
    """同步上下文；yield 出的 dict 可在块内补充属性（如 row_count / ok）。"""
    tr = current()
    if tr is None:
        yield {}
        return
    extra: dict = {}
    t0 = time.perf_counter()
    try:
        yield extra
    finally:
        rec = {
            "name": name,
            "start_ms": round((t0 - tr.started_perf) * 1000, 2),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            **{k: v for k, v in attrs.items() if v is not None},
            **{k: v for k, v in extra.items() if v is not None},
        }
        tr.spans.append(rec)


def add_usage(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    tr = current()
    if tr is None:
        return
    tr.llm_calls += 1 if (prompt_tokens or completion_tokens) else 0
    tr.prompt_tokens += max(0, int(prompt_tokens or 0))
    tr.completion_tokens += max(0, int(completion_tokens or 0))


def _write(tr: Trace, payload: dict) -> None:
    if not settings.TRACE_ENABLED:
        return
    try:
        path = settings.app_db_path.parent / "traces.jsonl"
        os.makedirs(path.parent, exist_ok=True)
        with _lock:
            try:
                if path.stat().st_size > 10 * 1024 * 1024:
                    os.replace(path, path.with_suffix(".jsonl.1"))
            except OSError:
                pass
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    except OSError:
        pass


def finish_trace(tr: Trace | None = None, status: str = "ok", **meta) -> dict | None:
    tr = tr or current()
    if tr is None or tr.finished:
        return None
    tr.finished = True
    tr.status = status
    tr.meta.update(meta)
    payload = {
        "trace_id": tr.id,
        "name": tr.name,
        "session_id": tr.session_id,
        "owner": tr.owner,
        "status": status,
        "started_at": tr.started_at,
        "duration_ms": round((time.perf_counter() - tr.started_perf) * 1000, 2),
        "llm_calls": tr.llm_calls,
        "prompt_tokens": tr.prompt_tokens,
        "completion_tokens": tr.completion_tokens,
        "spans": tr.spans,
        "meta": tr.meta,
    }
    with _lock:
        _recent[tr.id] = payload
        while len(_recent) > settings.TRACE_RECENT:
            _recent.popitem(last=False)
    _write(tr, payload)
    _current.set(None)
    return payload


def get_trace(trace_id: str) -> dict | None:
    with _lock:
        hit = _recent.get(trace_id)
        if hit:
            return hit
    if not settings.TRACE_ENABLED:
        return None
    path = settings.app_db_path.parent / "traces.jsonl"
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-2000:]:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("trace_id") == trace_id:
                return d
    except OSError:
        return None
    return None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k], 2)


def metrics() -> dict:
    """基于最近 N 条 trace 的聚合指标；无需外部 TSDB。"""
    with _lock:
        rows = list(_recent.values())
    durations = [r["duration_ms"] for r in rows]
    spans = [s for r in rows for s in r.get("spans", [])]
    tool_spans = [s for s in spans if str(s.get("name", "")).startswith("tool.")]
    tool_fail = [s for s in tool_spans if s.get("ok") is False]
    sql_spans = [s for s in spans if s.get("name") == "tool.run_sql"]
    sql_fail = [s for s in sql_spans if s.get("ok") is False]
    by_tool: dict[str, int] = {}
    for s in tool_spans:
        n = str(s.get("name", "")).split(".", 1)[-1]
        by_tool[n] = by_tool.get(n, 0) + 1
    refused = sum(1 for r in rows if r.get("status") == "refused")
    failed = sum(1 for r in rows if r.get("status") == "error")
    llm_calls = sum(int(r.get("llm_calls") or 0) for r in rows)
    return {
        "traces": len(rows),
        "success_rate": round((len(rows) - failed) / len(rows), 4) if rows else 0.0,
        "refusal_rate": round(refused / len(rows), 4) if rows else 0.0,
        "latency_ms": {
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "max": round(max(durations), 2) if durations else 0.0,
        },
        "llm_calls": llm_calls,
        "avg_llm_calls": round(llm_calls / len(rows), 2) if rows else 0.0,
        "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
        "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in rows),
        "tool_calls": len(tool_spans),
        "tool_failures": len(tool_fail),
        "tool_breakdown": by_tool,
        "sql_executions": len(sql_spans),
        "sql_errors": len(sql_fail),
        "recent": rows[-5:],
    }


def reset() -> None:
    """仅测试用：清空内存 trace。"""
    with _lock:
        _recent.clear()
    _current.set(None)
