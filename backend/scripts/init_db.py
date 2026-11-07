# -*- coding: utf-8 -*-
"""
初始化电商 SQLite 演示库：建 50 张表 + 生成关联一致的模拟数据 + 导出表元数据。

用法：
    python backend/scripts/init_db.py            # 已存在则覆盖重建
    python backend/scripts/init_db.py --keep     # 已存在则跳过

产物：
    backend/data/ecommerce.db       SQLite 数据库
    backend/data/schema_meta.json   表结构元数据（中文名/列说明/枚举值/样例值）
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import TABLES, ddl_of, table_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "ecommerce.db"
META_PATH = DATA_DIR / "schema_meta.json"

SEED = 20261107
START_DATE = date(2024, 1, 1)
END_DATE = date(2026, 11, 7)
DATE_SPAN = (END_DATE - START_DATE).days

CATEGORIES = ["手机数码", "电脑办公", "家用电器", "服饰鞋包", "美妆个护", "食品生鲜",
              "家居家装", "母婴玩具", "运动户外", "图书文娱", "汽车用品", "宠物生活",
              "耳机耳麦", "智能穿戴", "厨房小电", "男装", "女装", "童装", "护肤彩妆",
              "休闲零食", "粮油调味", "收纳清洁", "健身器材", "文创礼品"]
BRANDS = ["星河", "云屿", "沐光", "拓界", "简素", "知造", "橙野", "拾光", "青芒", "木川",
          "极昼", "栖谷", "朗跃", "墨白", "禾作", "鹿鸣", "岸森", "北辰", "初见", "远山",
          "格物", "南风", "鲸落", "半山", "亦物", "叁两", "有度", "未至", "新语", "和光"]
PRODUCTS = ["无线蓝牙耳机", "智能手表", "机械键盘", "保温杯", "冲锋衣", "扫地机器人",
            "咖啡机", "护眼台灯", "运动跑鞋", "双肩背包", "空气炸锅", "移动电源",
            "降噪耳机", "智能音箱", "电动牙刷", "瑜伽垫", "遮阳伞", "陶瓷餐具",
            "真皮钱包", "儿童积木", "筋膜枪", "显示器支架", "香薰加湿器", "速干T恤",
            "羊毛围巾", "玻璃水杯", "无线充电器", "露营折叠椅", "宠物自动喂食器", "手冲咖啡壶"]
CITY_PROVINCE = {
    "深圳": "广东", "广州": "广东", "东莞": "广东", "佛山": "广东",
    "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
    "杭州": "浙江", "宁波": "浙江", "苏州": "江苏", "南京": "江苏",
    "成都": "四川", "武汉": "湖北", "西安": "陕西", "长沙": "湖南",
    "郑州": "河南", "青岛": "山东", "厦门": "福建", "合肥": "安徽",
}
SURNAMES = list("张李王刘陈杨赵黄周吴徐孙马朱胡郭何高林罗")
GIVEN = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰",
         "娟", "涛", "明", "超", "霞", "晨", "宇", "欣", "悦", "琳", "博", "睿"]
SPECS = ["黑色/128G", "白色/256G", "灰色/标准版", "蓝色/L", "米色/M", "红色/Pro",
         "银色/套餐一", "绿色/单人装", "深空灰/升级款", "杏色/两件套"]
CARRIERS = ["顺丰速运", "京东物流", "中通快递", "圆通速递", "韵达快递", "邮政EMS"]
REASONS = ["质量问题", "尺寸不符", "不喜欢", "发错货", "物流破损", "重复下单"]
KEYWORDS = ["蓝牙耳机", "运动鞋", "咖啡机", "保温杯", "扫地机器人", "冲锋衣", "键盘",
            "智能手表", "空气炸锅", "双肩包", "加湿器", "瑜伽垫", "露营椅", "儿童积木"]

STATUS_MAP = {
    "products": ["on_sale", "on_sale", "on_sale", "off_sale", "draft"],
    "orders": ["completed", "completed", "completed", "shipped", "paid", "pending", "cancelled", "refunded"],
    "payments": ["success", "success", "success", "failed", "pending", "refunded"],
    "shipments": ["delivered", "delivered", "in_transit", "exception", "pending"],
    "carts": ["active", "converted", "abandoned"],
    "refunds": ["done", "approved", "applied", "rejected"],
    "return_requests": ["refunded", "approved", "received", "applied", "rejected"],
    "support_tickets": ["resolved", "closed", "open", "pending"],
    "coupon_codes": ["used", "unused", "unused", "expired"],
    "flash_sales": ["ended", "ended", "running", "upcoming"],
    "purchase_orders": ["received", "received", "submitted", "draft", "cancelled"],
    "gift_cards": ["active", "active", "used", "expired"],
    "invoices": ["company", "personal"],
    "banners": ["home", "category", "activity"],
    "notifications": ["order", "promo", "system", "points"],
    "user_events": ["view", "view", "view", "add_cart", "favorite", "purchase", "share"],
    "stock_movements": ["inbound", "outbound", "outbound", "adjust"],
    "order_status_log": ["pending", "paid", "shipped", "completed", "cancelled"],
    "support_tickets.category": ["物流", "退款", "商品", "发票", "其他"],
    "support_tickets.priority": ["normal", "normal", "high", "low", "urgent"],
}

DEFAULT_STATUS = ["active", "active", "inactive", "pending", "done"]


def rnd_date(rng: random.Random) -> str:
    return (START_DATE + timedelta(days=rng.randint(0, DATE_SPAN))).isoformat()


def topo_order(tables):
    """按外键依赖拓扑排序，保证被引用的表先生成。"""
    by_name = {t["name"]: t for t in tables}
    order, visited, visiting = [], set(), set()

    def visit(name):
        if name in visited:
            return
        if name in visiting:  # 自引用等环，直接放过
            return
        visiting.add(name)
        for ref_table, _ in by_name[name]["fks"].values():
            if ref_table in by_name and ref_table != name:
                visit(ref_table)
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for t in tables:
        visit(t["name"])
    return [by_name[n] for n in order]


def build_pools(conn, t, rows):
    """缓存主键 / 外键可用值。"""
    return rows


def gen_value(rng, t, c, i, pools, row):
    name, typ = c["name"], c["type"]
    table = t["name"]

    if name == t["pk"]:
        return i + 1

    if name == "parent_id":
        return rng.choice([0, 0, 0, 0] + list(range(1, 13)))

    if name in t["fks"]:
        ref_table, ref_col = t["fks"][name]
        values = pools.get((ref_table, ref_col), [])
        return rng.choice(values) if values else 0

    low = name.lower()

    # 日期 / 时间
    if any(k in low for k in ("date", "_at", "time", "year")) and typ == "TEXT":
        return rnd_date(rng)
    if "founded_year" in low or low == "year" or typ == "INTEGER" and "year" in low:
        return rng.randint(1980, 2020)
    if low in ("level",):
        return rng.randint(1, 2)

    # 状态 / 类型枚举
    if low in ("status", "type", "event_type", "category", "priority", "reason",
               "channel", "gender", "segment", "condition", "sender", "operator",
               "device", "input_type", "position") or low.endswith("_status"):
        key = f"{table}.{low}"
        choices = STATUS_MAP.get(key) or STATUS_MAP.get(table) or DEFAULT_STATUS
        if low.endswith("_status"):
            choices = STATUS_MAP["order_status_log"]
        elif low == "channel":
            choices = ["app", "app", "web", "miniapp", "offline"]
        elif low == "gender":
            choices = ["male", "female", "unknown"]
        elif low == "segment":
            choices = ["新客", "普通", "高价值", "沉睡"]
        elif low == "reason" and table == "points_ledger":
            choices = ["下单", "签到", "退款", "兑换"]
        elif low == "reason" and table in ("return_requests", "refunds"):
            choices = REASONS
        elif low == "sender":
            choices = ["customer", "agent"]
        elif low == "operator":
            choices = ["system", "customer", "admin"]
        elif low == "device":
            choices = ["ios", "android", "web"]
        elif low == "condition":
            choices = ["unopened", "used", "damaged"]
        elif low == "input_type":
            choices = ["select", "text"]
        elif low == "category" and table == "attribute_defs":
            choices = CATEGORIES[:6]
        return rng.choice(choices)

    # 金额类
    if any(k in low for k in ("amount", "price", "cost", "fee", "total", "balance",
                              "budget", "value", "pay", "discount", "refund")) and typ == "REAL":
        if "rate" in low or low in ("discount", "value", "fee_rate"):
            return round(rng.uniform(0.05, 0.9), 4)
        return round(rng.uniform(19.9, 2999.0), 2)
    if "min_amount" in low or "min_order_amount" in low:
        return round(rng.choice([99, 199, 299, 499, 999]) * 1.0, 2)

    # 数量类
    if any(k in low for k in ("qty", "quantity", "count", "capacity", "points",
                              "stock", "num", "total_qty", "sort_order", "click")) and typ == "INTEGER":
        return rng.randint(0, 500)
    if "rating" in low and typ == "REAL":
        return round(rng.uniform(3.0, 5.0), 1)
    if "rating" in low and typ == "INTEGER":
        return rng.randint(1, 5)
    if low.startswith("is_") or low in ("is_active", "is_default", "is_main", "is_visible", "is_read"):
        return rng.choice([0, 1, 1, 1])

    # 文本语义
    if low == "email":
        return f"user{rng.randint(1000, 99999)}@example.com"
    if low in ("phone", "mobile"):
        return f"1{rng.choice('35789')}{rng.randint(10**8, 10**9 - 1)}"
    if low == "city":
        return rng.choice(list(CITY_PROVINCE))
    if low == "province":
        return CITY_PROVINCE[rng.choice(list(CITY_PROVINCE))]
    if low == "country":
        return rng.choice(["中国", "日本", "德国", "美国", "韩国", "意大利"])
    if low in ("name", "title") and table in ("categories",):
        return CATEGORIES[i % len(CATEGORIES)]
    if low == "name" and table == "brands":
        return BRANDS[i % len(BRANDS)]
    if low == "name" and table == "attribute_defs":
        return ["材质", "颜色", "尺寸", "重量", "功率", "容量", "适用人群", "产地", "保修期",
                "接口", "屏幕尺寸", "电池容量", "面料", "风格", "季节", "包装清单", "认证", "电压"][i % 18]
    if low == "name" and table == "memberships":
        return ["普通会员", "银卡会员", "金卡会员", "铂金会员", "钻石会员"][i % 5]
    if low == "name" and table == "payment_methods":
        return ["支付宝", "微信支付", "银行卡", "账户余额", "花呗", "货到付款"][i % 6]
    if low == "name" and table == "tags":
        return ["新品", "爆款", "包邮", "限时特惠", "自营", "进口", "热卖", "清仓", "优选",
                "直播专享", "会员价", "赠品", "国货", "轻奢", "环保", "大容量", "便携",
                "静音", "儿童适用", "礼盒装"][i % 20]
    if low == "name" and table == "warehouses":
        return ["华东仓", "华南仓", "华北仓", "西南仓", "华中仓", "东北仓", "西北仓", "前置仓"][i % 8]
    if low == "name" and table == "suppliers":
        return BRANDS[i % len(BRANDS)] + rng.choice(["供应链", "实业", "贸易有限公司"])
    if low == "name" and table == "wishlists":
        return rng.choice(["我的收藏", "想买的", "生日清单", "囤货清单"])
    if low in ("name", "title") and table in ("promotions", "flash_sales", "coupons", "banners", "customer_groups"):
        return rng.choice(["双11大促", "618年中庆", "年货节", "春日焕新", "会员日", "开学季",
                           "国庆特惠", "清凉一夏", "限时秒杀", "新客专享", "满减专场", "品牌日"]) + str(i % 9 + 1)
    if low == "name":
        return rng.choice(PRODUCTS) + rng.choice(["", " Pro", " 青春版", " 升级款"])
    if low == "receiver" or low == "contact":
        return rng.choice(SURNAMES) + rng.choice(GIVEN)
    if low in ("carrier",):
        return rng.choice(CARRIERS)
    if low == "spec":
        return rng.choice(SPECS)
    if low == "keyword":
        return rng.choice(KEYWORDS)
    if low in ("content", "description", "detail", "message"):
        return rng.choice(["质量很好，会回购", "物流很快，包装完整", "和描述一致，满意",
                           "一般般，性价比尚可", "客服态度不错，已解决", "尺寸偏小，建议拍大一码",
                           "用了一周再来评价，挺好用", "有问题已联系客服处理"])
    if low in ("url", "link_url"):
        return f"https://cdn.example.com/{table}/{i + 1}.jpg"
    if low.startswith(("code", "sku_code", "barcode", "trade_no", "tracking_no", "order_no", "tax_no")):
        prefixes = {"order_no": "SO", "trade_no": "PAY", "tracking_no": "SF",
                    "tax_no": "91", "sku_code": "SKU", "barcode": "69"}
        p = next((v for k, v in prefixes.items() if low.startswith(k)), "CD")
        return f"{p}{rng.randint(10**9, 10**10 - 1)}"
    if low in ("unit",):
        return rng.choice(["件", "kg", "cm", "W", "ml", "寸", ""])
    if low in ("color",):
        return rng.choice(["#FF6B6B", "#4ECDC4", "#FFD166", "#6A67CE", "#06D6A0"])

    if typ == "REAL":
        return round(rng.uniform(0, 1000), 2)
    if typ == "INTEGER":
        return rng.randint(0, 1000)
    return rng.choice(["标准", "常规", "已处理", "待跟进", "A档", "B档", "华东", "华南"])


def make_core_rows(rng, table, n, pools):
    """为最核心的 4 张表生成业务逻辑自洽的数据。"""
    name = table["name"]
    rows = []
    if name == "products":
        for i in range(n):
            price = round(rng.uniform(39, 2599), 2)
            rows.append({
                "product_id": i + 1,
                "category_id": rng.choice(pools[("categories", "category_id")]),
                "brand_id": rng.choice(pools[("brands", "brand_id")]),
                "name": PRODUCTS[i % len(PRODUCTS)] + rng.choice(["", " Pro", " 青春版", " 升级款", " 礼盒装"]),
                "sku_code": f"SPU{i + 1:06d}",
                "price": price,
                "cost": round(price * rng.uniform(0.45, 0.78), 2),
                "status": rng.choice(STATUS_MAP["products"]),
                "stock_qty": rng.randint(0, 800),
                "rating": round(rng.uniform(3.2, 5.0), 1),
                "created_at": rnd_date(rng),
            })
    elif name == "customers":
        for i in range(n):
            city = rng.choice(list(CITY_PROVINCE))
            rows.append({
                "customer_id": i + 1,
                "name": rng.choice(SURNAMES) + rng.choice(GIVEN),
                "email": f"customer{i + 1}@example.com",
                "phone": f"1{rng.choice('35789')}{rng.randint(10**8, 10**9 - 1)}",
                "city": city,
                "province": CITY_PROVINCE[city],
                "gender": rng.choice(["male", "female", "unknown"]),
                "segment": rng.choice(["新客", "普通", "普通", "高价值", "沉睡"]),
                "membership_id": rng.choice(pools[("memberships", "membership_id")]),
                "points": rng.randint(0, 20000),
                "signup_date": rnd_date(rng),
                "is_active": rng.choice([1, 1, 1, 0]),
            })
    elif name == "orders":
        for i in range(n):
            status = rng.choice(STATUS_MAP["orders"])
            total = round(rng.uniform(59, 4800), 2)
            discount = round(rng.uniform(0, min(300, total * 0.3)), 2)
            shipping = round(rng.choice([0, 0, 8, 12, 15]), 2)
            city = rng.choice(list(CITY_PROVINCE))
            rows.append({
                "order_id": i + 1,
                "order_no": f"SO{rng.randint(10**9, 10**10 - 1)}",
                "customer_id": rng.choice(pools[("customers", "customer_id")]),
                "order_date": rnd_date(rng),
                "status": status,
                "channel": rng.choice(["app", "app", "web", "miniapp", "offline"]),
                "total_amount": total,
                "discount_amount": discount,
                "shipping_fee": shipping,
                "pay_amount": round(total - discount + shipping, 2),
                "coupon_id": rng.choice([0, 0, 0] + list(range(1, 21))),
                "province": CITY_PROVINCE[city],
                "created_at": rnd_date(rng),
            })
    elif name == "order_items":
        prices = pools.get("__product_price__", {})
        for i in range(n):
            pid = rng.choice(pools[("products", "product_id")])
            unit = prices.get(pid, 199.0)
            qty = rng.randint(1, 5)
            disc = round(rng.uniform(0, unit * 0.15), 2)
            rows.append({
                "item_id": i + 1,
                "order_id": rng.choice(pools[("orders", "order_id")]),
                "product_id": pid,
                "quantity": qty,
                "unit_price": unit,
                "discount": disc,
                "line_total": round(unit * qty - disc, 2),
            })
    return rows


CORE_TABLES = {"products", "customers", "orders", "order_items"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="数据库已存在则跳过")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.keep and DB_PATH.exists():
        print(f"已存在，跳过：{DB_PATH}")
        return
    if DB_PATH.exists():
        DB_PATH.unlink()

    rng = random.Random(SEED)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    pools = {}
    meta_tables = []
    ordered = topo_order(TABLES)
    print(f"表数量：{len(ordered)}（按外键依赖排序）")

    for t in ordered:
        cur.execute(ddl_of(t))
        n = t["rows"]
        if t["name"] in CORE_TABLES:
            rows = make_core_rows(rng, t, n, pools)
        else:
            rows = []
            for i in range(n):
                row = {}
                for c in t["columns"]:
                    row[c["name"]] = gen_value(rng, t, c, i, pools, row)
                rows.append(row)

        col_names = [c["name"] for c in t["columns"]]
        placeholders = ",".join("?" for _ in col_names)
        cur.executemany(
            f'INSERT INTO {t["name"]} ({",".join(col_names)}) VALUES ({placeholders})',
            [tuple(r[c] for c in col_names) for r in rows],
        )

        # 缓存主键值供后续外键使用
        pools[(t["name"], t["pk"])] = [r[t["pk"]] for r in rows]
        if t["name"] == "products":
            pools["__product_price__"] = {r["product_id"]: r["price"] for r in rows}

        # 外键列建索引，提升 join 性能
        for fk in t["fks"]:
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{t["name"]}_{fk} ON {t["name"]}({fk})')

        # 枚举值：distinct 较少的文本列，交给 LLM 做值对齐
        enums = {}
        for c in t["columns"]:
            if c["type"] != "TEXT":
                continue
            cur.execute(f'SELECT DISTINCT {c["name"]} FROM {t["name"]} LIMIT 15')
            vals = [r[0] for r in cur.fetchall() if r[0] is not None]
            if 0 < len(vals) < 15 and all(isinstance(v, str) and len(v) < 40 for v in vals):
                enums[c["name"]] = vals

        meta_tables.append({
            "name": t["name"],
            "cn": t["cn"],
            "domain": t["domain"],
            "rows": n,
            "pk": t["pk"],
            "fks": t["fks"],
            "keywords": t["kw"],
            "ddl": ddl_of(t),
            "text": table_text(t),
            "columns": t["columns"],
            "enums": enums,
            "samples": rows[:2],
        })
        print(f"  {t['name']:<26} {n:>6} 行  {t['cn']}")

    conn.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # 元数据按定义顺序输出，便于前端展示
    order_index = {t["name"]: i for i, t in enumerate(TABLES)}
    meta_tables.sort(key=lambda m: order_index[m["name"]])
    meta = {
        "generated_at": date.today().isoformat(),
        "seed": SEED,
        "db_path": str(DB_PATH),
        "total_tables": len(meta_tables),
        "tables": meta_tables,
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    real_tables = cur.fetchone()[0]
    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()[0]
    conn.close()

    print(f"\n完成：{DB_PATH}（{DB_PATH.stat().st_size / 1024 / 1024:.2f} MB）")
    print(f"元数据：{META_PATH}")
    print(f"校验：表 {real_tables} 张（含索引不计）/ integrity_check = {integrity}")


if __name__ == "__main__":
    main()
