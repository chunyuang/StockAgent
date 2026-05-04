"""
MongoDB 集合名常量

所有集合名统一在此定义，禁止在其他文件中硬编码集合名字符串。
修改集合名只需改这里一处。

用法:
    from core.constants import C
    await mongo_manager.find_many(C.STOCK_DAILY, query)
    mongo_manager.db[C.STOCK_DAILY].find(...)
"""

# ==================== 行情数据 ====================
STOCK_DAILY = "stock_daily_ak_full"          # A股日线行情(主表) + 因子字段
STOCK_1MIN = "stock_1min"                     # 1分钟线(超短策略)
INDEX_DAILY = "index_daily"                   # 指数日线
INDEX_BASIC = "index_basic"                   # 指数基础信息

# ==================== 基础信息 ====================
STOCK_BASIC = "stock_basic"                   # 股票基础信息(名称/行业/上市日期)
DAILY_BASIC = "daily_basic"                   # 每日指标(PE/PB/换手率/流通市值)
FINA_INDICATOR = "fina_indicator"             # 财务指标
FINA_INCOME = "fina_income"                   # 利润表
FINA_BALANCE = "fina_balance"                 # 资产负债表
FINA_CASHFLOW = "fina_cashflow"               # 现金流量表

# ==================== 市场数据 ====================
LIMIT_LIST = "limit_list"                     # 涨跌停列表
MONEYFLOW_INDUSTRY = "moneyflow_industry"     # 行业资金流
MONEYFLOW_CONCEPT = "moneyflow_concept"       # 概念资金流
DAILY_STATS = "daily_stats"                   # 每日统计汇总
HOT_NEWS = "hot_news"                         # 热点新闻

# ==================== 交易/信号 ====================
TRADING_SIGNALS = "trading_signals"            # 交易信号
DAILY_PREMARKET_SIGNALS = "daily_premarket_signals"  # 盘前信号
POSITIONS = "positions"                        # 持仓

# ==================== 缓存 ====================
STOCK_DAILY_CACHE = "stock_daily_ak_full_cache"  # 日线数据缓存


class _CollectionConstants:
    """集合常量访问器，支持 C.STOCK_DAILY 写法"""
    STOCK_DAILY = STOCK_DAILY
    STOCK_1MIN = STOCK_1MIN
    INDEX_DAILY = INDEX_DAILY
    INDEX_BASIC = INDEX_BASIC
    STOCK_BASIC = STOCK_BASIC
    DAILY_BASIC = DAILY_BASIC
    FINA_INDICATOR = FINA_INDICATOR
    FINA_INCOME = FINA_INCOME
    FINA_BALANCE = FINA_BALANCE
    FINA_CASHFLOW = FINA_CASHFLOW
    LIMIT_LIST = LIMIT_LIST
    MONEYFLOW_INDUSTRY = MONEYFLOW_INDUSTRY
    MONEYFLOW_CONCEPT = MONEYFLOW_CONCEPT
    DAILY_STATS = DAILY_STATS
    HOT_NEWS = HOT_NEWS
    TRADING_SIGNALS = TRADING_SIGNALS
    DAILY_PREMARKET_SIGNALS = DAILY_PREMARKET_SIGNALS
    POSITIONS = POSITIONS
    STOCK_DAILY_CACHE = STOCK_DAILY_CACHE

    # 反向映射: 集合名 → 常量名(用于日志/调试)
    _NAME_MAP = {
        STOCK_DAILY: "STOCK_DAILY",
        STOCK_1MIN: "STOCK_1MIN",
        INDEX_DAILY: "INDEX_DAILY",
        INDEX_BASIC: "INDEX_BASIC",
        STOCK_BASIC: "STOCK_BASIC",
        DAILY_BASIC: "DAILY_BASIC",
        FINA_INDICATOR: "FINA_INDICATOR",
        LIMIT_LIST: "LIMIT_LIST",
        MONEYFLOW_INDUSTRY: "MONEYFLOW_INDUSTRY",
        MONEYFLOW_CONCEPT: "MONEYFLOW_CONCEPT",
        DAILY_STATS: "DAILY_STATS",
        HOT_NEWS: "HOT_NEWS",
        TRADING_SIGNALS: "TRADING_SIGNALS",
        DAILY_PREMARKET_SIGNALS: "DAILY_PREMARKET_SIGNALS",
        POSITIONS: "POSITIONS",
    }


C = _CollectionConstants()
