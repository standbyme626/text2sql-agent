#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小 MCP stdio server：把 Text-to-SQL Agent 的只读工具暴露给任意 MCP 客户端。

用法（Claude Code / opencode / 任意 MCP host）：
  {
    "mcpServers": {
      "text2sql": {
        "command": "python",
        "args": ["backend/mcp_server.py"],
        "env": {"TEXT2SQL_DATA_DIR": "/abs/path/backend/data"}
      }
    }
  }

协议：MCP 2025-06-18 / JSON-RPC 2.0，一行一个 JSON；stdout 只输出协议消息。
工具：search_schema / run_sql / list_metrics，全部复用与 Web Agent 相同的只读闸门。
"""
from __future__ import annotations

import asyncio
import json
import sys

from app import tools
from app.config import settings
from app.schema_index import SchemaIndex

PROTOCOL = "2025-06-18"
SERVER_INFO = {"name": "text2sql-agent", "version": "3.0.0"}
MCP_TOOLS = {"search_schema", "run_sql", "list_metrics"}
_IDX: SchemaIndex | None = None


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id, result) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id,
           "error": {"code": code, "message": message}})


def _tool_list() -> list[dict]:
    out = []
    for spec in tools.TOOL_SPECS:
        fn = spec["function"]
        if fn["name"] not in MCP_TOOLS:
            continue
        out.append({
            "name": fn["name"],
            "description": fn["description"],
            "inputSchema": fn["parameters"],
        })
    return out


async def _call(name: str, args: dict) -> dict:
    global _IDX
    if _IDX is None:
        _IDX = SchemaIndex()
    ctx = tools.ToolContext(_IDX)
    return await tools.execute(ctx, name, args)


def main() -> None:
    try:
        idx = SchemaIndex()
        sys.stderr.write(
            f"[text2sql-mcp] ready: {len(idx.order)} tables, "
            f"db={settings.db_dialect}, index={idx.mode}\n")
        sys.stderr.flush()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[text2sql-mcp] init failed: {e}\n")
        sys.stderr.flush()
        raise SystemExit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            _error(None, -32700, "Parse error")
            continue
        if not isinstance(req, dict):
            _error(None, -32600, "Invalid Request")
            continue
        method = req.get("method")
        req_id = req.get("id")
        if method == "initialize":
            _result(req_id, {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            _result(req_id, {})
        elif method == "tools/list":
            _result(req_id, {"tools": _tool_list()})
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in MCP_TOOLS:
                _error(req_id, -32602, f"Unknown tool: {name}")
                continue
            try:
                result = asyncio.run(_call(name, args))
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "error": str(e)[:200]}
            _result(req_id, {
                "content": [{"type": "text",
                             "text": json.dumps(result, ensure_ascii=False,
                                                default=str)}],
                "isError": not bool(result.get("ok")),
            })
        else:
            _error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
