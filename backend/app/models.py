# -*- coding: utf-8 -*-
"""请求体模型：所有列表/字符串都设上限，防止超大请求体放大内存。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginReq(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=256)


class QueryReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=64)


class SqlReq(BaseModel):
    sql: str = Field(..., min_length=1, max_length=8000)
    # 编辑重跑后把结果回写到对应消息，刷新 / 切会话不再丢失
    session_id: str | None = Field(default=None, max_length=64)
    message_id: int | None = None


class ExplainReq(BaseModel):
    question: str = Field(default="", max_length=1000)
    sql: str = Field(default="", max_length=8000)
    columns: list[str] = Field(default_factory=list, max_length=100)
    rows: list[list[Any]] = Field(default_factory=list, max_length=64)
    truncated: bool = False


class MemoryReq(BaseModel):
    text: str = Field(..., min_length=2, max_length=300)


class KnowledgeSqlReq(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    sql: str = Field(..., min_length=6, max_length=8000)
    tables: list[str] = Field(default_factory=list, max_length=50)
    notes: str = Field(default="", max_length=2000)


class KnowledgeRuleReq(BaseModel):
    text: str = Field(..., min_length=2, max_length=2000)
    title: str = Field(default="", max_length=80)


class FromMessageReq(BaseModel):
    message_id: int = Field(..., gt=0)
    notes: str = Field(default="", max_length=2000)
