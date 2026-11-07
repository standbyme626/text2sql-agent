# -*- coding: utf-8 -*-
"""硅基流动 Qwen/Qwen3-Embedding-8B 向量化客户端。

- 真实模式：POST /v1/embeddings，支持批量与自定义维度
- MOCK_MODE：本地字符哈希伪向量，零 API 消耗，用于自测
- 无 key / API 异常：返回 None，上层降级到关键词选表
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import math

import httpx

from .config import settings

# 每次 embed 调用链内隔离错误，避免并发请求串扰 /api/status 里的诊断信息
_ctx_error: contextvars.ContextVar[str] = contextvars.ContextVar("emb_error", default="")
_global_error: str = ""


def set_error(msg: str) -> None:
    global _global_error
    _ctx_error.set(msg[:180])
    _global_error = msg[:180]


def clear_error() -> None:
    global _global_error
    _ctx_error.set("")
    _global_error = ""


def last_error() -> str:
    return _ctx_error.get() or _global_error


def pseudo_vector(text: str, dim: int | None = None) -> list[float]:
    """确定性伪向量：中文按字 + 相邻二元组哈希分桶，字面重合度≈相似度。"""
    d = dim or settings.EMB_DIM
    vec = [0.0] * d
    s = (text or "").lower()
    tokens = list(s) + [s[i:i + 2] for i in range(len(s) - 1)]
    for tok in tokens:
        if not tok.strip():
            continue
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        vec[h % d] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """真·余弦：显式归一化 + 维度一致断言，避免远端向量量纲失衡。"""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"向量维度不一致：{len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def _post_batch(texts: list[str]) -> list[list[float]] | None:
    if settings.MOCK_MODE:
        return [pseudo_vector(t) for t in texts]
    if not settings.EMB_API_KEY:
        set_error("未配置 SILICONFLOW_API_KEY，已降级为关键词检索")
        return None

    url = f"{settings.EMB_BASE_URL}/embeddings"
    payload = {
        "model": settings.EMB_MODEL,
        "input": texts,
        "encoding_format": "float",
        "dimensions": settings.EMB_DIM,
    }
    headers = {
        "Authorization": f"Bearer {settings.EMB_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=settings.EMB_TIMEOUT) as client:
                r = await client.post(url, headers=headers, json=payload)
            if r.status_code == 429:
                set_error("硅基流动 429 限流")
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code != 200:
                # 上游响应正文只写日志，不回显给客户端
                set_error(f"向量接口 HTTP {r.status_code}")
                return None
            data = r.json().get("data", [])
            data.sort(key=lambda x: x.get("index", 0))
            vectors = [d["embedding"] for d in data]
            if len(vectors) != len(texts):
                set_error("向量返回条数与输入不一致")
                return None
            if any(len(v) != settings.EMB_DIM for v in vectors):
                set_error("向量维度与 EMB_DIM 不一致")
                return None
            clear_error()
            return vectors
        except Exception as e:  # noqa: BLE001
            set_error(f"向量接口异常：{type(e).__name__}")
            await asyncio.sleep(1 + attempt)
    return None


async def embed(texts: list[str]) -> list[list[float]] | None:
    """批量向量化；单次最多 32 条，超出自动分批。"""
    clear_error()
    if not texts:
        return []
    out: list[list[float]] = []
    for i in range(0, len(texts), 32):
        part = await _post_batch(texts[i:i + 32])
        if part is None:
            return None
        out.extend(part)
    return out


async def embed_one(text: str) -> list[float] | None:
    r = await embed([text])
    return r[0] if r else None
