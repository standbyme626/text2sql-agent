# -*- coding: utf-8 -*-
"""从现有 PostgreSQL 库内省生成 schema_meta.json（50 表 SQLite 演示库的 PG 等价物）。

用法：
    DATABASE_URL=postgresql://user:pass@host:5432/db \
        python backend/scripts/build_meta_pg.py

产物默认写入 backend/data/schema_meta.json，随后把同一 DATABASE_URL 配到 .env
即可让 Agent 以 Postgres 模式运行（只读 + statement_timeout）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

DEFAULT_META = settings.meta_path


def _type_name(c: dict) -> str:
    t = c.get("data_type") or "text"
    if t == "character varying" and c.get("character_maximum_length"):
        return f"varchar({c['character_maximum_length']})"
    if t == "numeric" and c.get("numeric_precision"):
        return f"numeric({c['numeric_precision']},{c.get('numeric_scale') or 0})"
    return t


def build(url: str, schema: str, out: Path, sample_rows: int = 2) -> dict:
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row
    except ImportError as e:
        raise SystemExit('需要 psycopg：pip install "psycopg[binary]"') from e

    with psycopg.connect(url, row_factory=dict_row) as conn:
        tables = conn.execute(
            "SELECT c.relname AS name, "
            "       COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment, "
            "       GREATEST(c.reltuples::bigint, 0) AS est_rows "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r','p') "
            "ORDER BY c.relname", (schema,)).fetchall()
        cols = conn.execute(
            "SELECT table_name, column_name, data_type, character_maximum_length, "
            "       numeric_precision, numeric_scale, is_nullable, column_default, "
            "       COALESCE(col_description((table_schema||'.'||table_name)::regclass, "
            "       ordinal_position), '') AS comment "
            "FROM information_schema.columns WHERE table_schema=%s "
            "ORDER BY table_name, ordinal_position", (schema,)).fetchall()
        pks = conn.execute(
            "SELECT tc.table_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            " AND kcu.table_schema = tc.table_schema "
            "WHERE tc.table_schema=%s AND tc.constraint_type='PRIMARY KEY' "
            "ORDER BY tc.table_name, kcu.ordinal_position", (schema,)).fetchall()
        fks = conn.execute(
            "SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table, "
            "       ccu.column_name AS ref_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            "WHERE tc.table_schema=%s AND tc.constraint_type='FOREIGN KEY'",
            (schema,)).fetchall()

    by_table: dict[str, list[dict]] = {}
    for c in cols:
        by_table.setdefault(c["table_name"], []).append(c)
    pk_map: dict[str, list[str]] = {}
    for p in pks:
        pk_map.setdefault(p["table_name"], []).append(p["column_name"])
    fk_map: dict[str, dict[str, list[str]]] = {}
    for f in fks:
        fk_map.setdefault(f["table_name"], {})[f["column_name"]] = [
            f["ref_table"], f["ref_column"]]

    out_tables = []
    for t in tables:
        name = t["name"]
        columns = by_table.get(name, [])
        if not columns:
            continue
        col_objs = [{
            "name": c["column_name"],
            "type": _type_name(c),
            "cn": c["comment"] or c["column_name"],
        } for c in columns]
        pk = (pk_map.get(name) or [columns[0]["column_name"]])[0]
        fk = fk_map.get(name, {})
        ddl_cols = []
        for c in columns:
            line = f'  "{c["column_name"]}" {_type_name(c)}'
            if c["column_name"] == pk:
                line += " PRIMARY KEY"
            if c.get("is_nullable") == "NO" and c["column_name"] != pk:
                line += " NOT NULL"
            ddl_cols.append(line)
        ddl = f'CREATE TABLE "{name}" (\n' + ",\n".join(ddl_cols) + "\n);"
        text = (f"数据表 {name}，中文名：{t['comment'] or name}。字段："
                + "；".join(f'{c["name"]}（{c["cn"]}）' for c in col_objs))
        out_tables.append({
            "name": name,
            "cn": t["comment"] or name,
            "domain": "postgres",
            "rows": int(t["est_rows"] or 0),
            "pk": pk,
            "fks": fk,
            "keywords": "",
            "columns": col_objs,
            "ddl": ddl,
            "text": text,
            "enums": {},
            "samples": [],
        })

    meta = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "dialect": "postgres",
        "db_path": "postgres",
        "total_tables": len(out_tables),
        "tables": out_tables,
    }
    if not out_tables:
        raise SystemExit(f"schema {schema} 没有可用的表")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("DATABASE_URL", ""))
    ap.add_argument("--schema", default="public")
    ap.add_argument("--out", default=str(DEFAULT_META))
    args = ap.parse_args()
    if not args.url:
        raise SystemExit("缺少 DATABASE_URL 或 --url")
    meta = build(args.url, args.schema, Path(args.out))
    print(f"OK: {meta['total_tables']} 张表 → {args.out}")


if __name__ == "__main__":
    main()
