# -*- coding: utf-8 -*-
"""FastAPI 入口：鉴权 / 限流 / SSE 查询 / 只读 SQL / 会话 / 索引 / 静态前端。"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import (agent, alerts, audit, auth, config_admin, db, evaluation, knowledge,
               llm, monitor, policy, prompts, semantic, tools, tracing)
from .auth import make_token, require_admin, require_auth, verify_login
from .config import STATIC_DIR, settings
from .embedding import last_error
from .models import (AccountsReq, AlertsReq, ConfigUpdateReq, EvalRunReq, ExplainReq,
                     FromMessageReq, KnowledgeRuleReq, KnowledgeSqlReq, LoginReq,
                     MemoryReq, PolicyReq, PromptReq, QueryReq, SemanticReq, SqlReq)
from .schema_index import SchemaIndex
from .store import Store

logger = logging.getLogger("text2sql.api")

_last_rebuild = 0.0
_rebuild_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 公网可达性来自反向隧道 + nginx，与 settings.HOST 无关：无条件要求鉴权
    # 唯一例外是 MOCK_MODE（纯本地、零外部调用的演示/自测）
    if (not settings.auth_enabled and not settings.ALLOW_INSECURE
            and not settings.MOCK_MODE):
        raise RuntimeError(
            "未配置 AUTH_PASSWORD：本服务经反向隧道对公网可达，必须设置登录密码。"
            "请在项目根 .env 配置后重启；仅本地 MOCK_MODE 演示或显式 ALLOW_INSECURE=1 可跳过。"
        )
    if not settings.is_postgres and not settings.db_path.exists():
        raise RuntimeError("数据库未初始化，请先运行：python backend/scripts/init_db.py")
    if not settings.meta_path.exists():
        raise RuntimeError(
            "schema_meta.json 不存在：SQLite 跑 init_db.py；Postgres 跑 "
            "backend/scripts/build_meta_pg.py")

    idx = SchemaIndex()
    st = Store()
    agent.setup(idx, st)
    app.state.index = idx
    app.state.store = st
    # AUTO_BUILD_INDEX 不再只是摆设：索引缺失/损坏时真正重建一次（正常启动不触发）
    if (settings.AUTO_BUILD_INDEX and idx.mode != "vector"
            and idx.load_error and settings.emb_ready and not settings.MOCK_MODE):
        try:
            await idx.build()
            logger.info("schema 索引已自动重建")
        except Exception:  # noqa: BLE001
            logger.exception("自动重建索引失败，继续以关键词选表运行")
    print(f"[text2sql] 表 {len(idx.order)} 张 | 选表模式 {idx.mode} | "
          f"Agent {settings.AGENT_MODE} | DB {settings.db_dialect} | "
          f"LLM {'mock' if settings.MOCK_MODE else ('就绪' if settings.LLM_API_KEY else '缺 key')} | "
          f"鉴权 {'开启' if settings.auth_enabled else '关闭'}")
    yield


app = FastAPI(title="Text-to-SQL Agent", version="3.2.0", lifespan=lifespan)

_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,          # 留空 = 仅同源，不再默认允许任意来源
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-App-Token", "Authorization"],
)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    raw = request.headers.get("content-length", "")
    if raw and raw.isdigit() and int(raw) > settings.MAX_BODY_BYTES:
        return HTMLResponse("请求体过大", status_code=413)
    return await call_next(request)


def _need_index() -> SchemaIndex:
    idx = getattr(app.state, "index", None)
    if idx is None:
        raise HTTPException(503, "服务尚未就绪")
    return idx


def _need_store() -> Store:
    st = getattr(app.state, "store", None)
    if st is None:
        raise HTTPException(503, "服务尚未就绪")
    return st


def _rate_limited(request: Request, user: str = Depends(require_auth)) -> str:
    key = f"{user}@{auth.client_ip(request)}"
    if not auth.rate_ok(key):
        raise HTTPException(429, "请求过于频繁，请稍后再试")
    return user


def _client_error(e: Exception, fallback: str) -> str:
    """上游/内部异常只写日志，给客户端稳定泛化文案。"""
    logger.exception(fallback, exc_info=e)
    return fallback


# ---------------- 基础 ----------------
@app.get("/api/health")
def health():
    """公开端点只暴露最少信息，不给撞库提供账号与内部指纹。"""
    return {"ok": True, "auth_enabled": settings.auth_enabled}


def _status_payload(user: str = "") -> dict:
    idx = getattr(app.state, "index", None)
    return {
        "user": user,
        "role": settings.role_of(user) if user else "",
        "mock_mode": settings.MOCK_MODE,
        "llm_model": settings.LLM_MODEL,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_chain": llm.providers_info(),
        "emb_model": settings.EMB_MODEL,
        "llm_ready": settings.llm_ready,
        "emb_ready": settings.emb_ready,
        "index_mode": idx.mode if idx else "loading",
        "indexed_tables": len(idx.vectors) if idx else 0,
        "table_count": len(idx.order) if idx else 0,
        "index_error": (idx.load_error if idx else "") or last_error(),
        "auto_insight": settings.AUTO_INSIGHT,
        "followup_count": settings.FOLLOWUP_COUNT,
        "empty_result_retry": settings.EMPTY_RESULT_RETRY,
        "guard_enabled": settings.GUARD_ENABLED,
        "max_rows": settings.MAX_RESULT_ROWS,
        "agent_mode": settings.AGENT_MODE,
        "db_dialect": settings.db_dialect,
        "tools": tools.tool_names(),
        "memory_enabled": settings.MEMORY_ENABLED,
        "trace_enabled": settings.TRACE_ENABLED,
        "semantic_metrics": len(semantic.metrics()),
        "semantic_error": semantic.last_error(),
        "knowledge": knowledge.stats(),
        "max_llm_calls": settings.MAX_LLM_CALLS,
    }


@app.get("/api/status")
def status(user: str = Depends(require_auth)):
    """登录后才可见的运行状态（模型、索引、开关）。"""
    return _status_payload(user)


@app.get("/api/config")
def public_config(user: str = Depends(require_auth)):
    return {
        "user": user,
        "role": settings.role_of(user),
        "llm_model": settings.LLM_MODEL,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_chain": llm.providers_info(),
        "emb_model": settings.EMB_MODEL,
        "top_k_tables": settings.TOP_K_TABLES,
        "max_rows": settings.MAX_RESULT_ROWS,
        "mock_mode": settings.MOCK_MODE,
        "auth_enabled": settings.auth_enabled,
        "auto_insight": settings.AUTO_INSIGHT,
        "followup_count": settings.FOLLOWUP_COUNT,
        "agent_mode": settings.AGENT_MODE,
        "db_dialect": settings.db_dialect,
        "tools": tools.tool_names(),
    }


@app.post("/api/login")
def login(req: LoginReq, request: Request):
    if not settings.auth_enabled:
        return {"token": "", "auth_required": False}
    ip = auth.client_ip(request)
    if auth.login_blocked(ip):
        raise HTTPException(429, "尝试次数过多，请 1 分钟后再试")
    if not verify_login(req.username, req.password):
        auth.note_login_failure(ip)
        raise HTTPException(401, "用户名或密码错误")
    auth.clear_login_failures(ip)
    return {"token": make_token(req.username), "auth_required": True,
            "username": req.username, "role": settings.role_of(req.username)}


@app.post("/api/logout")
def logout(x_app_token: str | None = Header(default=None, alias="X-App-Token")):
    auth.revoke_token(x_app_token or "")
    return {"ok": True}


# ---------------- 表结构 ----------------
@app.get("/api/meta")
def meta(_: str = Depends(require_auth)):
    idx = _need_index()
    return {"total": len(idx.order), "tables": idx.brief(),
            "index_mode": idx.mode, "dialect": settings.db_dialect}


# ---------------- 语义层 / 工具 / 可观测性 / 记忆 ----------------
@app.get("/api/semantic")
def semantic_catalog(_: str = Depends(require_auth)):
    return semantic.catalog()


@app.get("/api/tools")
def tool_catalog(_: str = Depends(require_auth)):
    return {"tools": tools.TOOL_SPECS, "mode": settings.AGENT_MODE}


@app.get("/api/metrics")
def metrics(_: str = Depends(require_auth)):
    return tracing.metrics()


@app.get("/api/traces/{trace_id}")
def trace_detail(trace_id: str, _: str = Depends(require_auth)):
    if not trace_id.replace("-", "").isalnum() or len(trace_id) > 64:
        raise HTTPException(400, "非法 trace id")
    tr = tracing.get_trace(trace_id)
    if not tr:
        raise HTTPException(404, "trace 不存在或已过期")
    return tr


@app.get("/api/memory")
def list_memory(user: str = Depends(require_auth)):
    return {"memory": _need_store().list_memory(user)}


@app.post("/api/memory")
def add_memory(req: MemoryReq, user: str = Depends(require_auth)):
    mid = _need_store().add_memory(user, req.text)
    return {"ok": True, "id": mid}


@app.delete("/api/memory/{mid}")
def delete_memory(mid: int, user: str = Depends(require_auth)):
    return {"ok": _need_store().delete_memory(user, mid)}


@app.delete("/api/memory")
def clear_memory(user: str = Depends(require_auth)):
    _need_store().clear_memory(user)
    return {"ok": True}


@app.get("/api/tables/{name}")
def table_detail(name: str, _: str = Depends(require_auth)):
    idx = _need_index()
    t = idx.tables.get(name)
    if not t:
        raise HTTPException(404, "表不存在")
    try:
        sample = db.table_sample(name, 5)
    except Exception as e:  # noqa: BLE001
        sample = {"columns": [], "rows": [], "error": _client_error(e, "样例读取失败")}
    return {
        "name": name, "cn": t["cn"], "domain": t["domain"], "rows": t["rows"],
        "ddl": t["ddl"], "columns": t["columns"], "enums": t.get("enums", {}),
        "fks": t.get("fks", {}), "keywords": t.get("keywords", ""),
        "sample": sample,
    }


# ---------------- 核心查询 ----------------
@app.post("/api/query")
async def query(req: QueryReq, user: str = Depends(_rate_limited)):
    async def gen():
        q: asyncio.Queue = asyncio.Queue()

        async def produce():
            try:
                async for ev in agent.run_agent(req.question, req.session_id, owner=user):
                    await q.put(ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                _client_error(e, "流式查询异常")
                await q.put({"type": "error", "message": "本次查询未完成，请稍后重试。"})
            finally:
                await q.put(None)

        task = asyncio.create_task(produce())
        sent_done = False
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=settings.SSE_HEARTBEAT_SEC)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"   # 长生成阶段防中间层判空闲断流
                    continue
                if ev is None:
                    break
                if ev.get("type") == "done":
                    sent_done = True
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            if not sent_done:
                yield "data: " + json.dumps(
                    {"type": "done", "session_id": req.session_id or "", "incomplete": True},
                    ensure_ascii=False) + "\n\n"
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.post("/api/sql")
def run_sql(req: SqlReq, user: str = Depends(_rate_limited)):
    """前端编辑 SQL 后重跑：同样受只读闸门约束，并把结果回写会话。"""
    try:
        res = db.execute_readonly(req.sql)
        res["chart"] = db.chart_hint(res["columns"], res["rows"])
        if req.session_id and req.message_id:
            _need_store().patch_rerun(req.session_id, req.message_id, res)
        return res
    except (db.SqlRejected, db.SqlTimeout) as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, _client_error(e, "SQL 执行失败，请检查语句")) from e


@app.post("/api/explain")
async def explain(req: ExplainReq, _: str = Depends(_rate_limited)):
    try:
        return await agent.explain_result(req.question, req.sql, req.columns, req.rows,
                                          truncated=req.truncated)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _client_error(e, "解读失败，请稍后重试")) from e


# ---------------- 会话 ----------------
@app.get("/api/sessions")
def sessions(user: str = Depends(require_auth)):
    return {"sessions": _need_store().list_sessions(owner=user)}


@app.get("/api/history")
def history(session_id: str, user: str = Depends(require_auth)):
    return {"history": _need_store().get_history(session_id, 20, owner=user)}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, user: str = Depends(require_auth)):
    _need_store().delete_session(session_id, owner=user)
    return {"ok": True}


# ---------------- 向量索引 ----------------
@app.post("/api/index/rebuild")
async def rebuild_index(_: str = Depends(_rate_limited)):
    """显式触发，会调用一次硅基流动 embedding（50 条文本）；带冷却与原子写。"""
    global _last_rebuild
    with _rebuild_lock:
        if time.time() - _last_rebuild < settings.REBUILD_COOLDOWN:
            raise HTTPException(429, "索引刚重建过，请稍后再试")
        _last_rebuild = time.time()
    try:
        return await _need_index().build()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _client_error(e, "索引重建失败，已保留原索引")) from e


# ---------------- 管理后台 ----------------
@app.get("/api/admin/knowledge")
def admin_knowledge(_: str = Depends(require_admin)):
    return {"sql": knowledge.examples(), "rules": knowledge.rules(),
            "stats": knowledge.stats()}


@app.post("/api/admin/knowledge/sql")
def admin_add_sql(req: KnowledgeSqlReq, user: str = Depends(require_admin)):
    try:
        sql = db.clean_sql(req.sql)
    except db.SqlRejected as e:
        raise HTTPException(400, str(e)) from e
    try:
        item = knowledge.add_example(
            req.question, sql, tables=req.tables, notes=req.notes,
            source=f"admin:{user}")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item, "stats": knowledge.stats()}


@app.post("/api/admin/knowledge/from-message")
def admin_knowledge_from_message(req: FromMessageReq,
                                 user: str = Depends(require_admin)):
    msg = _need_store().message_with_question(req.message_id)
    if not msg or msg.get("role") != "assistant":
        raise HTTPException(404, "消息不存在或不是回答")
    question = (msg.get("question") or "").strip()
    sql = (msg.get("sql") or "").strip()
    if not question or not sql:
        raise HTTPException(400, "该回答缺少问题或 SQL，无法收录")
    try:
        sql = db.clean_sql(sql)
        item = knowledge.add_example(
            question, sql, tables=list(msg.get("tables") or []),
            notes=req.notes,
            source=f"session:{msg.get('session_id')}#{req.message_id}")
    except (db.SqlRejected, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item, "stats": knowledge.stats()}


@app.delete("/api/admin/knowledge/sql/{kid}")
def admin_delete_sql(kid: str, _: str = Depends(require_admin)):
    if not knowledge.delete_example(kid):
        raise HTTPException(404, "知识样例不存在")
    return {"ok": True, "stats": knowledge.stats()}


@app.post("/api/admin/knowledge/rules")
def admin_add_rule(req: KnowledgeRuleReq, user: str = Depends(require_admin)):
    try:
        item = knowledge.add_rule(req.text, title=req.title,
                                  source=f"admin:{user}")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item, "stats": knowledge.stats()}


@app.delete("/api/admin/knowledge/rules/{kid}")
def admin_delete_rule(kid: str, _: str = Depends(require_admin)):
    if not knowledge.delete_rule(kid):
        raise HTTPException(404, "规则不存在")
    return {"ok": True, "stats": knowledge.stats()}


@app.get("/api/admin/sessions")
def admin_sessions(_: str = Depends(require_admin)):
    return {"sessions": _need_store().list_sessions(limit=500)}


@app.get("/api/admin/history")
def admin_history(session_id: str, _: str = Depends(require_admin)):
    return {"history": _need_store().get_history(session_id, 50, owner=None)}


@app.delete("/api/admin/sessions/{session_id}")
def admin_delete_session(session_id: str, _: str = Depends(require_admin)):
    _need_store().delete_session(session_id, owner=None)
    return {"ok": True}


@app.get("/api/admin/traces")
def admin_traces(_: str = Depends(require_admin)):
    m = tracing.metrics()
    return {"recent": m.get("recent") or [], "traces": m.get("traces", 0)}


@app.get("/api/admin/users")
def admin_users(_: str = Depends(require_admin)):
    return {"users": [{"username": u, "role": v["role"]}
                      for u, v in settings.auth_users.items()]}


# ---------------- 管理端：监控 ----------------
def _alert_ctx() -> dict:
    m = tracing.metrics()
    return {"metrics": m, "status": _status_payload(), "knowledge": knowledge.stats()}


@app.get("/api/admin/overview")
def admin_overview(user: str = Depends(require_admin)):
    ctx = _alert_ctx()
    st = _need_store()
    return {
        "version": app.version,
        "status": ctx["status"],
        "metrics": ctx["metrics"],
        "alerts": alerts.evaluate(ctx),
        "slo": alerts.slo(ctx),
        "usage": monitor.usage(),
        "failures": monitor.failures(),
        "trends": monitor.trends(),
        "index": monitor.index_stats(),
        "knowledge": ctx["knowledge"],
        "sessions": st.count_sessions(),
        "recent_traces": (ctx["metrics"].get("recent") or [])[:10],
        "users": [{"username": u, "role": v["role"]}
                  for u, v in settings.auth_users.items()],
        "llm_chain": llm.providers_info(),
        "audit_count": audit.count(),
    }


@app.get("/api/admin/alerts")
def admin_alerts(_: str = Depends(require_admin)):
    ctx = _alert_ctx()
    return {"rules": alerts.rules(), "fired": alerts.evaluate(ctx), "slo": alerts.slo(ctx)}


@app.put("/api/admin/alerts")
def admin_put_alerts(req: AlertsReq, user: str = Depends(require_admin)):
    try:
        rules = alerts.save_rules(req.rules, actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ctx = _alert_ctx()
    return {"ok": True, "rules": rules, "fired": alerts.evaluate(ctx)}


@app.get("/api/admin/trends")
def admin_trends(days: int = 14, _: str = Depends(require_admin)):
    return monitor.trends(days)


@app.get("/api/admin/usage")
def admin_usage(_: str = Depends(require_admin)):
    return monitor.usage()


@app.get("/api/admin/failures")
def admin_failures(_: str = Depends(require_admin)):
    return monitor.failures()


@app.get("/api/admin/unmatched")
def admin_unmatched(limit: int = 50, _: str = Depends(require_admin)):
    """未命中/失败问题清单：护栏拒答、0 行、SQL 报错、未完成。"""
    items = _need_store().unmatched(limit)
    for it in items:
        it["knowledge"] = knowledge.recall(it.get("question", ""), 2)
    return {"items": items}


@app.post("/api/admin/unmatched/promote")
def admin_promote_unmatched(req: KnowledgeSqlReq, user: str = Depends(require_admin)):
    """把未命中问题收录为正式样例（SQL 必填，走只读闸门校验）。"""
    try:
        sql = db.clean_sql(req.sql)
    except db.SqlRejected as e:
        raise HTTPException(400, str(e)) from e
    try:
        item = knowledge.add_example(req.question, sql, tables=req.tables,
                                     notes=req.notes, source=f"unmatched:{user}")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item, "stats": knowledge.stats()}


@app.get("/api/admin/debug/tables")
async def admin_debug_tables(question: str, _: str = Depends(require_admin)):
    """检索调试：单条问句的选表打分明细（向量分/关键词分/列级分/外键闭包）。"""
    if not question.strip():
        raise HTTPException(400, "question 不能为空")
    idx = _need_index()
    qvec = None
    if idx.mode == "vector":
        from .embedding import embed_one
        qvec = await embed_one(question)
    tables = await idx.search(question, qvec=qvec)
    plan = semantic.compile_question(question)
    return {
        "question": question,
        "index_mode": idx.mode,
        "tables": tables,
        "matched_columns": {t["name"]: t.get("matched_columns") or [] for t in tables},
        "plan": plan,
        "knowledge_recall": knowledge.recall(question, 3),
    }


@app.get("/api/admin/knowledge/recall")
def admin_recall(question: str, k: int = 3, _: str = Depends(require_admin)):
    """知识召回调试：看词法召回命中了什么。"""
    return {"question": question, "items": knowledge.recall(question, k),
            "rules": knowledge.rules()}


# ---------------- 管理端：配置 ----------------
@app.get("/api/admin/config")
def admin_config(_: str = Depends(require_admin)):
    return {"catalog": config_admin.catalog(), "current": config_admin.current(),
            "env_path": str(config_admin.env_path())}


@app.post("/api/admin/config")
def admin_apply_config(req: ConfigUpdateReq, user: str = Depends(require_admin)):
    try:
        res = config_admin.apply(user, req.changes, note=req.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **res, "current": config_admin.current()}


@app.get("/api/admin/accounts")
def admin_accounts(_: str = Depends(require_admin)):
    return {"users": config_admin.accounts()}


@app.post("/api/admin/accounts")
def admin_set_accounts(req: AccountsReq, user: str = Depends(require_admin)):
    try:
        res = config_admin.set_accounts(user, req.users, note=req.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **res}


@app.get("/api/admin/prompts")
def admin_prompts(_: str = Depends(require_admin)):
    prompts.seed_defaults()
    return {"prompts": prompts.versions(), "kinds": list(prompts.KINDS)}


@app.post("/api/admin/prompts")
def admin_add_prompt(req: PromptReq, user: str = Depends(require_admin)):
    try:
        item = prompts.add(req.kind, req.name, req.body, activate=req.activate, actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item, "prompts": prompts.versions()}


@app.post("/api/admin/prompts/{pid}/activate")
def admin_activate_prompt(pid: str, user: str = Depends(require_admin)):
    try:
        item = prompts.set_active(kind="", kid=pid, actor=user)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "item": item, "prompts": prompts.versions()}


@app.delete("/api/admin/prompts/{pid}")
def admin_delete_prompt(pid: str, user: str = Depends(require_admin)):
    if not prompts.delete(pid, actor=user):
        raise HTTPException(404, "提示词版本不存在")
    return {"ok": True, "prompts": prompts.versions()}


@app.get("/api/admin/semantic")
def admin_semantic(_: str = Depends(require_admin)):
    return semantic.catalog()


@app.put("/api/admin/semantic")
def admin_put_semantic(req: SemanticReq, user: str = Depends(require_admin)):
    try:
        cat = semantic.save(req.data, actor=user)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"语义层写入失败：{e}") from e
    return {"ok": True, "catalog": cat}


@app.get("/api/admin/policy")
def admin_policy(_: str = Depends(require_admin)):
    return policy.policy()


@app.put("/api/admin/policy")
def admin_put_policy(req: PolicyReq, user: str = Depends(require_admin)):
    try:
        return {"ok": True, "policy": policy.save_policy(req.policy, actor=user)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"策略写入失败：{e}") from e


@app.get("/api/admin/audit")
def admin_audit(limit: int = 100, actor: str = "", _: str = Depends(require_admin)):
    return {"items": audit.recent(limit, actor=actor), "count": audit.count()}


# ---------------- 管理端：质量评测 ----------------
@app.get("/api/admin/eval/runs")
def admin_eval_runs(limit: int = 30, _: str = Depends(require_admin)):
    return {"runs": evaluation.runs(limit), "jobs": evaluation.jobs()}


@app.post("/api/admin/eval/run")
def admin_eval_run(req: EvalRunReq, user: str = Depends(require_admin)):
    try:
        job = evaluation.start(req.label, req.mode, req.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "job": job}


@app.get("/api/admin/eval/job/{job_id}")
def admin_eval_job(job_id: str, _: str = Depends(require_admin)):
    job = evaluation.job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@app.get("/api/admin/eval/compare")
def admin_eval_compare(a: int, b: int, _: str = Depends(require_admin)):
    try:
        return evaluation.compare(a, b)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ---------------- 静态前端 ----------------
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    if path:
        root = STATIC_DIR.resolve()
        f = (STATIC_DIR / path).resolve()
        # 前缀校验：杜绝 ../ 读到 .env / .secret_key / app.db
        if f.is_relative_to(root) and f.is_file():
            return FileResponse(f)
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse(
        "<h3>前端尚未构建</h3><p>请执行 <code>npm install &amp;&amp; npm run build</code> "
        "并把 frontend/dist 内容拷到 backend/static/。</p>", status_code=200,
    )
