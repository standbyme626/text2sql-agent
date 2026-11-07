#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text-to-SQL Agent 评估：执行准确率（Execution Accuracy）+ 失败分类 + 延迟。

两种数据集：
  golden  本项目 50 表演示库 + eval/golden.yaml（默认，零外部依赖）
  bird    BIRD dev 子集（需自行下载数据集；真实模型模式下才有意义）

用法：
  python backend/scripts/eval.py --mode mock                 # 零 API 冒烟
  python backend/scripts/eval.py --mode real                 # 真实模型（消耗额度）
  python backend/scripts/eval.py --mode real --bird ~/BIRD/dev --limit 50

执行准确率 = 候选 SQL 与参考 SQL 的结果集一致（默认忽略行序；gold 含
ORDER BY+LIMIT 时按行序比较），不是字符串相似度。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
PROJECT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

MAX_EVAL_ROWS = 100_000


def _norm(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return v


def _rows(rows, ordered: bool):
    data = [tuple(_norm(x) for x in r) for r in rows]
    return data if ordered else sorted(data, key=lambda r: tuple(str(x) for x in r))


def exec_equal(gold: dict, cand: dict, ordered: bool = False) -> bool:
    if len(gold.get("columns") or []) != len(cand.get("columns") or []):
        return False
    return _rows(gold.get("rows") or [], ordered) == _rows(cand.get("rows") or [], ordered)


def _ordered(gold_sql: str) -> bool:
    s = (gold_sql or "").lower()
    return "order by" in s and "limit" in s


def _load_cases(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except ImportError:
        data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("cases") or []
    return [c for c in (data or []) if isinstance(c, dict) and c.get("question")]


def _write_report(report: dict, out: Path, markdown: bool = True) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        lines = [
            f"# Text-to-SQL Eval Report ({report['dataset']})",
            "",
            f"- 模式：**{report['mode']}**",
            f"- 用例：**{report['total']}**，正确：**{report['correct']}**",
            f"- Execution Accuracy：**{report['exec_accuracy']:.2%}**",
            f"- 平均延迟：**{report['avg_latency_ms']:.0f} ms**",
            f"- 失败分类：{json.dumps(report['taxonomy'], ensure_ascii=False)}",
            "",
            "| # | 问题 | 结果 | 耗时 | 说明 |",
            "|---|---|---|---|---|",
        ]
        for i, c in enumerate(report["cases"], 1):
            q = str(c.get("question", "")).replace("|", "\\|")[:60]
            lines.append(
                f"| {i} | {q} | {'✅' if c.get('correct') else '❌'} | "
                f"{c.get('latency_ms', 0):.0f}ms | {c.get('reason', '')} |")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


def _taxonomy(report: dict) -> None:
    tax: dict[str, int] = {}
    for c in report["cases"]:
        if not c.get("correct"):
            key = c.get("failure") or "wrong_result"
            tax[key] = tax.get(key, 0) + 1
    report["taxonomy"] = tax


async def run_golden(args) -> dict:
    mode = args.mode
    os.environ["MOCK_MODE"] = "true" if mode == "mock" else "false"
    os.environ.setdefault("AUTO_INSIGHT", "false")
    os.environ.setdefault("AGENT_MODE", "toolloop")
    tmp = Path(tempfile.mkdtemp(prefix="t2s-eval-"))
    for name in ("ecommerce.db", "schema_meta.json"):
        shutil.copy(BACKEND / "data" / name, tmp / name)
    os.environ["TEXT2SQL_DATA_DIR"] = str(tmp)

    from app import agent, db, tracing
    from app.schema_index import SchemaIndex
    from app.store import Store

    idx = SchemaIndex()
    store = Store()
    agent.setup(idx, store)
    tracing.reset()

    cases = _load_cases(args.cases)
    if args.limit:
        cases = cases[:args.limit]
    results = []
    started = time.perf_counter()
    for case in cases:
        q = case["question"]
        gold_sql = case.get("sql") or ""
        t0 = time.perf_counter()
        gold = None
        gold_error = ""
        if gold_sql:
            try:
                gold = db.execute_readonly(gold_sql, max_rows=MAX_EVAL_ROWS)
            except Exception as e:  # noqa: BLE001
                gold_error = str(e)[:160]

        events = []
        try:
            async for ev in agent.run_agent(q):
                events.append(ev)
        except Exception as e:  # noqa: BLE001
            events.append({"type": "error", "message": str(e)[:160]})
        latency = (time.perf_counter() - t0) * 1000

        result = next((e for e in events if e.get("type") == "result"), None)
        guidance = next((e for e in events if e.get("type") == "guidance"), None)
        err = next((e for e in events if e.get("type") == "error"), None)
        expect_refusal = bool(case.get("expect_refusal"))
        correct, failure, reason = False, "", ""

        if expect_refusal:
            correct = bool(guidance) and not result
            failure = "" if correct else "should_refuse"
            reason = "正确拒答" if correct else "未拒答"
        elif gold_error:
            failure, reason = "gold_sql_error", gold_error
        elif result is None:
            failure = "refusal" if guidance else ("error" if err else "no_result")
            reason = (guidance or err or {}).get("reason") or \
                     (guidance or err or {}).get("message") or "无结果"
        else:
            try:
                correct = exec_equal(gold, result, _ordered(gold_sql))
            except Exception as e:  # noqa: BLE001
                failure, reason = "compare_error", str(e)[:160]
            if not correct:
                failure = failure or "wrong_result"
                reason = "结果集不一致" if not failure else reason
            else:
                reason = "结果集一致"

        results.append({
            "id": case.get("id") or q[:20],
            "question": q,
            "category": case.get("category", "general"),
            "latency_ms": round(latency, 1),
            "correct": correct,
            "failure": failure,
            "reason": reason,
            "sql": (result or {}).get("sql") or "",
        })

    shutil.rmtree(tmp, ignore_errors=True)
    correct = sum(1 for r in results if r["correct"])
    report = {
        "dataset": "golden",
        "mode": mode,
        "total": len(results),
        "correct": correct,
        "exec_accuracy": correct / len(results) if results else 0.0,
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in results) / len(results), 1) if results else 0.0,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "cases": results,
        "taxonomy": {},
    }
    _taxonomy(report)
    by_cat: dict[str, dict] = {}
    for r in results:
        d = by_cat.setdefault(r["category"], {"total": 0, "correct": 0})
        d["total"] += 1
        d["correct"] += 1 if r["correct"] else 0
    report["by_category"] = by_cat
    return report


def _sqlite_meta(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        out = []
        for t in tables:
            name = t["name"]
            cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            fks = conn.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
            try:
                samples = [dict(r) for r in conn.execute(
                    f'SELECT * FROM "{name}" LIMIT 2').fetchall()]
            except sqlite3.Error:
                samples = []
            out.append({
                "name": name,
                "cn": name,
                "domain": "bird",
                "rows": 0,
                "fks": {f["from"]: [f["table"], f["to"]] for f in fks},
                "keywords": "",
                "columns": [{"name": c["name"], "type": c["type"] or "text",
                             "cn": c["name"]} for c in cols],
                "ddl": t["sql"] or "",
                "text": name + " " + " ".join(c["name"] for c in cols),
                "enums": {},
                "samples": samples,
            })
        return {"tables": out}
    finally:
        conn.close()


def _pick_tables(meta: dict, question: str, k: int = 8) -> list[dict]:
    q = question.lower()
    qg = {q[i:i + 2] for i in range(len(q) - 1) if q[i:i + 2].strip()}

    def score(t):
        text = (t["name"] + " " + " ".join(
            c["name"] + " " + c.get("cn", "") for c in t["columns"])).lower()
        hit = len(qg & {text[i:i + 2] for i in range(len(text) - 1)})
        return hit

    return sorted(meta["tables"], key=score, reverse=True)[:k]


async def run_bird(args) -> dict:
    mode = args.mode
    os.environ["MOCK_MODE"] = "true" if mode == "mock" else "false"
    from app import db, llm

    root = Path(args.bird).expanduser()
    dev_json = root / "dev.json" if root.is_dir() else root
    db_dir = dev_json.parent / "dev_databases"
    if not dev_json.exists():
        raise SystemExit(f"找不到 BIRD dev.json：{dev_json}")
    data = json.loads(dev_json.read_text(encoding="utf-8"))
    if args.limit:
        data = data[:args.limit]

    results = []
    started = time.perf_counter()
    for case in data:
        db_id = case.get("db_id") or ""
        db_path = db_dir / db_id / f"{db_id}.sqlite"
        gold_sql = case.get("SQL") or case.get("sql") or ""
        question = case.get("question") or ""
        t0 = time.perf_counter()
        failure, reason, correct = "", "", False
        cand_sql = ""
        if not db_path.exists():
            failure, reason = "db_missing", str(db_path)
        else:
            meta = _sqlite_meta(db_path)
            picked = _pick_tables(meta, question)
            ctx = "\n\n".join(
                f"### {t['name']}\n{t['ddl']}" for t in picked)
            messages = [
                {"role": "system", "content": (
                    "你是 SQLite 数据分析师。只输出一条 SELECT/WITH SQL，"
                    "用 ```sql 围栏包裹，不要解释；只能使用给定表。")},
                {"role": "user", "content": f"问题：{question}\n\n可用表：\n{ctx}\n\n"
                                             "请输出 SQL。"},
            ]
            try:
                raw = await llm.chat(messages)
                cand_sql = llm.extract_sql(raw)
                if not cand_sql:
                    failure, reason = "no_sql", "模型未输出 SQL"
                else:
                    gold = db.execute_readonly(gold_sql, max_rows=MAX_EVAL_ROWS,
                                               db_path=str(db_path))
                    cand = db.execute_readonly(cand_sql, max_rows=MAX_EVAL_ROWS,
                                               db_path=str(db_path))
                    correct = exec_equal(gold, cand, _ordered(gold_sql))
                    failure = "" if correct else "wrong_result"
                    reason = "结果集一致" if correct else "结果集不一致"
            except Exception as e:  # noqa: BLE001
                failure, reason = "sql_error", str(e)[:160]
        latency = (time.perf_counter() - t0) * 1000
        results.append({
            "id": case.get("question_id") or case.get("id") or "",
            "question": question,
            "category": case.get("difficulty") or "unknown",
            "difficulty": case.get("difficulty") or "unknown",
            "latency_ms": round(latency, 1),
            "correct": correct,
            "failure": failure,
            "reason": reason,
            "sql": cand_sql,
            "db_id": db_id,
        })

    correct = sum(1 for r in results if r["correct"])
    report = {
        "dataset": "bird",
        "mode": mode,
        "total": len(results),
        "correct": correct,
        "exec_accuracy": correct / len(results) if results else 0.0,
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in results) / len(results), 1) if results else 0.0,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "cases": results,
        "taxonomy": {},
    }
    _taxonomy(report)
    by_diff: dict[str, dict] = {}
    for r in results:
        d = by_diff.setdefault(r["difficulty"], {"total": 0, "correct": 0})
        d["total"] += 1
        d["correct"] += 1 if r["correct"] else 0
    report["by_difficulty"] = by_diff
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mock", "real"], default="mock")
    ap.add_argument("--cases", type=Path,
                    default=PROJECT / "eval" / "golden.yaml")
    ap.add_argument("--bird", default="", help="BIRD dev 目录或 dev.json 路径")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=PROJECT / "eval" / "report.json")
    ap.add_argument("--report", type=Path, default=PROJECT / "eval" / "report.md")
    args = ap.parse_args()

    if args.mode == "real" and not os.getenv("MODELSCOPE_API_KEY"):
        raise SystemExit("real 模式需要 MODELSCOPE_API_KEY（.env）")
    report = asyncio.run(run_bird(args) if args.bird else run_golden(args))
    _write_report(report, args.out, markdown=False)
    _write_report(report, args.report, markdown=True)
    print(json.dumps({
        "dataset": report["dataset"],
        "total": report["total"],
        "exec_accuracy": report["exec_accuracy"],
        "taxonomy": report["taxonomy"],
        "report": str(args.report),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
