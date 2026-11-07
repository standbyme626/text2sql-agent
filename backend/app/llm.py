# -*- coding: utf-8 -*-
"""魔搭 ModelScope DeepSeek 客户端（OpenAI 兼容 /chat/completions）。

默认模型 deepseek-ai/DeepSeek-V4.1-Flash-1017（旧 ID 已失效）。
推理模型可能把正文放在 reasoning_content，content 为空时需回落取用。
429 / 网络超时归为 LLMTransientError：不是 SQL 语法错，不应触发「改写 SQL」重试。
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from . import tracing
from .config import settings

FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
SQL_START = re.compile(r"\b(select|with)\b", re.IGNORECASE)

LANGUAGE_RULE = (
    "\n【硬性语言要求】所有自然语言输出必须使用简体中文。"
    "即使用户问题、SQL、列名或字段值是英文，也必须用简体中文叙述；"
    "SQL 关键字、表名、字段名、专有名词（GMV / SKU 等）与数字保持原样，不要翻译。"
    "【拒答】这类协议标记本身不是自然语言，按协议原样输出即可。"
)


class LLMTransientError(RuntimeError):
    """限流 / 超时 / 网络抖动：应直接告知用户稍后重试，不要重写 SQL。"""


class LLMToolUnsupported(LLMTransientError):
    """模型/网关不支持 OpenAI tools 参数：回退到 workflow 模式。"""


def with_language_rule(messages: list[dict]) -> list[dict]:
    msgs = [dict(m) for m in messages]
    if msgs and msgs[0].get("role") == "system":
        content = msgs[0].get("content") or ""
        if "简体中文" not in content:
            msgs[0]["content"] = content + LANGUAGE_RULE
    else:
        msgs.insert(0, {"role": "system", "content": "你是数据分析助手。" + LANGUAGE_RULE})
    return msgs


def _cut_at_semicolon(s: str) -> str:
    """只在字符串字面量之外切断多语句，避免 WHERE name LIKE '%a;b%' 被误截。"""
    in_str = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            if in_str and i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            in_str = not in_str
        elif ch == ";" and not in_str:
            return s[:i]
        i += 1
    return s


def extract_sql(text: str) -> str:
    """从模型输出里提取纯 SQL，容忍 ```sql 围栏、解释文字、前后缀。"""
    if not text:
        return ""
    m = FENCE.search(text)
    candidate = m.group(1).strip() if m else text.strip()
    candidate = _cut_at_semicolon(candidate).strip().rstrip(";").strip()
    m2 = SQL_START.search(candidate)
    if m2 and not candidate.lower().startswith(("select", "with")):
        candidate = candidate[m2.start():]
    if not SQL_START.search(candidate):
        return ""
    return candidate.strip()


def mock_sql(question: str) -> str:
    """MOCK_MODE 下的假 LLM：按关键词返回预置 SQL / 洞察 JSON，用于零额度自测。"""
    q = question.lower()
    if "请输出 json" in q or "followups" in q:
        return json.dumps({
            "summary": "（本地 Mock 结论）本次查询已返回结果，可继续按时间或品类维度下钻。",
            "followups": [
                "按月份统计销售额的变化趋势",
                "按商品类目统计销售额并取前 10 名",
                "只看已完成订单统计销售额前 10 名",
            ],
        }, ensure_ascii=False)
    if any(k in q for k in ("销售额", "gmv", "营收", "成交额", "月度", "按月")):
        sql = ("SELECT strftime('%Y-%m', order_date) AS 月份, "
               "ROUND(SUM(pay_amount), 2) AS 销售额 "
               "FROM orders WHERE status != 'cancelled' "
               "GROUP BY 月份 ORDER BY 月份 DESC LIMIT 12")
    elif any(k in q for k in ("销量", "卖得最好", "热销", "畅销")):
        sql = ("SELECT p.name AS 商品, SUM(oi.quantity) AS 销量 "
               "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
               "GROUP BY p.name ORDER BY 销量 DESC LIMIT 10")
    elif any(k in q for k in ("品类", "类目", "分类")):
        sql = ("SELECT c.name AS 类目, ROUND(SUM(oi.line_total), 2) AS 销售额 "
               "FROM categories c JOIN products p ON p.category_id = c.category_id "
               "JOIN order_items oi ON oi.product_id = p.product_id "
               "GROUP BY c.name ORDER BY 销售额 DESC LIMIT 10")
    elif any(k in q for k in ("库存", "缺货", "备货")):
        sql = ("SELECT p.name AS 商品, i.quantity AS 库存, i.safety_qty AS 安全库存 "
               "FROM inventory i JOIN products p ON p.product_id = i.product_id "
               "WHERE i.quantity < i.safety_qty ORDER BY i.quantity ASC LIMIT 20")
    elif any(k in q for k in ("客户", "用户数", "注册")):
        sql = ("SELECT province AS 省份, COUNT(*) AS 客户数 "
               "FROM customers GROUP BY province ORDER BY 客户数 DESC LIMIT 15")
    elif any(k in q for k in ("评分", "评价", "口碑")):
        sql = ("SELECT p.name AS 商品, ROUND(AVG(r.rating), 2) AS 平均评分, COUNT(*) AS 评价数 "
               "FROM product_reviews r JOIN products p ON p.product_id = r.product_id "
               "GROUP BY p.name ORDER BY 平均评分 DESC LIMIT 10")
    elif any(k in q for k in ("退款", "退货")):
        sql = ("SELECT reason AS 原因, COUNT(*) AS 数量, ROUND(SUM(amount), 2) AS 退款金额 "
               "FROM refunds GROUP BY reason ORDER BY 数量 DESC")
    else:
        sql = ("SELECT status AS 订单状态, COUNT(*) AS 订单数, "
               "ROUND(SUM(pay_amount), 2) AS 金额 "
               "FROM orders GROUP BY status ORDER BY 订单数 DESC")
    return f"```sql\n{sql}\n```"


def _estimate_tokens(messages: list[dict], extra: str = "") -> int:
    chars = sum(len(str(m.get("content") or "")) for m in messages) + len(extra)
    return max(1, chars // 4)


def parse_tool_json(text: str) -> list[dict]:
    """兼容不支持原生 tools 的模型：从正文里解析 {"tool":..,"arguments":..}。"""
    if not text:
        return []
    candidates = []
    fence = FENCE.search(text)
    if fence:
        candidates.append(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end + 1])
    for raw in candidates:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and (data.get("tool") or data.get("name")):
            name = data.get("tool") or data.get("name")
            args = data.get("arguments") or data.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"_raw": args}
            if not isinstance(args, dict):
                args = {}
            return [{"id": "json_call", "name": str(name), "arguments": args}]
    return []


def _openai_tools(tools: list[dict] | None) -> list[dict] | None:
    return tools or None


async def _completion(messages: list[dict], max_tokens: int | None = None,
                      tools: list[dict] | None = None) -> dict:
    """统一 completion 入口：返回 content / tool_calls / usage。"""
    if settings.MOCK_MODE:
        await asyncio.sleep(0.05)
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "解读" in user or "总结" in user:
            content = "本次查询已返回结果，可按时间或分类维度进一步下钻。"
        else:
            content = mock_sql(user)
        p = _estimate_tokens(messages)
        c = _estimate_tokens([], content)
        tracing.add_usage(p, c)
        with tracing.span("llm.chat", model="mock", mock=True) as sp:
            sp.update(prompt_tokens=p, completion_tokens=c)
        return {"content": content, "tool_calls": [],
                "usage": {"prompt_tokens": p, "completion_tokens": c}}

    if not settings.LLM_API_KEY:
        raise RuntimeError("未配置 MODELSCOPE_API_KEY（魔搭 API key）")

    url = f"{settings.LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": with_language_rule(messages),
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        "stream": False,
    }
    if _openai_tools(tools):
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    last = "大模型暂时不可用，请稍后重试"
    for attempt in range(3):
        try:
            with tracing.span("llm.chat", model=settings.LLM_MODEL,
                              tools=bool(tools)) as sp:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                    r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 429:
                    sp.update(ok=False, status=429)
                    last = "魔搭 429 限流，请稍后再试"
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    body = (r.text or "").lower()
                    sp.update(ok=False, status=r.status_code)
                    if tools and r.status_code == 400 and (
                            "tool" in body or "function" in body):
                        raise LLMToolUnsupported("上游不支持 tools/function calling")
                    raise LLMTransientError(f"魔搭接口 HTTP {r.status_code}")
                data = r.json()
                msg = data["choices"][0]["message"]
                content = (msg.get("content") or "").strip()
                if not content:
                    content = (msg.get("reasoning_content") or "").strip()
                calls = []
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or "{}"
                    try:
                        parsed = json.loads(args) if isinstance(args, str) else args
                    except ValueError:
                        parsed = {"_raw": args}
                    calls.append({"id": tc.get("id") or "call",
                                  "name": fn.get("name") or "",
                                  "arguments": parsed if isinstance(parsed, dict) else {}})
                usage = data.get("usage") or {}
                pt = int(usage.get("prompt_tokens") or _estimate_tokens(messages))
                ct = int(usage.get("completion_tokens") or _estimate_tokens([], content))
                sp.update(ok=True, prompt_tokens=pt, completion_tokens=ct,
                          tool_calls=len(calls))
                tracing.add_usage(pt, ct)
                if not content and not calls:
                    raise LLMTransientError("模型返回内容为空")
                return {"content": content, "tool_calls": calls,
                        "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
        except LLMToolUnsupported:
            raise
        except LLMTransientError as e:
            last = str(e)
            if "HTTP" in last and "429" not in last:
                raise
            await asyncio.sleep(1 + attempt)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last = f"大模型请求超时或网络异常：{type(e).__name__}"
            await asyncio.sleep(1 + attempt)
        except Exception as e:  # noqa: BLE001
            raise LLMTransientError(f"大模型调用异常：{type(e).__name__}") from e
    raise LLMTransientError(last)


async def chat(messages: list[dict], max_tokens: int | None = None) -> str:
    """返回模型正文；失败抛出异常，由上层转成 SSE 错误事件。"""
    return (await _completion(messages, max_tokens=max_tokens))["content"]


async def chat_tools(messages: list[dict], tools: list[dict],
                     max_tokens: int | None = None) -> dict:
    """OpenAI tools 调用；不支持时抛 LLMToolUnsupported 供上层回退 workflow。"""
    return await _completion(messages, max_tokens=max_tokens, tools=tools)
