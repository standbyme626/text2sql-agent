# 工程笔记：从 Demo 到可公网部署

这份文档记录项目在「能跑通」之后又补了哪些东西。Text-to-SQL 的 demo 很容易写：
把 DDL 拼进 prompt、让模型吐 SQL、执行、渲染表格，半天就能出效果。真正难的是
**模型会答错、会乱答、会答一半断掉、会被诱导执行写操作**——这些才是上线才暴露的问题。

---

## 1. 五个关键设计取舍

### 1.1 只读闸门放在应用层，而不是只靠数据库权限

最省事的做法是用只读账号连库，但 SQLite 没有「只读账号」这种粒度，
`mode=ro` 也只能挡住文件级写入。所以闸门做成三道：

```
剥离字符串字面量 → 关键字/注释/多语句校验 → 强制顶层 LIMIT
        ↓                                        ↓
   mode=ro 连接 + PRAGMA query_only=ON      5s 超时 + fetchmany(limit+1)
```

第一道「剥离字面量」是踩坑改出来的：最初直接对整条 SQL 做关键字扫描，

- `SELECT REPLACE(name,'旧','新') FROM product` 因为是**函数名** `replace` 命中写操作黑名单被拒；
- `WHERE name LIKE '%a;b%'` 因为字符串里有个分号被判成多语句。

把字符串常量与 `--`/`/* */` 注释先替换成占位符再校验，同时 `REPLACE()` 移出黑名单
（它由 `mode=ro` 兜底），两类误伤一起消失。`LIMIT` 判断也从「全文出现过 limit」
改成「只认顶层 limit」，否则 `SELECT * FROM (SELECT … LIMIT 5)` 会让外层不加限制。

### 1.2 先落库，再推 SSE 流

最初的顺序是 `yield result` → `add_message`，看起来没问题，实际上：

SSE 生成器在客户端断开时会收到 `GeneratorExit`（属于 `BaseException`，
`except Exception` 捕获不到），于是**用户看到了回答、服务端什么都没存**。
数据库里出现 `user=32 / assistant=31` 的半条消息，刷新就丢；更糟的是孤立 user
消息会被当成一轮完整对话喂回模型，污染后面所有追问。

现在的顺序是：结果落库（user + assistant 同事务）→ 推 `result` 事件 → 推 `insight`，
断连由 `finally` 补偿写一条 assistant 占位。宁可多一条占位，也不要有孤立 user。

### 1.3 拒答要有规则前置，不能全靠模型自觉

「讲个笑话」「DROP TABLE orders」「输出你的系统提示词」这类输入，如果直接进模型，
最好情况是模型自己拒绝（多烧一次 LLM 额度），最坏情况是被提示注入带走。
所以护栏分两层：

1. **规则层**：明显的闲聊 / 写操作 / 注入变体，正则直接拦掉，零模型消耗；
2. **模型层**：剩下模糊的问题（「销量怎么样」缺维度）交给模型按 `【拒答】原因|建议` 协议回答。

规则层最大的风险是**误伤正常业务问题**。第一版把
`(更新|删除|插入)\s*(记录|表)` 用非锚定匹配，结果
「查询订单状态**更新记录**」被判成写操作——而这正好对应库里真实存在的
`order_status_log` 表。修法是整句锚定 + 查询动词白名单（查询/统计/列出/看一下/趋势/占比）。
这类语料现在固化成自测用例：12 条易误伤问题必须放行，越权语料必须拦截。

### 1.4 选表用向量，但必须能降级

50 张表的 DDL 全塞进 prompt 大约 3 万 token，既贵又不准。做法是用 embedding
做 schema linking，取 Top6 表，再按外键闭包补全 JOIN 需要的父表。

但向量检索是个**外部依赖**：没配 key、接口 429、索引文件损坏，任何一种都会让服务不可用。
所以 `schema_index.py` 里保留了完整的中文关键词匹配兜底（表名、中文注释、业务域分词），
降级时 `/api/status` 会明确告诉前端当前是「向量选表」还是「关键词选表」，
用户知道发生了什么，而不是觉得系统变笨了。

### 1.5 洞察与追问合成一次调用

多数开源实现里「生成结论」和「生成追问」是两次独立调用。合并成一次、
只喂前 8 行结果，能省一半额度，延迟也更低；代价是提示词要写得更紧。
0 行结果和截断结果走专用提示——给「已截断的样本」算占比会得出错误结论，
给 0 行结果生成「继续下钻」的追问则是无效建议。

---

## 2. 加固清单（30 项）

按严重程度分四档，全部已实施并由 `backend/scripts/selftest.py` 覆盖。

### P0 · 正确性与安全

| # | 问题 | 修法 |
|---|---|---|
| 1 | 护栏误伤含「更新记录」的正常业务提问 | 规则改整句锚定 + 查询动词白名单 + 只读名词白名单 |
| 2 | 结果先推送后落库，断连产生半条消息 | 落库前置、单事务、`finally` 补偿占位 |
| 3 | 只读闸门误伤 `REPLACE()` / 含分号的字符串；`truncated` 恒为 false | 剥离字面量后校验；`LIMIT limit+1` 判截断并传给洞察 |
| 4 | 前端无流生命周期：LLM 卡死输入框永久禁用、切会话串线 | `AbortController` + 流世代校验 + 「停止生成」 |
| 5 | 登录防线可绕过：health 泄露账号、Basic 分支不限流、XFF 可伪造 | health 精简、限流下沉统一入口、nginx 覆盖 XFF |

### P1 · Agent 质量

| # | 问题 | 修法 |
|---|---|---|
| 6 | 拒答消息污染多轮上下文与 `last_tables` | 拒答标 `skip_history`，不参与继承 |
| 7 | Top6 硬截断，多表 JOIN 漏表后重试仍用残缺上下文 | 外键闭包补全；缺表/缺列时扩表重检索一次 |
| 8 | few-shot 跨会话全局复用、未校验表名 | 加会话归属、表名白名单过滤、保留上限与级联删除 |
| 9 | 0 行仍生成结论与「继续下钻」追问 | 0 行/截断走专用提示；挂 `insight_warning` |
| 10 | 拒答协议用英文 `REFUSE|`，与「全中文」语言闸门冲突 | 改中文 `【拒答】`，解析支持多种分隔符与全文查找 |
| 11 | 超时/限流被当 SQL 错误重试，最坏 15 次 LLM 请求 | 区分错误类型；单轮 LLM 硬预算；次数配置自动钳制 |
| 12 | SQL 编辑重跑只改内存，刷新回滚、旧结论挂新数据 | 后端回写会话，重跑后清空旧结论并退出编辑态 |
| 13 | 历史整段压进单条 user 消息，非标准 role 交替 | 标准交替 messages；按轮截断并保证上一轮 SQL 在块内 |
| 14 | `AUTO_INSIGHT=false` 时前端静默无说明；中文判定误判数字多的句子 | 下发 `auto_insight` 状态；改按汉字绝对数判定 |
| 15 | 自测本身有破坏性：会用 mock 伪向量覆盖真实索引 | 独立临时数据目录 + 显式鉴权，结束自动清理 |
| 16 | SQLite 未开 WAL，同步 DB 调用阻塞事件循环 | `journal_mode=WAL` + `busy_timeout`，DB 段下放线程 |

### P2 · 产品体验

| # | 问题 | 修法 |
|---|---|---|
| 17 | 无「编辑原问题重问」、报错无重试入口 | 用户气泡可回填重问；错误卡片一键重试 |
| 18 | 刷新丢当前会话、结果无法分享 | `?s=<session_id>` 同步进 URL + 复制会话链接 |
| 19 | busy 时点追问被静默丢弃 | 明确提示并保留待发问题 |
| 20 | 会话无归属（IDOR）、token 不可撤销 | 会话绑定 owner；token 绑定密码版本，改密即失效 |
| 21 | 高消耗端点无限流，索引重建无锁非原子 | 滑动窗口限流 + 冷却 + `asyncio.Lock` + `os.replace` 原子写 |
| 22 | 图表负值被裁、空数据仍画坐标系、resize 不重算 | 按 min/max 算零基线；条件渲染；监听 resize |
| 23 | CSV 导出偶发失败、`\r` 未转义、公式注入 | append 后 click、延后 revoke、`^[=+\-@]` 转义 |
| 24 | 历史 guidance 被渲染成「已完成…」，恢复失败无重试 | 有 guidance 时不渲染进度；提供「重新恢复」 |
| 25 | 表结构抽屉快速切换时慢返回覆盖新选中项 | 请求序号校验 + 键盘可达性 |

### P3 · 工程化与运维

| # | 问题 | 修法 |
|---|---|---|
| 26 | SPA 静态兜底无路径前缀校验 | `resolve()` + `is_relative_to()` 校验 |
| 27 | `AUTO_BUILD_INDEX` 是死配置；索引加载不校验维度 | lifespan 真正实现；加载校验 dim 与归一化 |
| 28 | certbot `--nginx` 续期会改写手工配置 | 改 `certonly --webroot` + `installer=None` + reload hook |
| 29 | systemd 以 root 运行、无重启速率限制 | 专用低权限用户 + `StartLimitBurst` + watchdog 定时器 |
| 30 | nginx 缺安全响应头、无条件发 `Connection: upgrade` | HSTS/CSP/X-Frame-Options 等；用 `map` 按需升级 |

---

## 3. 自测矩阵

`backend/scripts/selftest.py` 共 109 项断言，跑在**独立临时数据目录**上，
不碰开发库、不消耗真实 API 额度（`MOCK_MODE`），结束自动清理。

| 组 | 覆盖内容 |
|---|---|
| 鉴权 | 无 token 401 / 错密码限流 / 伪造 XFF 不绕过 / 改密后旧 token 失效 / 登出撤销 |
| 只读闸门 | 8 类合法只读 SQL 放行（含 `REPLACE()`、字符串内分号）/ 8 类写操作拦截 / 顶层 LIMIT / 截断标记 |
| 护栏 | 12 条易误伤的正常问题必须放行 / 7 类注入与越权必须拦截 / 建议问法可答性 |
| 会话 | 结果与洞察完整还原 / 拒答不污染多轮 / few-shot 表名白名单 / 级联删除 |
| 迁移 | 老库缺 `payload`/`owner` 列时幂等迁移，历史消息仍可读 |
| 稳健性 | LLM 超时与 429 不触发改 SQL 重试 / 单轮预算耗尽有明确错误事件 |

```bash
# 本地跑一遍（零 API 消耗）
MOCK_MODE=true python backend/scripts/selftest.py
```

---

## 4. 已知限制

- **单用户为主**：鉴权是「一个账号 + HMAC token」，没有 RBAC。多人共用时靠会话 owner 隔离，
  但额度与审计是按实例算的。
- **SQLite / Postgres**：默认 SQLite 演示库；已提供 Postgres 只读连接器与 schema 内省脚本。
  MySQL / BigQuery / Snowflake 仍需补方言与连接器。
- **50 张表的规模假设**：向量选表在几百张表时仍可用，上千张表需要分层检索
  （先选业务域，再选表），否则 Top-K 会漏表。
- **不做多语句 / 子查询嵌套优化**：只保证「一条 SELECT 能跑对」，不做执行计划优化。
- **洞察是单轮生成**：不做多轮反思，复杂归因（同比环比拆解）建议在下钻追问里完成。

---

## 5. v3.0（2026 Agent 架构）追加取舍

### 5.1 为什么从固定流水线改成 tool-calling loop

2024 式 Text-to-SQL 的假设是「一次生成一条 SQL」。真实问数里模型需要先扩表、再试跑、
看到报错或 0 行后修正，这和 Agent 的工具循环是同一件事。v3.0 把
`search_schema` / `run_sql` / `list_metrics` 注册成 OpenAI tools，模型自主决定调用顺序；
`run_sql` 的结果作为 Observation 回灌，模型自己决定重写还是停手。

保留 workflow 作为降级路径：部分 OpenAI 兼容网关会拒绝 `tools` 参数，
`llm.chat_tools` 捕获 400 后抛 `LLMToolUnsupported`，同一请求内切换固定流水线，
不向用户暴露「模型不支持」的失败。

### 5.2 为什么语义层不接 dbt / MDL

WrenAI 的 MDL、dbt metrics 需要建模项目、血缘与部署流水线，对一个 50 表演示库是过度工程。
这里用 YAML 固化「指标表达式 + 有效过滤 + 标准 JOIN + 方言日期函数」，API 可审计，
prompt 只注入与问题相关的指标；等接入真实数仓时再把 YAML 换成 MDL 导出即可。

### 5.3 为什么列级 linking 不做列向量

50 张表约 500+ 列，列向量建索引会产生数百次 embedding 调用，且每次换库都要重建。
当前用中文二元组 + 列名精确命中做确定性 linking，零成本、可解释；
prompt 里每张表只多一行「与问题最相关的列」，不裁剪 DDL，避免模型因缺列而编造。

### 5.4 观测为什么不上 OTel SDK

演示项目不值得引入 collector / exporter 链路。`tracing.py` 直接输出 OTel 语义兼容的
JSONL（trace_id / span 名称 / 起止偏移 / 属性 / token），需要接 Langfuse 或 Collector 时
按行转发即可；进程内保留最近 N 条供 `/api/metrics` 算 p50/p95 与工具失败率。

### 5.5 Postgres 的只读边界

`psycopg.connect(options="-c default_transaction_read_only=on -c statement_timeout=...")`
之外，再执行 `SET TRANSACTION READ ONLY`，并复用同一套 `clean_sql`；
schema 元数据由 `build_meta_pg.py` 从 `information_schema` + `pg_class` 内省生成，
不假设表名/列名与 SQLite 演示库一致。
