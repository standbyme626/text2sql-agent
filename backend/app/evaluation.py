# -*- coding: utf-8 -*-
"""质量评测接入：把 eval.py 的 golden 评测变成后台可一键触发、可对比的任务。

- 评测在独立子进程里跑（脚本会自己复制数据目录并切 MOCK_MODE），不污染线上进程；
- 结果落 app.db 的 eval_runs 表，后台可看历史与 A/B 对比；
- 任务状态在内存里跟踪（running / done / failed）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .config import BACKEND_DIR, PROJECT_DIR, settings

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
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
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                label TEXT,
                mode TEXT,
                dataset TEXT,
                total INTEGER,
                correct INTEGER,
                exec_accuracy REAL,
                taxonomy TEXT,
                duration_ms INTEGER,
                note TEXT
            )
        """)
        c.commit()
    finally:
        c.close()
    _INIT = True


def runs(limit: int = 30) -> list[dict]:
    _init()
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?",
                         (max(1, min(limit, 200)),)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["taxonomy"] = json.loads(d.get("taxonomy") or "{}")
            except (ValueError, TypeError):
                d["taxonomy"] = {}
            out.append(d)
        return out
    finally:
        c.close()


def _save_run(label: str, mode: str, report: dict, duration_ms: int, note: str = "") -> int:
    _init()
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO eval_runs(ts,label,mode,dataset,total,correct,exec_accuracy,"
            "taxonomy,duration_ms,note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), label, mode, report.get("dataset", "golden"),
             int(report.get("total") or 0), int(report.get("correct") or 0),
             float(report.get("exec_accuracy") or 0.0),
             json.dumps(report.get("taxonomy") or {}, ensure_ascii=False),
             duration_ms, note))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def _run_eval(mode: str, label: str, note: str = "") -> dict:
    out_dir = Path(tempfile.mkdtemp(prefix="t2s-evalrun-"))
    report_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    cmd = [sys.executable, str(BACKEND_DIR / "scripts" / "eval.py"),
           "--mode", mode, "--out", str(report_path), "--report", str(md_path)]
    t0 = time.time()
    env = dict(os.environ)
    env.setdefault("TEXT2SQL_NO_DOTENV", "1")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=str(PROJECT_DIR), env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "评测进程失败")[-400:])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    duration = int((time.time() - t0) * 1000)
    rid = _save_run(label or f"{mode} 评测", mode, report, duration, note)
    return {
        "run_id": rid, "label": label, "mode": mode,
        "dataset": report.get("dataset"), "total": report.get("total"),
        "correct": report.get("correct"),
        "exec_accuracy": report.get("exec_accuracy"),
        "taxonomy": report.get("taxonomy") or {},
        "avg_latency_ms": report.get("avg_latency_ms"),
        "duration_ms": duration,
        "report_md": md_path.read_text(encoding="utf-8")[:8000],
    }


def _job(job_id: str) -> dict:
    with _jobs_lock:
        return dict(_jobs.get(job_id) or {})


def start(label: str = "", mode: str = "mock", note: str = "") -> dict:
    """异步启动一次评测，返回 job id。"""
    if mode not in ("mock", "real"):
        raise ValueError("mode 只能是 mock / real")
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"job_id": job_id, "state": "running", "label": label,
                         "mode": mode, "started_at": _now(), "result": None, "error": ""}
    note_txt = note

    def worker():
        try:
            res = _run_eval(mode, label or f"{mode} 评测", note_txt)
            with _jobs_lock:
                _jobs[job_id].update(state="done", finished_at=_now(), result=res)
        except Exception as e:  # noqa: BLE001
            with _jobs_lock:
                _jobs[job_id].update(state="failed", finished_at=_now(),
                                      error=str(e)[-300:])

    threading.Thread(target=worker, daemon=True).start()
    return _job(job_id)


def job(job_id: str) -> dict:
    return _job(job_id)


def jobs(limit: int = 20) -> list[dict]:
    with _jobs_lock:
        items = sorted(_jobs.values(), key=lambda j: j.get("started_at") or "",
                       reverse=True)
    return items[:max(1, min(limit, 100))]


def compare(run_a: int, run_b: int) -> dict:
    """两次评测的 A/B 对比。"""
    rows = {r["id"]: r for r in runs(200)}
    a, b = rows.get(int(run_a)), rows.get(int(run_b))
    if not a or not b:
        raise ValueError("评测记录不存在")
    tax_a = a.get("taxonomy") or {}
    tax_b = b.get("taxonomy") or {}
    keys = sorted(set(tax_a) | set(tax_b))
    return {
        "a": a, "b": b,
        "delta_accuracy": round(float(b.get("exec_accuracy") or 0)
                                - float(a.get("exec_accuracy") or 0), 4),
        "failure_diff": {k: (int(tax_b.get(k, 0)) - int(tax_a.get(k, 0))) for k in keys},
    }
