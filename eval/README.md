# Eval · 执行准确率

判定标准是 **Execution Accuracy**：候选 SQL 与参考 SQL 在同一个库上执行后的结果集一致，
不是 SQL 字符串相似度。默认忽略行序；参考 SQL 同时包含 `ORDER BY` 与 `LIMIT` 时按行序比较
（Top-N 语义）。数值按 4 位小数归一化。

## 命令

```bash
# 零额度冒烟：规则 SQL 基线，只验证 harness 与链路，不代表模型质量
.venv/bin/python backend/scripts/eval.py --mode mock

# 真实模型（会消耗额度）
.venv/bin/python backend/scripts/eval.py --mode real

# BIRD dev 子集（需先下载 BIRD，放到 ~/BIRD/dev）
.venv/bin/python backend/scripts/eval.py --mode real --bird ~/BIRD/dev --limit 50
```

产物：`eval/report.json`（机器可读）+ `eval/report.md`（逐条用例），均已 gitignore。

## golden.yaml 结构

```yaml
cases:
  - id: gmv_monthly
    category: time          # time / join / dimension / ops / guard
    question: 近 12 个月每月的销售额趋势
    sql: SELECT ...         # 参考 SQL；expect_refusal=true 时可省略
    expect_refusal: false
```

## 失败分类

| 分类 | 含义 |
|---|---|
| `wrong_result` | SQL 可执行，但结果集与参考 SQL 不一致 |
| `no_sql` | 模型没有输出可执行 SQL |
| `sql_error` | 候选 SQL 执行失败 |
| `refusal` / `should_refuse` | 该答却拒答 / 该拒答却作答 |
| `gold_sql_error` | golden 参考 SQL 自身执行失败（数据集问题） |

> mock 模式的准确率只用于确认 harness 工作正常；真实模型跑分请使用 `--mode real`，
> 并把 `eval/report.md` 作为提示词/模型/语义层改动的回归基线。
