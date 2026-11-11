# knowledge/ · 可审计的文件知识库

设计参考 Wren AI 的 context / memory 分层：**markdown 是唯一真相，检索索引只是派生层**。

| 目录 | 内容 | 谁来写 |
|---|---|---|
| `sql/*.md` | 已确认的「自然语言问题 → SQL」样例 | 管理员在「管理后台 → 会话轨迹」收录，或直接手写 |
| `rules/*.md` | 业务口径、过滤规则、命名约定 | 管理员在「管理后台 → 知识库」新增，或直接手写 |

运行时 `backend/app/knowledge.py` 会：

1. 扫描两个目录（按 mtime 缓存，改文件后自动失效）；
2. 把 `knowledge/sql` 的样例与 `qa_history` 的自动 few-shot 合并召回，正式样例优先；
3. 把 `knowledge/rules` 注入每轮 system prompt，优先级高于默认口径。

## sql 样例格式

```md
---
question: 近 12 个月每月销售额趋势
sql: |-
  SELECT strftime('%Y-%m', order_date) AS 月份, ROUND(SUM(pay_amount), 2) AS 销售额
  FROM orders
  WHERE status NOT IN ('cancelled','refunded')
  GROUP BY 月份 ORDER BY 月份
tables:
- orders
source: session:abc123#42
created: '2026-11-11T22:00:00'
verified: true
---

可选备注：为什么这样写、口径来源。
```

## rules 规则格式

```md
---
title: 有效成交口径
source: admin:sqladmin
created: '2026-11-11T22:00:00'
---

统计有效成交时排除 orders.status 为 cancelled / refunded 的订单。
```

## 注意

- 这些文件会进入 Git，可 review、可回滚；**不要写入密钥、手机号、身份证等敏感数据**。
- 自动积累的 `qa_history` 仍是隐式记忆；只有管理员确认过的样例才会写进 `knowledge/sql`，避免错误答案回流。
- 删除样例/规则会同步失效缓存，无需重启服务。
