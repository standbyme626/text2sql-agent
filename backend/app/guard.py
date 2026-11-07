# -*- coding: utf-8 -*-
"""异常问题护栏：拒答 + 引导用户正确提问。

两层，尽量保守，避免误伤正常业务提问：
  1) 规则前置（零 LLM 调用）：只拦明确的空输入 / 写操作越权 / 提示注入 / 整句闲聊 / 整句模糊；
  2) 大模型拒答协议：输出 `【拒答】|原因|建议1|建议2|建议3`（兼容旧 REFUSE|…），
     由 parse_refusal 解析；格式不符或没给 SQL 时走中文兜底引导。

规则层刻意整句锚定并排除查询动词：「查询订单状态更新记录」「统计库存更新记录」
对应真实表，属于正常业务提问，绝不能被当成写操作拒答。
"""
from __future__ import annotations

import re

from .config import settings

# 英文 SQL 写语句 / 越权语句（结构明确，可用子串匹配）
_WRITE_SQL = re.compile(
    r"\b(drop|truncate|alter)\s+table\b|"
    r"\b(delete\s+from|insert\s+into|update\s+\w+\s+set|create\s+(table|database|index)|"
    r"attach\s+database|detach\s+database|pragma\s+\w+|vacuum|reindex|load_extension|"
    r"select\s+load_extension)\b",
    re.IGNORECASE,
)
# 中文写动作：必须整句就是写请求，避免命中「…更新记录」这类只读名词
_WRITE_CN = [
    re.compile(r"^\s*(请|帮我|麻烦)?\s*(删除|清空|删掉|改动|修改|更新|写入|插入|新增|撤销)"
               r"\s*(数据库|数据表|表|订单信息|用户数据|数据|记录|状态)(\s*里的?[^\n]*)?\s*[。.!！?？]*\s*$"),
    re.compile(r"^\s*(把|将)\s*.{0,30}\s*(改成|改为|更新为|删除|插入)\s*[。.!！?？]*\s*$"),
]
_INJECTION_PATTERNS = [
    r"(输出|打印|给我|告诉我|显示|复述|泄露|导出)\s*.{0,12}(系统提示词|提示词|system\s*prompt|系统指令|内部指令)",
    r"(系统提示词|system\s*prompt|系统指令)\s*.{0,12}(输出|打印|给我|告诉我|是什么|内容|复述)",
    r"(print|show|reveal|dump|repeat)\s+(me\s+)?(your|the|system)\s+(prompt|instructions|rules)",
    r"ignore\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions|prompts|rules)",
    r"(忽略|无视|忘记|绕过|禁用)\s*.{0,8}(上面|之前|所有|系统|原先|以上)\s*.{0,8}(指令|规则|要求|提示|限制|约束)",
    r"(密钥|token|api\s*key|secret|密码)\s*.{0,12}(给我|输出|打印|告诉我|泄露|是什么)",
    r"(扮演|假装|越狱|开发者模式|dan\s*mode|act\s+as\s+(a\s+)?(developer|admin|dan))",
    r"(给我|输出|导出|列出|打印)\s*.{0,6}(全部|所有)\s*.{0,8}(手机号|身份证|密码|token|密钥)",
]
_OFFTOPIC_PATTERNS = [
    r"^\s*(你好|您好|hi|hello|在吗|你是谁|讲个?笑话|写一首?诗|写段?代码|翻译一下|闲聊|聊聊天)\s*[!！?？。.~\s]*$",
    r"^\s*(今天|明天|现在).{0,4}(天气|气温|股价|汇率)\s*(怎么样|如何|多少)?\s*[?？。.]*\s*$",
    r"(帮我|给我|请)\s*(写|编|创作|翻译)\s*(一首|一篇|一段|个|份)?\s*(诗|文章|故事|代码|邮件|文案|简历)",
    r"(预测|预估|预报)\s*.{0,12}(明年|下一年|未来|下一季度|双\s*11|销售额|销量)",
]
_VAGUE_PATTERNS = [
    r"^\s*(随便|看看|查查|分析一下|有什么|帮我看看|看一下数据|查一下|来点数据|嗯|啊|\?)\s*[?？。.!！~\s]*$",
    r"^\s*(随便看看|随便查查|随便来点|帮我分析一下|帮我分析下)\s*[?？。.!！~\s]*$",
]
_QUERY_VERBS = re.compile(r"(查询|统计|查看|看看|列出|分析|排名|趋势|分布|占比|对比|汇总|有多少|分别是)")

DEFAULT_SUGGESTIONS = [
    "统计近 12 个月每月的销售额趋势",
    "按商品类目统计销售额并取前 10 名",
    "查询库存低于安全库存的商品有哪些",
]

# 由 SchemaIndex 注入：判断建议问法能否用本库现有表回答
_answerable = None


def set_answerable(fn) -> None:
    global _answerable
    _answerable = fn


_REFUSE_MARK = re.compile(r"(【拒答】|REFUSE)\s*[|｜:：,，]?\s*", re.IGNORECASE)
_ZH = re.compile(r"[\u4e00-\u9fff]")


def _has_zh(s: str) -> bool:
    t = re.sub(r"\s+", "", str(s or ""))
    return bool(t) and len(_ZH.findall(t)) / len(t) >= 0.15


def _guidance(reason: str, kind: str, suggestions: list[str] | None, source: str) -> dict:
    n = settings.GUARD_SUGGESTIONS
    sug: list[str] = []
    for x in (suggestions or []):
        x = str(x).strip()
        if not x or not _has_zh(x) or x in sug:
            continue
        if _answerable and not _answerable(x):
            continue
        sug.append(x)
    for x in DEFAULT_SUGGESTIONS:
        if len(sug) >= n:
            break
        if x not in sug:
            sug.append(x)
    return {
        "type": "guidance",
        "kind": kind,               # refuse=拒答 / clarify=需补充信息
        "reason": reason if _has_zh(reason) else "该问题无法用当前数据回答，请换一种更具体的问法。",
        "suggestions": sug[:n],
        "source": source,           # rule / llm / fallback
    }


def check(question: str) -> dict | None:
    """规则前置。命中返回 guidance 事件，未命中返回 None 交给 LLM 判断。"""
    if not settings.GUARD_ENABLED:
        return None
    q = (question or "").strip()
    if len(q) < 2 or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", q):
        return _guidance("问题太短或没有可识别的内容，请说明想查的指标或维度。", "clarify", None, "rule")

    if _WRITE_SQL.search(q):
        return _guidance(
            "该请求涉及写操作、越权访问或绕过限制；本系统只提供电商演示库的只读查询。",
            "refuse", None, "rule",
        )
    # 中文写动作只在「整句就是写请求」时命中；带查询动词的一律放行
    if not _QUERY_VERBS.search(q):
        for pat in _WRITE_CN:
            if pat.search(q):
                return _guidance(
                    "该请求涉及写操作、越权访问或绕过限制；本系统只提供电商演示库的只读查询。",
                    "refuse", None, "rule",
                )
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, q, re.IGNORECASE):
            return _guidance(
                "该请求试图获取系统内部信息或绕过限制；本系统只回答电商演示库的业务查询。",
                "refuse", None, "rule",
            )
    for pat in _OFFTOPIC_PATTERNS:
        if re.search(pat, q, re.IGNORECASE):
            return _guidance(
                "这个问题与电商演示数据无关，我只能回答这张库能查到的业务问题。",
                "refuse", None, "rule",
            )
    for pat in _VAGUE_PATTERNS:
        if re.search(pat, q, re.IGNORECASE):
            return _guidance(
                "问题信息不足，请说明要查的指标、时间范围或拆分维度。",
                "clarify", None, "rule",
            )
    return None


def parse_refusal(raw: str) -> dict | None:
    """解析模型拒答输出，兼容中英文标记、竖线/冒号/换行、前后带解释文字。"""
    if not settings.GUARD_ENABLED:
        return None
    s = (raw or "").strip().strip("`").strip()
    m = _REFUSE_MARK.search(s)
    if not m:
        return None
    tail = s[m.end():]
    parts = [p.strip() for p in re.split(r"[|｜\n]", tail) if p.strip()]
    if len(parts) < 2:
        parts = [p.strip() for p in re.split(r"[:：,，]", tail) if p.strip()]
    reason = parts[0] if parts else "该问题无法用当前数据回答。"
    suggestions = parts[1:]
    return _guidance(reason, "refuse", suggestions, "llm")


def fallback_guidance() -> dict:
    """模型既没给 SQL 也没按拒答协议输出时的中文兜底。"""
    return _guidance(
        "这个问题暂时没能生成可执行的查询，请换一种更具体的问法，或参考下面的示例。",
        "clarify", None, "fallback",
    )
