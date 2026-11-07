# -*- coding: utf-8 -*-
"""
电商演示库表结构定义（50 张表）

业务模型参考开源电商系统 Saleor / Magento 的领域划分，做适度精简。
每张表的中文名、业务域、列中文说明、检索关键词会一起用于向量化，
是 schema linking（选表）的主要语义来源。
"""

TOTAL_TABLES = 50


def T(name, cn, domain, rows, cols, kw="", pk=None, fks=None):
    """
    name  表名 / cn 中文名 / domain 业务域 / rows 模拟数据行数
    cols  [(列名, SQLite类型, 中文说明), ...]
    kw    额外检索关键词（中文，空格分隔）
    pk    主键列名
    fks   {外键列: (引用表, 引用列)}
    """
    return {
        "name": name,
        "cn": cn,
        "domain": domain,
        "rows": rows,
        "kw": kw,
        "pk": pk or (cols[0][0] if cols else "id"),
        "fks": fks or {},
        "columns": [{"name": c[0], "type": c[1], "cn": c[2]} for c in cols],
    }


TABLES = [
    # ==================== 一、商品与目录（10） ====================
    T("categories", "商品类目", "商品目录", 24, [
        ("category_id", "INTEGER", "类目ID"),
        ("parent_id", "INTEGER", "父类目ID，0表示一级类目"),
        ("name", "TEXT", "类目名称，如 手机数码、女装、家居"),
        ("level", "INTEGER", "类目层级 1或2"),
        ("sort_order", "INTEGER", "展示排序"),
        ("is_active", "INTEGER", "是否启用 1是 0否"),
    ], kw="分类 品类 目录 商品分类 一级类目 二级类目"),

    T("brands", "品牌", "商品目录", 30, [
        ("brand_id", "INTEGER", "品牌ID"),
        ("name", "TEXT", "品牌名称"),
        ("country", "TEXT", "品牌所属国家"),
        ("founded_year", "INTEGER", "创立年份"),
        ("is_active", "INTEGER", "是否启用"),
    ], kw="品牌 厂家 商标 牌子"),

    T("products", "商品主表", "商品目录", 320, [
        ("product_id", "INTEGER", "商品ID，主键"),
        ("category_id", "INTEGER", "所属类目ID"),
        ("brand_id", "INTEGER", "品牌ID"),
        ("name", "TEXT", "商品名称"),
        ("sku_code", "TEXT", "商品编码SPU"),
        ("price", "REAL", "销售单价（元）"),
        ("cost", "REAL", "成本价（元）"),
        ("status", "TEXT", "商品状态 on_sale上架 / off_sale下架 / draft草稿"),
        ("stock_qty", "INTEGER", "可售库存数量"),
        ("rating", "REAL", "平均评分 1-5"),
        ("created_at", "TEXT", "上架日期 YYYY-MM-DD"),
    ], kw="商品 货品 SPU 价格 售价 成本 库存 上架 下架 毛利",
        fks={"category_id": ("categories", "category_id"), "brand_id": ("brands", "brand_id")}),

    T("product_skus", "商品SKU", "商品目录", 640, [
        ("sku_id", "INTEGER", "SKU主键"),
        ("product_id", "INTEGER", "商品ID"),
        ("sku_code", "TEXT", "SKU编码"),
        ("spec", "TEXT", "规格描述，如 黑色/128G"),
        ("price", "REAL", "SKU售价（元）"),
        ("stock_qty", "INTEGER", "SKU库存"),
        ("barcode", "TEXT", "条形码"),
    ], kw="SKU 规格 型号 颜色 尺码 条码 变体",
        fks={"product_id": ("products", "product_id")}),

    T("product_images", "商品图片", "商品目录", 700, [
        ("image_id", "INTEGER", "图片ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("url", "TEXT", "图片地址"),
        ("is_main", "INTEGER", "是否主图 1是 0否"),
        ("sort_order", "INTEGER", "图片排序"),
    ], kw="图片 主图 相册 轮播图", fks={"product_id": ("products", "product_id")}),

    T("product_attributes", "商品属性值", "商品目录", 900, [
        ("attr_value_id", "INTEGER", "属性值ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("attr_id", "INTEGER", "属性定义ID"),
        ("value", "TEXT", "属性值，如 棉、220V、5.5英寸"),
    ], kw="属性 参数 规格参数 属性值",
        fks={"product_id": ("products", "product_id"), "attr_id": ("attribute_defs", "attr_id")}),

    T("attribute_defs", "属性定义", "商品目录", 18, [
        ("attr_id", "INTEGER", "属性ID"),
        ("name", "TEXT", "属性名，如 材质、颜色、尺寸"),
        ("unit", "TEXT", "单位"),
        ("input_type", "TEXT", "录入方式 select / text"),
    ], kw="属性名 属性定义 参数字典"),

    T("product_tags", "商品标签关联", "商品目录", 800, [
        ("id", "INTEGER", "关联ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("tag_id", "INTEGER", "标签ID"),
    ], kw="标签关联 打标",
        pk="id", fks={"product_id": ("products", "product_id"), "tag_id": ("tags", "tag_id")}),

    T("tags", "标签字典", "商品目录", 20, [
        ("tag_id", "INTEGER", "标签ID"),
        ("name", "TEXT", "标签名，如 新品、爆款、包邮"),
        ("color", "TEXT", "标签颜色"),
    ], kw="标签 标记 新品 爆款 热卖"),

    T("product_reviews", "商品评价", "商品目录", 1200, [
        ("review_id", "INTEGER", "评价ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("rating", "INTEGER", "评分 1-5 星"),
        ("content", "TEXT", "评价内容"),
        ("is_visible", "INTEGER", "是否展示 1是"),
        ("review_date", "TEXT", "评价日期 YYYY-MM-DD"),
    ], kw="评价 评论 评分 好评 差评 口碑 星级",
        fks={"product_id": ("products", "product_id"), "customer_id": ("customers", "customer_id")}),

    # ==================== 二、用户与会员（8） ====================
    T("customers", "客户主表", "用户会员", 500, [
        ("customer_id", "INTEGER", "客户ID，主键"),
        ("name", "TEXT", "客户姓名"),
        ("email", "TEXT", "邮箱"),
        ("phone", "TEXT", "手机号"),
        ("city", "TEXT", "所在城市"),
        ("province", "TEXT", "所在省份"),
        ("gender", "TEXT", "性别 male / female / unknown"),
        ("segment", "TEXT", "客户分群 新客/普通/高价值/沉睡"),
        ("membership_id", "INTEGER", "会员等级ID"),
        ("points", "INTEGER", "当前积分"),
        ("signup_date", "TEXT", "注册日期 YYYY-MM-DD"),
        ("is_active", "INTEGER", "是否活跃 1是"),
    ], kw="客户 用户 会员 买家 消费者 注册 城市 省份 积分 分群",
        fks={"membership_id": ("memberships", "membership_id")}),

    T("customer_addresses", "收货地址", "用户会员", 900, [
        ("address_id", "INTEGER", "地址ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("receiver", "TEXT", "收货人"),
        ("phone", "TEXT", "收货手机号"),
        ("province", "TEXT", "省"),
        ("city", "TEXT", "市"),
        ("detail", "TEXT", "详细地址"),
        ("is_default", "INTEGER", "是否默认地址"),
    ], kw="地址 收货地址 配送地址 省份 城市",
        fks={"customer_id": ("customers", "customer_id")}),

    T("customer_groups", "客户分群", "用户会员", 6, [
        ("group_id", "INTEGER", "分群ID"),
        ("name", "TEXT", "分群名称"),
        ("description", "TEXT", "分群规则说明"),
        ("min_order_amount", "REAL", "入群门槛累计消费金额（元）"),
    ], kw="分群 人群 客群 用户分层 RFM"),

    T("customer_group_members", "分群成员", "用户会员", 500, [
        ("id", "INTEGER", "记录ID"),
        ("group_id", "INTEGER", "分群ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("joined_at", "TEXT", "加入日期"),
    ], kw="分群成员 人群包", pk="id",
        fks={"group_id": ("customer_groups", "group_id"), "customer_id": ("customers", "customer_id")}),

    T("memberships", "会员等级", "用户会员", 5, [
        ("membership_id", "INTEGER", "等级ID"),
        ("name", "TEXT", "等级名称 普通/银卡/金卡/铂金/钻石"),
        ("discount", "REAL", "会员折扣 0-1"),
        ("min_points", "INTEGER", "升级所需积分"),
    ], kw="会员等级 VIP 折扣 等级"),

    T("points_ledger", "积分流水", "用户会员", 1500, [
        ("ledger_id", "INTEGER", "流水ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("change_qty", "INTEGER", "积分变动值，正数为获得"),
        ("reason", "TEXT", "变动原因 下单/签到/退款/兑换"),
        ("created_at", "TEXT", "发生时间 YYYY-MM-DD"),
    ], kw="积分 积分明细 积分变动 签到",
        fks={"customer_id": ("customers", "customer_id")}),

    T("wishlists", "收藏夹", "用户会员", 400, [
        ("wishlist_id", "INTEGER", "收藏夹ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("name", "TEXT", "收藏夹名称"),
        ("created_at", "TEXT", "创建日期"),
    ], kw="收藏夹 心愿单", fks={"customer_id": ("customers", "customer_id")}),

    T("wishlist_items", "收藏商品", "用户会员", 900, [
        ("id", "INTEGER", "记录ID"),
        ("wishlist_id", "INTEGER", "收藏夹ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("added_at", "TEXT", "加入日期"),
    ], kw="收藏商品 心愿商品 加收藏", pk="id",
        fks={"wishlist_id": ("wishlists", "wishlist_id"), "product_id": ("products", "product_id")}),

    # ==================== 三、交易与订单（10） ====================
    T("orders", "订单主表", "交易订单", 3000, [
        ("order_id", "INTEGER", "订单ID，主键"),
        ("order_no", "TEXT", "订单号"),
        ("customer_id", "INTEGER", "下单客户ID"),
        ("order_date", "TEXT", "下单日期 YYYY-MM-DD"),
        ("status", "TEXT", "订单状态 pending待付款/paid已付款/shipped已发货/completed已完成/cancelled已取消/refunded已退款"),
        ("channel", "TEXT", "下单渠道 app / web / miniapp / offline"),
        ("total_amount", "REAL", "订单总金额（元，含运费）"),
        ("discount_amount", "REAL", "优惠金额（元）"),
        ("shipping_fee", "REAL", "运费（元）"),
        ("pay_amount", "REAL", "实付金额（元）"),
        ("coupon_id", "INTEGER", "使用的优惠券ID，未使用为0"),
        ("province", "TEXT", "收货省份"),
        ("created_at", "TEXT", "创建时间"),
    ], kw="订单 销售 销售额 GMV 营收 成交额 下单 实付 客单价 交易 渠道 状态",
        fks={"customer_id": ("customers", "customer_id")}),

    T("order_items", "订单明细", "交易订单", 7200, [
        ("item_id", "INTEGER", "明细ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("quantity", "INTEGER", "购买数量"),
        ("unit_price", "REAL", "成交单价（元）"),
        ("discount", "REAL", "明细优惠金额（元）"),
        ("line_total", "REAL", "明细小计金额（元）"),
    ], kw="订单明细 商品销量 销量 购买数量 销售额 单品销售额 品类销售",
        fks={"order_id": ("orders", "order_id"), "product_id": ("products", "product_id")}),

    T("order_status_log", "订单状态日志", "交易订单", 6000, [
        ("log_id", "INTEGER", "日志ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("from_status", "TEXT", "变更前状态"),
        ("to_status", "TEXT", "变更后状态"),
        ("operator", "TEXT", "操作人 system / customer / admin"),
        ("created_at", "TEXT", "变更时间"),
    ], kw="状态变更 流转日志 订单轨迹", fks={"order_id": ("orders", "order_id")}),

    T("carts", "购物车", "交易订单", 450, [
        ("cart_id", "INTEGER", "购物车ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("updated_at", "TEXT", "最后更新时间"),
        ("status", "TEXT", "状态 active / converted / abandoned"),
    ], kw="购物车 加购 弃购", fks={"customer_id": ("customers", "customer_id")}),

    T("cart_items", "购物车明细", "交易订单", 1100, [
        ("id", "INTEGER", "记录ID"),
        ("cart_id", "INTEGER", "购物车ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("quantity", "INTEGER", "数量"),
        ("added_at", "TEXT", "加入时间"),
    ], kw="购物车商品 加购商品", pk="id",
        fks={"cart_id": ("carts", "cart_id"), "product_id": ("products", "product_id")}),

    T("payments", "支付记录", "交易订单", 2800, [
        ("payment_id", "INTEGER", "支付ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("method_id", "INTEGER", "支付方式ID"),
        ("amount", "REAL", "支付金额（元）"),
        ("status", "TEXT", "支付状态 success / failed / pending / refunded"),
        ("trade_no", "TEXT", "第三方交易流水号"),
        ("paid_at", "TEXT", "支付时间"),
    ], kw="支付 付款 收款 流水 交易金额 支付方式 成功率",
        fks={"order_id": ("orders", "order_id"), "method_id": ("payment_methods", "method_id")}),

    T("payment_methods", "支付方式", "交易订单", 6, [
        ("method_id", "INTEGER", "支付方式ID"),
        ("name", "TEXT", "支付方式名称 支付宝/微信支付/银行卡/余额/花呗/货到付款"),
        ("fee_rate", "REAL", "手续费率"),
        ("is_active", "INTEGER", "是否启用"),
    ], kw="支付方式 支付渠道 支付宝 微信支付"),

    T("refunds", "退款单", "交易订单", 320, [
        ("refund_id", "INTEGER", "退款ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("amount", "REAL", "退款金额（元）"),
        ("reason", "TEXT", "退款原因"),
        ("status", "TEXT", "退款状态 applied / approved / rejected / done"),
        ("created_at", "TEXT", "申请日期"),
    ], kw="退款 退款金额 退款率 售后退款", fks={"order_id": ("orders", "order_id")}),

    T("invoices", "发票", "交易订单", 900, [
        ("invoice_id", "INTEGER", "发票ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("title", "TEXT", "发票抬头"),
        ("tax_no", "TEXT", "税号"),
        ("amount", "REAL", "开票金额（元）"),
        ("type", "TEXT", "发票类型 personal / company"),
        ("issued_at", "TEXT", "开票日期"),
    ], kw="发票 开票 抬头 税号", fks={"order_id": ("orders", "order_id")}),

    T("shipments", "发货单", "交易订单", 2300, [
        ("shipment_id", "INTEGER", "发货单ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("warehouse_id", "INTEGER", "发货仓库ID"),
        ("carrier", "TEXT", "快递公司"),
        ("tracking_no", "TEXT", "运单号"),
        ("status", "TEXT", "物流状态 pending / in_transit / delivered / exception"),
        ("shipped_at", "TEXT", "发货日期"),
        ("delivered_at", "TEXT", "签收日期"),
    ], kw="发货 物流 快递 配送 签收 运单 仓库",
        fks={"order_id": ("orders", "order_id"), "warehouse_id": ("warehouses", "warehouse_id")}),

    # ==================== 四、仓储与采购（6） ====================
    T("warehouses", "仓库", "仓储采购", 8, [
        ("warehouse_id", "INTEGER", "仓库ID"),
        ("name", "TEXT", "仓库名称"),
        ("province", "TEXT", "所在省份"),
        ("city", "TEXT", "所在城市"),
        ("capacity", "INTEGER", "库容（件）"),
        ("is_active", "INTEGER", "是否启用"),
    ], kw="仓库 库房 仓 发货仓"),

    T("inventory", "库存", "仓储采购", 1200, [
        ("id", "INTEGER", "库存记录ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("warehouse_id", "INTEGER", "仓库ID"),
        ("quantity", "INTEGER", "在库数量"),
        ("locked_qty", "INTEGER", "锁定数量"),
        ("safety_qty", "INTEGER", "安全库存阈值"),
        ("updated_at", "TEXT", "更新时间"),
    ], kw="库存 在库 缺货 安全库存 库存预警 备货", pk="id",
        fks={"product_id": ("products", "product_id"), "warehouse_id": ("warehouses", "warehouse_id")}),

    T("stock_movements", "库存流水", "仓储采购", 2500, [
        ("movement_id", "INTEGER", "流水ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("warehouse_id", "INTEGER", "仓库ID"),
        ("change_qty", "INTEGER", "变动数量，正入库负出库"),
        ("type", "TEXT", "类型 inbound入库 / outbound出库 / adjust盘点"),
        ("created_at", "TEXT", "发生日期"),
    ], kw="出入库 库存变动 盘点 流水",
        fks={"product_id": ("products", "product_id"), "warehouse_id": ("warehouses", "warehouse_id")}),

    T("suppliers", "供应商", "仓储采购", 40, [
        ("supplier_id", "INTEGER", "供应商ID"),
        ("name", "TEXT", "供应商名称"),
        ("contact", "TEXT", "联系人"),
        ("phone", "TEXT", "联系电话"),
        ("city", "TEXT", "所在城市"),
        ("rating", "REAL", "供应商评分"),
    ], kw="供应商 供货商 厂商 采购来源"),

    T("purchase_orders", "采购单", "仓储采购", 260, [
        ("po_id", "INTEGER", "采购单ID"),
        ("supplier_id", "INTEGER", "供应商ID"),
        ("warehouse_id", "INTEGER", "收货仓库ID"),
        ("total_amount", "REAL", "采购总金额（元）"),
        ("status", "TEXT", "状态 draft / submitted / received / cancelled"),
        ("order_date", "TEXT", "采购日期"),
    ], kw="采购 进货 采购单 采购金额",
        fks={"supplier_id": ("suppliers", "supplier_id"), "warehouse_id": ("warehouses", "warehouse_id")}),

    T("purchase_order_items", "采购明细", "仓储采购", 700, [
        ("id", "INTEGER", "明细ID"),
        ("po_id", "INTEGER", "采购单ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("quantity", "INTEGER", "采购数量"),
        ("unit_cost", "REAL", "采购单价（元）"),
    ], kw="采购明细 进货明细 采购成本", pk="id",
        fks={"po_id": ("purchase_orders", "po_id"), "product_id": ("products", "product_id")}),

    # ==================== 五、营销与促销（7） ====================
    T("coupons", "优惠券模板", "营销促销", 20, [
        ("coupon_id", "INTEGER", "优惠券ID"),
        ("name", "TEXT", "优惠券名称"),
        ("type", "TEXT", "类型 fixed满减 / percent折扣 / shipping免邮"),
        ("value", "REAL", "优惠面额或折扣率"),
        ("min_amount", "REAL", "使用门槛金额（元）"),
        ("start_date", "TEXT", "生效日期"),
        ("end_date", "TEXT", "失效日期"),
        ("total_qty", "INTEGER", "发放总量"),
    ], kw="优惠券 满减 折扣 促销 券 门槛 活动"),

    T("coupon_codes", "优惠券码", "营销促销", 600, [
        ("code_id", "INTEGER", "券码ID"),
        ("coupon_id", "INTEGER", "优惠券模板ID"),
        ("customer_id", "INTEGER", "领取客户ID"),
        ("code", "TEXT", "券码字符串"),
        ("status", "TEXT", "状态 unused / used / expired"),
        ("received_at", "TEXT", "领取日期"),
    ], kw="券码 领券 发券 优惠券领取",
        fks={"coupon_id": ("coupons", "coupon_id"), "customer_id": ("customers", "customer_id")}),

    T("coupon_usages", "优惠券使用记录", "营销促销", 420, [
        ("usage_id", "INTEGER", "使用记录ID"),
        ("coupon_id", "INTEGER", "优惠券ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("discount_amount", "REAL", "实际抵扣金额（元）"),
        ("used_at", "TEXT", "使用日期"),
    ], kw="用券 核销 优惠抵扣 券使用率",
        fks={"coupon_id": ("coupons", "coupon_id"), "order_id": ("orders", "order_id"),
             "customer_id": ("customers", "customer_id")}),

    T("promotions", "促销活动", "营销促销", 18, [
        ("promo_id", "INTEGER", "活动ID"),
        ("name", "TEXT", "活动名称，如 双11、618、年货节"),
        ("type", "TEXT", "活动类型 discount / bundle / gift / flash"),
        ("discount_rate", "REAL", "活动折扣率"),
        ("start_date", "TEXT", "开始日期"),
        ("end_date", "TEXT", "结束日期"),
        ("budget", "REAL", "活动预算（元）"),
    ], kw="促销活动 大促 双11 618 营销活动 折扣"),

    T("flash_sales", "秒杀场次", "营销促销", 24, [
        ("flash_id", "INTEGER", "秒杀场次ID"),
        ("name", "TEXT", "场次名称"),
        ("start_at", "TEXT", "开始时间"),
        ("end_at", "TEXT", "结束时间"),
        ("status", "TEXT", "状态 upcoming / running / ended"),
    ], kw="秒杀 限时抢购 场次"),

    T("flash_sale_items", "秒杀商品", "营销促销", 180, [
        ("id", "INTEGER", "记录ID"),
        ("flash_id", "INTEGER", "秒杀场次ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("flash_price", "REAL", "秒杀价（元）"),
        ("limit_qty", "INTEGER", "限购数量"),
        ("sold_qty", "INTEGER", "已售数量"),
    ], kw="秒杀商品 秒杀价 限购 抢购", pk="id",
        fks={"flash_id": ("flash_sales", "flash_id"), "product_id": ("products", "product_id")}),

    T("gift_cards", "礼品卡", "营销促销", 200, [
        ("card_id", "INTEGER", "礼品卡ID"),
        ("code", "TEXT", "卡号"),
        ("balance", "REAL", "余额（元）"),
        ("customer_id", "INTEGER", "持有客户ID"),
        ("status", "TEXT", "状态 active / used / expired"),
        ("issued_at", "TEXT", "发放日期"),
    ], kw="礼品卡 储值卡 余额 购物卡",
        fks={"customer_id": ("customers", "customer_id")}),

    # ==================== 六、售后与客服（5） ====================
    T("return_requests", "退货申请", "售后客服", 260, [
        ("return_id", "INTEGER", "退货申请ID"),
        ("order_id", "INTEGER", "订单ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("reason", "TEXT", "退货原因 质量问题/尺寸不符/不喜欢/发错货"),
        ("status", "TEXT", "状态 applied / approved / rejected / received / refunded"),
        ("refund_amount", "REAL", "应退金额（元）"),
        ("created_at", "TEXT", "申请日期"),
    ], kw="退货 退款申请 售后 退货率 退货原因",
        fks={"order_id": ("orders", "order_id"), "customer_id": ("customers", "customer_id")}),

    T("return_items", "退货明细", "售后客服", 420, [
        ("id", "INTEGER", "明细ID"),
        ("return_id", "INTEGER", "退货申请ID"),
        ("product_id", "INTEGER", "商品ID"),
        ("quantity", "INTEGER", "退货数量"),
        ("condition", "TEXT", "商品成色 unopened / used / damaged"),
    ], kw="退货商品 退货明细", pk="id",
        fks={"return_id": ("return_requests", "return_id"), "product_id": ("products", "product_id")}),

    T("support_tickets", "客服工单", "售后客服", 380, [
        ("ticket_id", "INTEGER", "工单ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("order_id", "INTEGER", "关联订单ID"),
        ("category", "TEXT", "工单类型 物流/退款/商品/发票/其他"),
        ("priority", "TEXT", "优先级 low / normal / high / urgent"),
        ("status", "TEXT", "状态 open / pending / resolved / closed"),
        ("created_at", "TEXT", "创建日期"),
        ("resolved_at", "TEXT", "解决日期"),
    ], kw="工单 客服 投诉 咨询 处理时长",
        fks={"customer_id": ("customers", "customer_id"), "order_id": ("orders", "order_id")}),

    T("ticket_messages", "工单消息", "售后客服", 900, [
        ("message_id", "INTEGER", "消息ID"),
        ("ticket_id", "INTEGER", "工单ID"),
        ("sender", "TEXT", "发送方 customer / agent"),
        ("content", "TEXT", "消息内容"),
        ("created_at", "TEXT", "发送时间"),
    ], kw="客服消息 沟通记录 会话", fks={"ticket_id": ("support_tickets", "ticket_id")}),

    T("review_replies", "评价回复", "售后客服", 300, [
        ("reply_id", "INTEGER", "回复ID"),
        ("review_id", "INTEGER", "评价ID"),
        ("content", "TEXT", "商家回复内容"),
        ("created_at", "TEXT", "回复日期"),
    ], kw="评价回复 商家回评", fks={"review_id": ("product_reviews", "review_id")}),

    # ==================== 七、内容与运营（4） ====================
    T("banners", "首页轮播", "内容运营", 30, [
        ("banner_id", "INTEGER", "轮播ID"),
        ("title", "TEXT", "标题"),
        ("position", "TEXT", "投放位置 home / category / activity"),
        ("link_url", "TEXT", "跳转链接"),
        ("click_count", "INTEGER", "点击次数"),
        ("is_active", "INTEGER", "是否启用"),
        ("start_date", "TEXT", "投放开始日期"),
    ], kw="轮播图 广告位 banner 点击量 曝光"),

    T("search_logs", "搜索日志", "内容运营", 2500, [
        ("log_id", "INTEGER", "日志ID"),
        ("customer_id", "INTEGER", "搜索客户ID，0表示游客"),
        ("keyword", "TEXT", "搜索关键词"),
        ("result_count", "INTEGER", "返回结果数"),
        ("created_at", "TEXT", "搜索日期"),
    ], kw="搜索 关键词 热搜 搜索词 无结果"),

    T("user_events", "用户行为事件", "内容运营", 6000, [
        ("event_id", "INTEGER", "事件ID"),
        ("customer_id", "INTEGER", "客户ID"),
        ("event_type", "TEXT", "事件类型 view / add_cart / favorite / purchase / share"),
        ("product_id", "INTEGER", "相关商品ID"),
        ("device", "TEXT", "设备 ios / android / web"),
        ("created_at", "TEXT", "发生日期"),
    ], kw="埋点 行为 浏览 加购 转化 PV UV 访问",
        fks={"customer_id": ("customers", "customer_id"), "product_id": ("products", "product_id")}),

    T("notifications", "站内通知", "内容运营", 1500, [
        ("notification_id", "INTEGER", "通知ID"),
        ("customer_id", "INTEGER", "接收客户ID"),
        ("type", "TEXT", "通知类型 order / promo / system / points"),
        ("title", "TEXT", "通知标题"),
        ("is_read", "INTEGER", "是否已读 1是 0否"),
        ("created_at", "TEXT", "发送日期"),
    ], kw="通知 消息推送 站内信 已读",
        fks={"customer_id": ("customers", "customer_id")}),
]

assert len(TABLES) == TOTAL_TABLES, f"表数量应为 {TOTAL_TABLES}，实际 {len(TABLES)}"


def ddl_of(t):
    """由列定义生成 CREATE TABLE 语句，中文说明写成行内 SQL 注释。"""
    lines = []
    last = len(t["columns"]) - 1
    for idx, c in enumerate(t["columns"]):
        suffix = " PRIMARY KEY" if c["name"] == t["pk"] else ""
        comma = "," if idx < last else ""
        lines.append(f'    {c["name"]} {c["type"]}{suffix}{comma}  -- {c["cn"]}')
    body = "\n".join(lines)
    return f'CREATE TABLE {t["name"]} (\n{body}\n);'


def table_text(t):
    """拼成用于 embedding 的语义文本（表级）。"""
    cols = "；".join(f'{c["name"]}（{c["cn"]}）' for c in t["columns"])
    return f'数据表 {t["name"]}，中文名：{t["cn"]}，业务域：{t["domain"]}。字段：{cols}。相关业务：{t["kw"]}'
