# -*- coding: utf-8 -*-
"""构建 50 张表的向量索引（显式执行，会消耗 1 次硅基流动 embedding 调用）。

用法：
    python backend/scripts/build_index.py           # 真实向量
    MOCK_MODE=true python backend/scripts/build_index.py   # 本地伪向量，零消耗
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.config import settings  # noqa: E402
from app.embedding import last_error  # noqa: E402
from app.schema_index import SchemaIndex  # noqa: E402


async def main():
    idx = SchemaIndex()
    print(f"待索引表：{len(idx.order)} 张 | 模型：{settings.EMB_MODEL} | "
          f"模式：{'mock' if settings.MOCK_MODE else 'remote'}")
    try:
        r = await idx.build()
        print(f"完成：{r} → {settings.index_path}")
    except Exception as e:  # noqa: BLE001
        print(f"失败：{e}；{last_error()}")
        print("提示：不建索引也能用，服务会自动降级为关键词选表。")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
