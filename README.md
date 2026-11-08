<div align="center">

# text2sql-agent

**中文 Text-to-SQL / Data Agent · 2026 tool-calling 架构**

工具调用循环 · 受治理语义层 · 列级 schema linking · MCP Server · 执行准确率评测 · Trace 观测

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.5-42B883?logo=vue.js&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-read--only-003B57?logo=sqlite&logoColor=white)
![Postgres](https://img.shields.io/badge/Postgres-read--only-336791?logo=postgresql&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-stdio-6B4FBB)
![Tool Calling](https://img.shields.io/badge/Agent-tool--calling-0EA5E9)
![Eval](https://img.shields.io/badge/Eval-execution%20accuracy-16A34A)
![CI](https://github.com/standbyme626/text2sql-agent/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/License-MIT-green)

[项目概览](#1-项目概览) · [核心特性](#2-核心特性) · [界面](#3-界面) · [系统架构](#4-系统架构) · [快速开始](#8-快速开始) · [API](#9-api)

[部署](#10-部署) · [测试与验证](#11-测试与验证) · [已知限制](#12-已知限制与未验证事项) · [踩坑记录](#13-工程实践与踩坑) · [Roadmap](#16-roadmap)

</div>

> **项目状态：v3.0 / 2026 Agent 架构 / 单实例演示。**
> 曾在公网域名上以「应用层登录 + 只读闸门」对外提供过一段时间，单账号使用；
> 仓库不含数据库文件、向量索引与任何密钥，首次运行按第 8 节初始化，约 1 分钟建好 50 张表。

**50 张表** · **51,899 行** · **tool-calling Agent** · **5 个工具 + MCP** · **130 项自测** · **单轮 ≤ 6 次 LLM 调用**

---

## 目录

- [1. 项目概览](#1-项目概览)
- [2. 核心特性](#2-核心特性)
- [3. 界面](#3-界面)
- [4. 系统架构](#4-系统架构)
- [5. 选表与生成](#5-选表与生成)
- [6. 只读闸门与拒答](#6-只读闸门与拒答)
- [7. 数据资产](#7-数据资产)
- [8. 快速开始](#8-快速开始)
- [9. API](#9-api)
- [10. 部署](#10-部署)
- [11. 测试与验证](#11-测试与验证)
- [12. 已知限制与未验证事项](#12-已知限制与未验证事项)
- [13. 工程实践与踩坑](#13-工程实践与踩坑)
- [14. 目录结构](#14-目录结构)
- [15. 安全须知](#15-安全须知)
- [16. Roadmap](#16-roadmap)

---

## 1. 项目概览

### 1.1 要解决的问题

Text-to-SQL 的 demo 半天能写完，但它离「能给别人用」差一段距离：

- **50 张表的 DDL 不能全塞进 prompt**：约 3 万 token，又贵又选不准；
- **模型生成的 SQL 会报错**：语法错、字段错、JOIN 漏表，直接把错误抛给用户等于没做；
- **用户看不懂结果表**：需要一句人话结论，以及下一步该问什么；
- **什么都能问 = 什么都答不好**：「讲个笑话」「DROP TABLE」这类输入必须被挡住，
  并告诉用户**能问什么**；
- **生成到一半断掉会丢数据**：SSE 断开时若先推送后落库，历史里只剩半条消息。

### 1.2 方案

采用 **2026 tool-calling Agent + 固定流水线降级** 的双模架构：

- **toolloop（默认）**：模型通过 OpenAI tools 自主调用 `search_schema` / `run_sql` / `list_metrics` / `remember_preference`，执行结果作为 Observation 回灌，形成「规划 → 调工具 → 看结果 → 修正」的真实循环；
- **workflow（降级）**：模型或网关不支持 tools 时，同一请求内无缝回退固定流水线（选表 → 生成 → 执行 → 报错重试）；
- 选表用向量检索 + **列级关键词 linking**，没 key / 429 / 索引损坏时自动退回纯关键词；
- 业务口径升级为 **YAML 语义层**（可版本化、可 API 审计），不再是一段硬编码 prompt；
- 拒答分两层：规则前置零成本，模型协议处理模糊问题；
- 全链路 **trace + token/延迟/工具失败率** 观测，查询可回放。

### 1.3 八个平面

| 平面 | 职责 | 入口 |
|---|---|---|
| 策略 | 配置快照、次数上限钳制、鉴权开关 | `config.py` |
| Agent | tool-calling 循环 / workflow 降级 / 上下文组装 | `agent.py` / `tools.py` |
| 语义 | 指标口径、标准 JOIN、方言日期函数 | `semantic/metrics.yaml` / `semantic.py` |
| 治理 | 只读闸门、拒答护栏、限流 | `db.py` / `guard.py` / `auth.py` |
| 数据 | 50 表 schema、SQLite/Postgres、向量索引、会话/few-shot/记忆 | `schema_index.py` / `store.py` / `db.py` |
| 接口 | Web SSE + **MCP stdio server** | `main.py` / `mcp_server.py` |
| 观测 | trace / span / token / p50-p95 / 工具失败率 | `tracing.py` |
| 交互 | 会话、SQL 编辑重跑、图表、Agent 轨迹时间线 | `frontend/src/` |

---

## 2. 核心特性

| 能力 | 代码入口 |
|---|---|
| **Tool-calling Agent** — 模型自主调 search_schema / run_sql / submit_result / list_metrics；报错与 0 行作为 Observation 回灌 | `agent.py::_tool_loop`、`tools.py` |
| **MCP Server** — stdio 暴露同一套只读工具，可接 Claude Code / opencode / 任意 MCP host | `backend/mcp_server.py` |
| **向量选表 + 列级 linking** — 问题向量化 → Top-6 表 + 外键闭包；列级中文关键词打分 | `schema_index.py::search`、`column_scores` |
| **YAML 语义层** — GMV/销量/客单价等指标与标准 JOIN 可版本化、可 API 审计 | `semantic/metrics.yaml`、`semantic.py` |
| **执行准确率评测** — golden set + BIRD dev 加载器，结果集比对而非字符串相似 | `backend/scripts/eval.py`、`eval/golden.yaml` |
| **Trace 观测** — OTel 语义兼容 JSONL，p50/p95、token、工具失败率 | `tracing.py`、`/api/metrics` |
| **跨会话记忆** — 显式偏好写入 + 问题召回注入，零 embedding 成本 | `store.py::add_memory`、`relevant_memory` |
| **Postgres 只读** — `DATABASE_URL` 切换；默认事务只读 + statement_timeout | `db.py::_execute_postgres`、`build_meta_pg.py` |
| **外键闭包补表** — 缺 JOIN 父表时按 `fks` 补全，最多 `FK_EXPAND_MAX` 张 | `schema_index.py::expand_with_fks` |
| **上下文组装** — DDL + 中文列说明 + 枚举值 + 样例行 + 业务口径 + few-shot + 交替历史 | `prompt_context`、`build_messages` |
| **SQL 生成** — 只允许一条 SELECT；无法回答时走 `【拒答】原因｜建议` 协议 | `llm.py::chat`、`extract_sql` |
| **只读闸门** — 剥离字面量后校验关键字/注释/多语句；强制顶层 LIMIT；5s 超时 | `db.py::clean_sql`、`_top_level_limit` |
| **双层自纠正** — toolloop 内模型自主重试；workflow 报错/0 行/缺表回灌；单轮硬预算 | `agent.py::_tool_loop`、`_workflow_loop` |
| **自动解读** — 结论 + 追问合并为 1 次轻量调用，只喂前 8 行；0 行/截断走专用提示 | `agent.py::build_insight` |
| **拒答引导** — 规则前置拦截无关/越权/注入；模糊问题给可点击的正确问法 | `guard.py::check`、`parse_refusal` |
| **会话还原** — 完整回答结构化落库（`payload`），切走再切回表格/图表/结论都在 | `store.py::add_answer`、`get_history` |
| **鉴权** — 中文登录页 + HMAC token，签名绑定密码版本；登录失败按 IP 限流 | `auth.py::make_token`、`rate_ok` |
| **流式输出** — SSE 事件：`session` / `stage` / `tables` / `step` / `sql` / `result` / `retry` / `insight` / `guidance` / `error` / `done`；带 `trace_id` | `main.py::query`、`agent.py` |
| **前端** — Vue 3 单页，无 UI 框架，图表用原生 SVG 手绘 | `frontend/src/components/` |

---

## 3. 界面

<p align="center">
  <img src="docs/screenshots/result.png" width="900" alt="结果区：自动结论、追问建议、SVG 图表与表格">
</p>

<p align="center"><sub>自动结论 + 可点击追问 + 图表 + 表格；右上角可收起图表、导出 CSV、重新解读</sub></p>

**Agent 过程是可见的**：本轮命中了哪几张表、各自的向量分/关键词分、最终执行的 SQL，
都摆在结果前面，不是黑盒。

<p align="center">
  <img src="docs/screenshots/agent-flow.png" width="900" alt="检索命中的数据表与生成的 SQL">
</p>

<p align="center"><sub>检索命中的数据表（Top 9，含分数）+ 生成的 SQL（可复制、可编辑后重跑）</sub></p>

**异常问题不会硬凑 SQL**，而是说明原因并给出可以直接点的问法：

<p align="center">
  <img src="docs/screenshots/guard.png" width="760" alt="拒答引导：无法回答 + 可以这样问">
</p>

<p align="center"><sub>规则前置拦截「讲个笑话」，零模型消耗；建议问法点击即问</sub></p>

**表结构可浏览**：50 张表按名称/中文名/业务域搜索，展开看 DDL、字段中文说明、枚举值、样例行。

<p align="center">
  <img src="docs/screenshots/schema.png" width="900" alt="表结构浏览：搜索、DDL、字段说明、样例">
</p>

<p align="center"><sub>右侧为表结构面板，左侧会话不受影响</sub></p>

**移动端**：侧栏与表结构面板变抽屉，图表自动缩减数据点，输入框适配 iOS 安全区。

<table align="center">
  <tr>
    <td align="center"><img src="docs/screenshots/mobile.png" width="270" alt="移动端结果区"></td>
    <td align="center"><img src="docs/screenshots/mobile-drawer.png" width="270" alt="移动端侧栏抽屉"></td>
  </tr>
  <tr>
    <td align="center"><sub>结果区（390×844）</sub></td>
    <td align="center"><sub>侧栏抽屉</sub></td>
  </tr>
</table>

**公网部署时走应用层登录**，不依赖 nginx Basic（原生 401 弹窗在手机和预览面板里常不出现）：

<p align="center">
  <img src="docs/screenshots/login.png" width="640" alt="应用层登录页">
</p>

<p align="center"><sub>登录后 24 小时内免输；token 绑定密码版本，改密即失效</sub></p>

---

## 4. 系统架构

### 4.1 总览

```text
用户提问（中文）
   │
   ▼
①  guard.check ─────── 无关 / 越权 / 注入 ──▶ guidance（0 次模型调用）
   │ 通过
   ▼
②  embed(question) → Top-6 表 + 外键闭包 + 列级 linking
   │                  （失败自动降级为中文关键词）
   ▼
③  build_messages：语义层指标 + DDL + 枚举 + few-shot + 历史 + 长期记忆
   │
   ▼
④  ┌───────────── Agent tool-calling loop（默认）─────────────┐
   │  LLM 决策 ──▶ search_schema / run_sql / list_metrics      │
   │      ▲                         │                          │
   │      └──── Observation ◀───────┘（报错 / 0 行 / 缺列）    │
   │  直到模型输出 DONE 或拒答；超步数/超预算即停               │
   └────────────────────────────────────────────────────────────┘
   │  （模型不支持 tools → 同一请求内回退 workflow 固定流水线）
   ▼
⑤  clean_sql 只读闸门 ─▶ execute_readonly（mode=ro / PG 只读事务 + 超时）
   ▼
⑥  先落库：user + assistant 同事务（payload 存完整回答 + 工具轨迹 + trace_id）
   ▼
⑦  build_insight ──▶ 中文结论 + 3 条追问（只喂前 8 行）
   ▼
⑧  SSE 推送：session → stage → tables → step → sql → result → insight → done
   ▼
⑨  trace 落盘：llm.chat / tool.* / db.execute 的耗时、token、成功失败
```

### 4.2 一次提问的完整过程

1. 前端 `POST /api/query`，建立 SSE 连接，携带 `X-App-Token`；
2. `guard.check` 规则前置：命中写操作、注入、闲聊直接返回 `guidance`，**不调用任何模型**；
3. `embedding.embed_one` 向量化问题；`SchemaIndex.search` 融合向量/关键词分取 Top-6，外键闭包补齐 JOIN 父表，并给出列级 `matched_columns`；
4. `semantic.prompt_block` 注入受治理指标与标准 JOIN；`store.similar` 补 few-shot；`store.relevant_memory` 注入用户显式偏好；
5. **toolloop**：`llm.chat_tools` 携带 4 个工具定义；模型可多轮调用 `search_schema` / `run_sql` / `list_metrics`，每次工具结果作为 Observation 回灌；`run_sql` 内部仍走与 Web API 完全相同的只读闸门；
6. 模型输出 DONE 后，以最后一次成功执行的 SQL 结果为准；若模型不支持 tools，则同一请求回退 `_workflow_loop`（选表→生成→执行→报错重写）；
7. **先落库**：`store.add_answer` 把 SQL、结果、命中表、图表建议、工具轨迹、trace_id 写进同一条 assistant 消息；
8. `build_insight` 生成中文结论与追问，patch 回该消息，再推 `insight` 事件；
9. 全链路 span 写入 `traces.jsonl`，`/api/metrics` 可在进程内看到 p50/p95、token、工具失败率；
10. 成功问答向量化写入 `qa_history` 作为后续 few-shot（带会话归属、表名白名单、保留上限）。

### 4.3 数据平面

| 存储 | 职责 | 说明 |
|---|---|---|
| `ecommerce.db` | 50 张电商演示表 | 首次运行由 `scripts/init_db.py` 生成，约 3.7 MB / 51,899 行 |
| `app.db` | 会话、消息、few-shot 库 | WAL 模式；`messages.payload` 存完整回答 |
| `schema_meta.json` | 表中文名、业务域、列说明、枚举值 | 建库时一并生成，选表与上下文都依赖它 |
| `schema_index.json` | 50 条表描述向量 | `scripts/build_index.py` 生成，可重建 |
| `.secret_key` | token 签名密钥 | 首次启动 `O_EXCL` 原子创建，权限 600 |
| `traces.jsonl` | trace / span / token | OTel 语义兼容 JSONL，600；`/api/metrics` 读进程内最近 N 条 |
| `semantic/metrics.yaml` | 受治理指标层 | 版本化指标、标准 JOIN、方言日期函数；`/api/semantic` 可审计 |
| `user_memory`（app.db） | 跨会话偏好 | 仅显式「记住/以后/默认」写入；按中文二元组召回注入 |

### 4.4 模型供给

- **文本**：`deepseek-ai/DeepSeek-V4.1-Flash-1017`（魔搭 ModelScope，OpenAI 兼容）；
- **向量**：`Qwen/Qwen3-Embedding-8B`（硅基流动，1024 维），只用于选表与 few-shot 检索；
- **工具调用**：默认发送 OpenAI `tools` + `tool_choice=auto`；上游返回 400/不支持时自动回退 workflow，不影响可用性；
- **可替换**：两个端点都是 OpenAI 兼容协议，改 `.env` 的 `LLM_BASE_URL` / `LLM_MODEL` 即可换成别家；
- **降级顺序**：toolloop → workflow；向量选表 → 关键词选表；自动结论失败 → 前端提示可手动「AI 解读」；无 Key → `MOCK_MODE`。
- **免费兜底**：ModelScope 额度耗尽时，可把 `LLM_BASE_URL` 指向 OpenRouter，使用带 `:free` 后缀的模型（如 `nvidia/nemotron-3-ultra-550b-a55b:free`），并设置通用 `LLM_API_KEY`；**本项目任何情况下不调用收费模型**。

---

## 5. 选表与生成

### 5.1 为什么不把 DDL 全塞进去

50 张表的建表语句 + 中文注释约 3 万 token。按轮次拼进去的后果是：贵、慢，而且**准确率反而下降**
（模型会挑错表、拼错 JOIN）。向量选表把每轮上下文压到 6 张表以内，同时保留业务语义：

| 用户问法 | 命中的表 | 靠什么命中 |
|---|---|---|
| 「各渠道销售额占比」 | `orders`、`order_items`、`payment_methods` | 语义「销售额 / 渠道」 |
| 「哪些商品库存低于安全库存」 | `products`、`inventory`、`warehouses` | 关键词「库存 / 安全库存」 |
| 「近三个月复购率」 | `orders`、`customers`、`customer_groups` | 语义 + 外键闭包引入 `customers` |

### 5.2 外键闭包

Top-6 只按语义选出，很容易漏掉 JOIN 需要的维表。`expand_with_fks` 会读每张表的 `fks`，
把父表补进来（最多 `FK_EXPAND_MAX` 张），避免模型写出「`orders JOIN customers` 但 `customers` 不在上下文里」。

### 5.3 自纠正循环

```text
生成 SQL → 执行
   ├─ SQL 语法/字段错误 ──▶ 把 sqlite 报错原文作为 Observation 回灌 → 重写
   ├─ 返回 0 行        ──▶ 提示「可能是过滤条件过严」，放宽后重试一次
   ├─ no such table    ──▶ 扩表重检索（新 Top-K）后重写
   └─ 成功            ──▶ 落库 + 解读
```

三重约束防止失控：`MAX_SQL_RETRY=2`（最多 3 次生成）、`MAX_LLM_CALLS=6`（单轮硬预算，含 1 次洞察）、
**429/超时不进「改 SQL」重试**（重试也不会成功，只会白烧额度）。

> v3.0 起默认走 toolloop：模型看到 `run_sql` 的报错 Observation 后自行决定重写、扩表或停手，
> 上图的 workflow 逻辑保留为降级路径（`AGENT_MODE=workflow` 或上游不支持 tools 时）。

### 5.4 列级 schema linking

表级 Top-K 只能保证「表选对」，复杂问题还需要「列选对」。`column_scores` 对每张候选表的
列名 + 中文注释做中文二元组匹配，并给问题中出现的英文列名加权，输出 `matched_columns`：

- 注入 prompt 的每张表增加「与问题最相关的列」一行，减少模型在 10+ 列里挑错；
- `tables` SSE 事件与 `/api/meta` 都能看到列级命中，便于前端与审计；
- **不额外调用 embedding**：50 表 × 十余列若做列向量会产生数百次 API 调用，这里用零成本、
  可解释的关键词融合；需要更强列语义时再升级为列向量（`COLUMN_LINK_TOPK` 控制返回列数）。

### 5.5 语义层（YAML）

`backend/semantic/metrics.yaml` 是业务口径的唯一真相：

```yaml
metrics:
  - id: gmv
    name: 销售额 / GMV
    synonyms: [销售额, gmv, 营收, 成交额]
    expr: "SUM(orders.pay_amount)"
    valid_filter: "orders.status NOT IN ('cancelled','refunded')"
```

- `semantic.prompt_block(question)` 只注入「与问题相关」的指标，控制 token；
- `/api/semantic` 返回完整指标目录、标准 JOIN、方言日期函数，可被前端/审计消费；
- 文件缺失或 YAML 损坏时自动退回内置口径，服务不中断；
- 换 Postgres 时用 `dialects.postgres.date_month = date_trunc(...)`，同一指标定义跨方言复用。

### 5.6 跨会话记忆

- 只有用户明确说「记住 / 以后 / 默认」时，模型才会调用 `remember_preference` 写入；
- 写入 `app.db` 的 `user_memory` 表，按 owner 隔离，每用户最多 100 条；
- 每轮按中文二元组召回 Top-3 注入 prompt，零 embedding 调用；
- `GET/POST/DELETE /api/memory` 可人工审计与删除，不做隐式画像。

### 5.7 可调参数

| 参数 | 默认 | 位置 |
|---|---|---|
| `TOP_K_TABLES` | 6 | `.env` / `config.py` |
| `FK_EXPAND_MAX` | 3 | 同上，外键闭包最多补几张 |
| `FEWSHOT_K` | 2 | 注入几条相似历史问答 |
| `MAX_SQL_RETRY` | 2 | 报错重写次数（钳制 0~5） |
| `MAX_LLM_CALLS` | 6 | 单轮 LLM 调用硬预算（含 1 次洞察；钳制 1~20） |
| `MAX_RESULT_ROWS` | 500 | 单次返回上限，超出标记 `truncated` |
| `SQL_TIMEOUT_MS` | 5000 | 单条 SQL 超时 |
| `EMPTY_RESULT_RETRY` | `true` | 0 行是否回灌重试 |
| `HISTORY_TURNS` | 6 | 注入几轮历史对话 |
| `INSIGHT_PREVIEW_ROWS` | 50 | 洞察调用最多喂多少行结果（防止把预览行数当总行数） |
| `AGENT_MODE` | `toolloop` | `toolloop` / `workflow` |
| `MAX_AGENT_STEPS` | 6 | Agent 最多规划步数（钳制 1~20） |
| `MAX_TOOL_SQL` | 4 | 单轮最多执行几次 SQL |
| `COLUMN_LINK_TOPK` | 8 | 每张表返回多少相关列 |
| `TOOL_ROW_PREVIEW` | 20 | 回灌给模型的工具结果预览行数 |
| `MEMORY_ENABLED` | `true` | 跨会话偏好记忆开关 |
| `TRACE_ENABLED` | `true` | 是否落 `traces.jsonl` |

---

## 6. 只读闸门与拒答

### 6.1 三道闸门

```text
① 应用层文本校验    剥离字符串字面量与注释 → 关键字 / 多语句 / 顶层 LIMIT
② 连接级只读        SQLite: mode=ro + PRAGMA query_only=ON
                    Postgres: default_transaction_read_only=on + SET TRANSACTION READ ONLY
③ 执行级兜底        5s statement_timeout + fetchmany(limit+1) 判截断
④ 工具入口统一      Web API / Agent run_sql / MCP stdio 走同一个 execute_readonly
```

第 ① 道是踩坑改出来的。最初对**整条 SQL** 做关键字扫描，结果：

- `SELECT REPLACE(name,'旧','新') FROM product` —— `replace` 是**函数名**，被当成写操作拒掉；
- `WHERE name LIKE '%a;b%'` —— 字符串里的分号被判成多语句。

现在先把字符串常量和 `--` / `/* */` 注释替换成占位符再校验，`REPLACE()` 移出黑名单
（由 `mode=ro` 兜底）。`LIMIT` 判定也从「全文出现过 limit」改成「只认顶层 limit」，
否则 `SELECT * FROM (SELECT … LIMIT 5)` 会让外层不加限制。

### 6.2 拒答分两层

| 层 | 处理对象 | 开销 | 入口 |
|---|---|---|---|
| 规则前置 | 闲聊、创作、实时行情、写操作、提示注入、`PRAGMA` / `ATTACH` / `VACUUM` | 0 次模型调用 | `guard.check` |
| 模型协议 | 语义模糊（缺指标/维度）、边界模糊（能否答） | 1 次生成 | `guard.parse_refusal` |

规则层最大的风险是**误伤**。第一版把 `(更新|删除|插入)\s*(记录|表)` 用非锚定匹配，
结果「查询订单状态**更新记录**」被判成写操作 —— 而这正好对应库里真实存在的 `order_status_log`。
现在改为整句锚定 + 查询动词白名单（查询/统计/列出/看一下/趋势/占比）+ 只读名词白名单
（记录/日志/流水/变更/表结构），并把 12 条易误伤语料固化进自测。

### 6.3 边界

- 不支持多语句、`ATTACH`、`PRAGMA` 写入、临时表；
- 不解析执行计划，不保证生成的 SQL 高效（只保证正确且只读）；
- 拒答建议会做一次「可答性」校验，避免给出系统其实答不了的问题。

---

## 7. 数据资产

| 资产 | 规模 | 用途 | 是否随仓库发布 |
|---|---|---|---|
| 电商演示库 `ecommerce.db` | 50 表 / 51,899 行 / 3.7 MB | 查询目标 | **否**（脚本生成） |
| 表元数据 `schema_meta.json` | 50 表，含中文名、列说明、枚举值 | 选表与上下文 | **否**（脚本生成） |
| 向量索引 `schema_index.json` | 50 条 / 1024 维 | 选表 | **否**（脚本生成） |
| 会话库 `app.db` | 运行期产生 | 会话、few-shot | **否** |
| 前端构建产物 `backend/static/` | 约 300 KB | 单进程托管 | **否**（`npm run build` 生成） |

> 仓库只保留建库/建索引脚本与前端源码。克隆后按第 8 节跑一次，即可得到与第 3 节截图一致的数据。

---

## 8. 快速开始

### 8.1 前置

- Python 3.11+（推荐 3.12）
- Node.js 18+（只在需要构建前端时需要）
- 两个 API Key：文本模型（魔搭）、embedding 模型（硅基流动）
- 不想申请 Key 时可用 `MOCK_MODE=true` 走本地伪向量 + 规则 SQL

### 8.2 环境变量

复制 `.env.example` 为 `.env`（**不要提交**）：

```bash
cp .env.example .env
```

| 分组 | 键 |
|---|---|
| 服务 | `HOST`、`PORT`、`PUBLIC_BASE_PATH`、`CORS_ORIGINS` |
| 鉴权 | `AUTH_USER`、`AUTH_PASSWORD`、`TOKEN_TTL_HOURS`、`SECRET_KEY` |
| 文本模型 | `LLM_BASE_URL`、`LLM_API_KEY`（优先）/ `MODELSCOPE_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT`、`LLM_MAX_TOKENS` |
| 向量模型 | `EMB_BASE_URL`、`SILICONFLOW_API_KEY`、`EMB_MODEL`、`EMB_DIM` |
| Agent | `AGENT_MODE`、`MAX_AGENT_STEPS`、`MAX_TOOL_SQL`、`TOP_K_TABLES`、`FK_EXPAND_MAX`、`MAX_SQL_RETRY`、`MAX_LLM_CALLS`、`AUTO_INSIGHT`、`EMPTY_RESULT_RETRY` |
| 语义 / 数据源 | `SEMANTIC_FILE`、`DATABASE_URL`（Postgres）、`COLUMN_LINK_TOPK`、`TOOL_ROW_PREVIEW` |
| 观测 / 记忆 | `TRACE_ENABLED`、`TRACE_RECENT`、`MEMORY_ENABLED` |
| 护栏 | `GUARD_ENABLED`、`GUARD_SUGGESTIONS`、`RATE_LIMIT_ENABLED`、`RATE_LIMIT_PER_MIN` |
| 开关 | `MOCK_MODE`、`AUTO_BUILD_INDEX`、`ALLOW_INSECURE` |

### 8.3 一键启动

```bash
git clone https://github.com/standbyme626/text2sql-agent.git
cd text2sql-agent
cp .env.example .env      # 填 MODELSCOPE_API_KEY / SILICONFLOW_API_KEY
bash run.sh               # Windows 双击 run.bat
```

`run.sh` 依次完成：建 venv → 装依赖 → 建库 → 建索引 → 构建前端（缺 npm 则跳过）→ 起服务。
浏览器打开 `http://127.0.0.1:3388`。

### 8.4 分步执行

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python backend/scripts/init_db.py       # 50 张表 + 模拟数据
.venv/bin/python backend/scripts/build_index.py   # 向量索引（约 1 次 embedding 调用）
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 3388
```

前端源码在 `frontend/`，构建后拷进 `backend/static/` 由后端托管：

```bash
cd frontend && npm install && npm run build && cd ..
rm -rf backend/static/* && cp -r frontend/dist/. backend/static/
```

### 8.4.1 切换到 PostgreSQL

```bash
pip install "psycopg[binary]"
DATABASE_URL=postgresql://user:pass@host:5432/db \
  python backend/scripts/build_meta_pg.py        # 内省生成 schema_meta.json
# 再把同一 DATABASE_URL 写进 .env，重启服务
```

Postgres 模式不建 SQLite 演示库；Agent、只读闸门、MCP 工具全部复用同一执行器。
`build_meta_pg.py` 会读取表/列注释、主键、外键、估算行数，语义层的 `dialects.postgres`
提供 `date_trunc` 日期函数。

### 8.5 Docker

```bash
docker compose up -d --build
```

首次启动自动建库。容器只映射到宿主机 `127.0.0.1:3388`，公网入口交给反代（见第 10 节）。

### 8.6 健康检查

```bash
curl -s http://127.0.0.1:3388/api/health          # {"ok":true,"auth_enabled":false}
curl -s http://127.0.0.1:3388/api/status -H "X-App-Token: <token>"
```

### 8.7 当前状态说明

克隆下来直接能用与不能用的：

- ✅ 建库脚本、选表索引构建、前端源码、部署模板齐全；
- ✅ `MOCK_MODE=true` 下全链路可跑，不消耗任何额度；
- ⚠️ `backend/static/` 与 `backend/data/` 为空，需按 8.3 / 8.4 生成；
- ⚠️ 真实问答需要 Key；只配文本模型也能跑（选表自动降级为关键词）；
- ✅ 不申请 Key 也能验证 2026 Agent 链路：`MOCK_MODE=true` 会走完整工具轨迹、语义层、trace、MCP、评测 harness；
- ❌ 仓库不含任何线上实例的域名、账号、密钥与数据库快照。

---

## 9. API

### 9.1 端点

除 `/api/health`、`/api/login` 外，其余端点都需要请求头 `X-App-Token`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 存活探针，仅返回 `ok` 与 `auth_enabled` |
| `POST` | `/api/login` | `{username,password}` → `{token,auth_required}` |
| `POST` | `/api/logout` | 撤销当前 token |
| `GET` | `/api/status` | 选表模式、索引错误、模型就绪度、各项开关 |
| `GET` | `/api/meta` | 50 张表元信息 |
| `GET` | `/api/tables/{name}` | 单表 DDL、字段说明、枚举值、样例行 |
| `POST` | `/api/query` | **SSE 流式问答** |
| `POST` | `/api/sql` | 用户编辑后重跑（仍受只读闸门约束，结果回写会话） |
| `POST` | `/api/explain` | 对已有结果重新生成结论 |
| `GET` | `/api/sessions` | 当前身份的会话列表 |
| `GET` | `/api/history?session_id=` | 会话完整消息（含结构化 payload） |
| `DELETE` | `/api/sessions/{id}` | 删除会话并级联清理 few-shot |
| `POST` | `/api/index/rebuild` | 重建向量索引（带冷却与并发锁） |
| `GET` | `/api/semantic` | 受治理指标目录、标准 JOIN、方言函数 |
| `GET` | `/api/tools` | Agent 工具定义（可审计） |
| `GET` | `/api/metrics` | 最近 N 条 trace 的 p50/p95、token、工具失败率 |
| `GET` | `/api/traces/{trace_id}` | 单次查询的 span 明细 |
| `GET/POST/DELETE` | `/api/memory` | 用户长期偏好：列出 / 写入 / 清空 |
| `DELETE` | `/api/memory/{id}` | 删除单条偏好 |

### 9.2 提问示例

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:3388/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"***"}' | jq -r .token)

curl -N -X POST http://127.0.0.1:3388/api/query \
  -H "X-App-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"各渠道销售额占比","session_id":null}'
```

### 9.3 SSE 事件

```text
event: session     data: {"session_id":"...","trace_id":"...","agent_mode":"toolloop"}
event: stage       data: {"key":"plan","label":"Agent 规划第 1 步"}
event: tables      data: {"tables":[{"name","cn","score","matched_columns"}]}
event: step        data: {"tool":"run_sql","ok":true,"ms":42.1,"args":{...},"error":""}
event: sql         data: {"sql":"SELECT ...","attempt":1}
event: retry       data: {"attempt":1,"error":"no such column: xxx"}
event: result      data: {"columns":[],"rows":[],"truncated":false,"chart":{},"message_id":42,"trace_id":"..."}
event: insight     data: {"summary":"...","followups":["..."]}
event: guidance    data: {"kind":"refuse","reason":"...","suggestions":["..."]}
event: error       data: {"message":"已脱敏的失败原因"}
event: done        data: {"message_id":42,"trace_id":"...","agent_mode":"toolloop","steps":2}
```

服务端每 15 秒发一次心跳注释行；客户端断开时生成器收到 `GeneratorExit`，
由 `finally` 补偿写入 assistant 占位消息，不产生孤立 user 消息。

### 9.4 MCP 接入

`backend/mcp_server.py` 把同一套只读工具通过 stdio 暴露给任意 MCP host：

```json
{
  "mcpServers": {
    "text2sql": {
      "command": "python",
      "args": ["backend/mcp_server.py"],
      "env": {"TEXT2SQL_DATA_DIR": "/abs/path/text2sql-agent/backend/data"}
    }
  }
}
```

- 支持 `initialize` / `tools/list` / `tools/call` / `ping`（MCP 2025-06-18）；
- 工具：`search_schema`、`run_sql`、`list_metrics`；不暴露写操作与记忆写入；
- stdout 只输出 JSON-RPC，日志走 stderr，便于 host 直接拉起；
- 与 Web Agent 共用 `clean_sql` + 只读连接，不存在「MCP 绕过闸门」的路径。

---

## 10. 部署

### 10.1 单机 + 反代

应用监听 `127.0.0.1:3388`，nginx 反代。**必须关掉响应缓冲**，否则 SSE 会被攒成一次性返回：

```nginx
location / {
    proxy_pass http://127.0.0.1:3388;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;   # 覆盖，防伪造 IP 绕过限流
    proxy_buffering off;                              # SSE 必须
    proxy_read_timeout 300s;
}
```

### 10.2 内网机器 + 公网反代（SSH 反向隧道）

没有公网 IP 的机器也能上线，且**不开放任何入站端口**：

```text
浏览器 → 公网反代机 nginx:443 → 127.0.0.1:3388（SSH 反向隧道）→ 内网应用机 FastAPI
```

| 文件 | 用途 |
|---|---|
| `deploy/text2sql.service` | 应用侧 systemd 单元（低权限用户 + 重启速率限制） |
| `deploy/text2sql-tunnel.service` | SSH 反向隧道常驻单元（`EDGE_SSH` 指定别名） |
| `deploy/text2sql-watchdog.{service,timer}` | 每 2 分钟探活，服务或隧道挂了自动重启 |
| `deploy/prepare-user.sh` | 建低权限账号并迁移权限 |
| `deploy/nginx-bootstrap.conf` / `nginx-site.conf` | 首签证书用 80 模板 / 最终 443 反代模板 |
| `deploy/setup-edge.sh` | 反代机一键上线：签发 → 覆盖配置 → 改续期方式 → 断言 401/200 |
| `deploy/fix-renewal.py` | certbot 续期改 `webroot + installer=None`，不再改写手工配置 |
| `deploy/gen_env.sh` | 从本机凭据文件注入 key 到 `.env`，值不回显 |

```bash
# 应用侧
sudo PROJ=/opt/text2sql-agent bash deploy/prepare-user.sh
sudo cp deploy/text2sql.service deploy/text2sql-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now text2sql text2sql-tunnel

# 反代机（模板里域名统一写作 sql.example.com，脚本会自动替换）
DOMAIN=sql.example.com sudo -E bash /tmp/text2sql-deploy/setup-edge.sh
```

三个容易踩的点：`ssh -R` 目标写 `127.0.0.1` 别写 `localhost`（可能只监听 `::1`）；
隧道下「公网可达」与 `HOST` 无关，所以未设 `AUTH_PASSWORD` 时服务**拒绝启动**；
`proxy_buffering off` 丢了，SSE 就退化成一次性返回。

---

## 11. 测试与验证

### 11.1 自测矩阵

```bash
MOCK_MODE=true .venv/bin/python backend/scripts/selftest.py
```

**130 项断言**，跑在独立临时数据目录上，不碰开发库、不消耗外部额度，结束自动清理。
覆盖新增的 tool-calling 循环（假模型注入）、语义层、列级 linking、trace、记忆、MCP 握手、eval 冒烟。

| 组 | 覆盖内容 |
|---|---|
| 鉴权 | 无 token 401 / 错密码限流 / 伪造 XFF 不绕过 / 改密后旧 token 失效 / 登出撤销 |
| 只读闸门 | 8 类合法只读 SQL 放行（含 `REPLACE()`、字符串内分号）/ 8 类写操作拦截 / 顶层 LIMIT / 截断标记 |
| 护栏 | 12 条易误伤的正常问题必须放行 / 7 类注入与越权必须拦截 / 建议问法可答性 |
| 会话 | 结果与结论完整还原 / 拒答不污染多轮 / few-shot 表名白名单 / 级联删除 |
| 迁移 | 老库缺 `payload` / `owner` 列时幂等迁移，历史消息仍可读 |
| 稳健性 | 上游超时与 429 不触发改 SQL 重试 / 单轮预算耗尽有明确错误事件 |
| 2026 Agent | 原生 tool_calls 假模型：search_schema → run_sql → DONE / 工具轨迹落库 |
| 语义 / 数据 | YAML 指标目录 / 列级 matched_columns / Postgres 连接器（人工验证） |
| MCP | initialize / tools/list / tools/call 只读执行（stdio 子进程） |
| 评测 | golden set harness mock 冒烟，执行准确率与失败分类输出 |

### 11.2 已人工验证过的路径

- 域名端到端 20 项（首页 200、未登录 API 401、带 token 200、SSE 事件序列、登录限流）；
- 会话切换：生成中切走、切回旧会话、旧会话无 payload 时只读重跑补齐（不耗额度）；
- 移动端：抽屉开合、图表窄屏重排、iOS 安全区、横滑表格；
- 反代：`certbot renew --dry-run` 通过，续期不再改写 nginx 配置。

### 11.3 执行准确率评测

```bash
# 零额度冒烟（规则 SQL 基线，不代表模型质量）
.venv/bin/python backend/scripts/eval.py --mode mock

# 真实模型（会消耗额度；需 MODELSCOPE_API_KEY）
.venv/bin/python backend/scripts/eval.py --mode real

# BIRD dev 子集（需自行下载数据集）
.venv/bin/python backend/scripts/eval.py --mode real --bird ~/BIRD/dev --limit 50
```

判定是**结果集一致**（默认忽略行序；参考 SQL 含 `ORDER BY LIMIT` 时按行序），
输出 `eval/report.json` + `eval/report.md`，含 Execution Accuracy、分类准确率、
逐条失败分类（`wrong_result` / `no_sql` / `sql_error` / `should_refuse`）与延迟。
BIRD 模式按 `difficulty` 分组统计，可作为模型/提示词改动的回归基线。

### 11.4 缺口

- **CI 已覆盖后端自测 + 前端构建**（`.github/workflows/ci.yml`，零 API Key）；
- **前端无单元测试**：只有人工回归；
- **golden set 规模有限**：24 条核心业务问法 + 3 条拒答，适合回归不替代 BIRD；
- **没有压测**：并发、长会话、大结果集的表现未量化。

---

## 12. 已知限制与未验证事项

1. **单账号**：鉴权是「一个账号 + HMAC token」，没有 RBAC；多人共用靠会话 owner 隔离，额度与审计按实例算；
2. **数据库方言**：已支持 SQLite / PostgreSQL；MySQL、BigQuery、Snowflake 还需补方言与只读连接器；
3. **50 表规模假设**：上千张表时 Top-K 会漏表，需要先选业务域再选表的分层检索（列级 linking 只缓解不根治）；
4. **语义层是轻量版**：YAML 指标 + 关键词匹配，不是 dbt metrics / MDL 那种带血缘、物化与审批的完整语义层；
5. **不做执行计划优化**：只保证「一条 SELECT 能跑对」，不保证快；
6. **洞察是单轮生成**：复杂归因（同比环比拆解）要靠下钻追问完成；
7. **BIRD 基线待跑**：harness 与数据集加载器已就绪，本仓库未附带 BIRD 数据与真实模型跑分（避免默认消耗额度）；
8. **未验证**：高并发、超长会话（>50 轮）、超大结果集、生产级审计合规。

---

## 13. 工程实践与踩坑

1. **先落库再推流**：SSE 客户端断开抛的是 `GeneratorExit`（属于 `BaseException`），
   `except Exception` 捕不到。原实现先 `yield` 后落库，导致库里 user 比 assistant 多一条，
   刷新即丢，还会把孤立 user 消息当一轮对话喂回模型。现在落库前置、单事务、`finally` 补偿。
2. **只读闸门要剥离字面量**：见 6.1，`REPLACE()` 与字符串里的分号都误伤过。
3. **护栏正则别用子串匹配**：「更新记录」把正常业务问法打成写操作，改整句锚定 + 动词白名单。
4. **`LIMIT` 只认顶层**：`SELECT * FROM (SELECT … LIMIT 5)` 的内层 LIMIT 不代表外层有界。
5. **截断判定要 `limit+1`**：注入 `LIMIT limit` 再 `fetchmany(limit+1)` 永远拿不到第 `limit+1` 行，
   `truncated` 恒为 False，洞察会拿截断样本算占比。
6. **XFF 只信最后一跳**：nginx 用 `$proxy_add_x_forwarded_for` 会保留客户端原值，限流可被伪造 IP 绕过；
   改成 `proxy_set_header X-Forwarded-For $remote_addr`，应用取末段。
7. **Windows 换行会毁掉脚本**：`.sh` 带 CRLF 在 Linux 上是 `bad interpreter`，
   仓库用 `.gitattributes` 强制 `eol=lf`，只有 `.bat` 用 CRLF。
8. **推理模型可能只吐 `reasoning_content`**：`content` 为空时要回落读该字段，否则表现为「模型返回空」。
9. **模型会答英文**：统一语言闸门 + 非中文回灌改写 + 历史英文回答屏蔽。
10. **nginx 的 Basic auth 会挡住登录页**：未带凭据返回原生 401 白页，移动端还弹不出输入框；
    改为应用层登录页，nginx Basic 只作可选第二层。

> 30 项加固的完整清单（含根因、修法与验收标准）见 [`docs/ENGINEERING-NOTES.md`](docs/ENGINEERING-NOTES.md)。

---

## 14. 目录结构

```text
text2sql-agent/
├── backend/
│   ├── app/
│   │   ├── main.py            # 路由 / SSE / 静态托管 / 错误脱敏
│   │   ├── agent.py           # toolloop / workflow 双模编排
│   │   ├── tools.py           # 工具注册表：search_schema / run_sql / metrics / memory
│   │   ├── tracing.py         # trace / span / token / p50-p95 / 工具失败率
│   │   ├── semantic.py        # YAML 语义层加载与 prompt 注入
│   │   ├── guard.py           # 拒答护栏：规则前置 + 【拒答】协议解析
│   │   ├── db.py              # SQLite / Postgres 只读执行器 + 图表建议
│   │   ├── schema_index.py    # 向量选表 + 列级 linking + 外键闭包
│   │   ├── store.py           # 会话 / 消息 / few-shot / 用户长期记忆
│   │   ├── auth.py            # HMAC token / 登录限流 / token 撤销
│   │   ├── llm.py             # OpenAI 兼容客户端 + SQL 提取 + 语言规则
│   │   ├── embedding.py       # 向量模型客户端 + 伪向量（Mock）
│   │   ├── config.py          # 全部配置，只从 .env 读
│   │   └── models.py          # 请求体校验
│   ├── scripts/
│   │   ├── schema.py          # 50 张表定义（中文注释）
│   │   ├── init_db.py         # 建库 + 模拟数据 + 元数据
│   │   ├── build_index.py     # 构建向量索引
│   │   ├── build_meta_pg.py   # Postgres 内省 → schema_meta.json
│   │   ├── eval.py            # golden / BIRD 执行准确率评测
│   │   └── selftest.py        # 130 项全链路自测
│   ├── semantic/metrics.yaml  # 受治理指标层（唯一真相）
│   ├── mcp_server.py          # MCP stdio server（只读工具）
│   └── data/                  # 运行期生成（.gitignore）
├── frontend/src/              # Vue 3 源码
│   └── components/            # ResultPanel / SchemaPanel / SqlBlock
├── deploy/                    # systemd / nginx / 隧道 / 证书 / 上线脚本
├── eval/
│   └── golden.yaml            # 26 条业务 golden + 3 条拒答
├── docs/
│   ├── ENGINEERING-NOTES.md   # 设计取舍、加固清单、自测矩阵
│   └── screenshots/
├── Dockerfile / docker-compose.yml
├── run.sh / run.bat
└── .env.example
```

---

## 15. 安全须知

| 面 | 做法 |
|---|---|
| 认证 | 应用层登录页 + HMAC token（`X-App-Token`），签名绑定密码版本，改密/换 `SECRET_KEY` 后旧 token 立即失效 |
| 限流 | 登录失败按 IP 计数并封禁；高消耗端点按 token+IP 滑动窗口；只信任反代覆盖后的远端 IP |
| 只读 | 剥离字面量后校验；单语句；顶层 LIMIT；5s 超时；SQLite `mode=ro` + `query_only`；Postgres 默认事务只读 + `statement_timeout` |
| 越权 | 拦截写操作、`PRAGMA` / `ATTACH` / `VACUUM`、`randomblob` 资源耗尽、提示注入变体 |
| 数据隔离 | 会话绑定 owner，列表/历史/删除均按身份过滤 |
| 静态资源 | SPA 兜底路径做 `resolve()` 前缀校验，杜绝 `../` 读到 `.env` / `.secret_key` |
| 错误 | 异常类名、SQLite 报错、上游响应正文只进服务端日志，客户端只见稳定文案 |
| 密钥 | 仅 `.env`（600），数据目录 0700，`.secret_key` 用 `O_EXCL` 创建；不进 Git、不打进镜像、不写日志 |

> 把带执行能力的服务挂上公网前，至少确认三件事：有认证、有出入站限制、有日志与告警。
> 无鉴权的公网 Web 服务被扫描器打穿只是时间问题。

---

## 16. Roadmap

- [x] 接入 Postgres（只读事务 + `statement_timeout` + schema 内省）
- [x] 指标口径 YAML（轻量语义层）替代自由文本业务口径
- [x] 列级 schema linking（表级 Top-K 之外的列命中）
- [x] 执行正确率评测（golden set + BIRD dev 加载器）
- [x] Tool-calling Agent loop + MCP stdio server
- [x] Trace 观测（OTel 语义兼容 JSONL + `/api/metrics`）
- [x] 跨会话用户偏好记忆（显式写入 + 召回）
- [ ] 千表规模的分层检索（先选业务域，再选表）
- [ ] MySQL / BigQuery / Snowflake 连接器
- [x] CI：`MOCK_MODE` 自测 + 前端构建 + golden 回归
- [ ] 结果集增量对比（同名查询跑两次看变化）

## License

[MIT](LICENSE)
