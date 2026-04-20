"""
因子库定义

内置常用的选股因子，支持扩展自定义因子。

因子分类:
- 动量因子: 基于价格趋势
- 价值因子: 基于估值指标
- 质量因子: 基于盈利能力
- 成长因子: 基于增长率
- 波动因子: 基于风险指标
- 流动性因子: 基于交易活跃度
- 技术因子: 基于技术指标
"""

from enum import Enum
from typing import Callable, Dict, Optional, List
from dataclasses import dataclass
import pandas as pd
import numpy as np


class FactorCategory(str, Enum):
    """因子分类"""
    MOMENTUM = "momentum"      # 动量因子
    VALUE = "value"           # 价值因子
    QUALITY = "quality"       # 质量因子
    GROWTH = "growth"         # 成长因子
    VOLATILITY = "volatility" # 波动因子
    LIQUIDITY = "liquidity"   # 流动性因子
    TECHNICAL = "technical"   # 技术因子


@dataclass
class FactorDefinition:
    """因子定义"""
    name: str                          # 因子名称 (唯一标识)
    display_name: str                  # 显示名称
    category: FactorCategory           # 因子分类
    description: str                   # 描述
    direction: str                     # "asc" 越大越好, "desc" 越小越好
    data_source: str                   # 数据来源: "daily" | "daily_basic" | "fina"
    required_fields: List[str]         # 需要的数据字段
    compute_func: Callable             # 计算函数
    lookback_days: int = 60            # 需要的历史数据天数


class FactorLibrary:
    """
    因子库
    
    管理所有内置因子和自定义因子
    """
    
    _factors: Dict[str, FactorDefinition] = {}
    
    @classmethod
    def register(cls, factor_def: FactorDefinition):
        """注册因子"""
        cls._factors[factor_def.name] = factor_def
    
    @classmethod
    def get(cls, name: str) -> Optional[FactorDefinition]:
        """获取因子定义"""
        return cls._factors.get(name)
    
    @classmethod
    def list_factors(cls) -> List[Dict]:
        """列出所有因子"""
        return [
            {
                "name": f.name,
                "display_name": f.display_name,
                "category": f.category.value,
                "description": f.description,
                "direction": f.direction,
                "data_source": f.data_source,
            }
            for f in cls._factors.values()
        ]
    
    @classmethod
    def get_factors_by_category(cls, category: FactorCategory) -> List[FactorDefinition]:
        """按分类获取因子"""
        return [f for f in cls._factors.values() if f.category == category]


# ============== 超短策略专用预计算因子 ==============
# 这些因子已经提前批量计算存储在MongoDB中，直接读取即可
FactorLibrary.register(
    FactorDefinition(
        name="limit_up_yesterday",
        display_name="昨日涨停标记",
        category=FactorCategory.TECHNICAL,
        description="昨日是否涨停 (1=是, 0=否)",
        direction="asc",
        data_source="daily",
        required_fields=["limit_up_yesterday"],
        compute_func=lambda df: df["limit_up_yesterday"],
        lookback_days=1,
    )
)

FactorLibrary.register(
    FactorDefinition(
        name="first_limit_up",
        display_name="首次涨停标记",
        category=FactorCategory.TECHNICAL,
        description="当日是否首次涨停 (1=是, 0=否)",
        direction="asc",
        data_source="daily",
        required_fields=["first_limit_up"],
        compute_func=lambda df: df["first_limit_up"],
        lookback_days=1,
    )
)

FactorLibrary.register(
    FactorDefinition(
        name="limit_up_count",
        display_name="连续涨停天数",
        category=FactorCategory.TECHNICAL,
        description="连续涨停天数",
        direction="asc",
        data_source="daily",
        required_fields=["limit_up_count"],
        compute_func=lambda df: df["limit_up_count"],
        lookback_days=1,
    )
)

FactorLibrary.register(
    FactorDefinition(
        name="market_leader",
        display_name="龙头股标记",
        category=FactorCategory.TECHNICAL,
        description="是否为市场龙头股 (1=是, 0=否)",
        direction="asc",
        data_source="daily",
        required_fields=["market_leader"],
        compute_func=lambda df: df["market_leader"],
        lookback_days=1,
    )
)

FactorLibrary.register(
    FactorDefinition(
        name="amplitude",
        display_name="振幅",
        category=FactorCategory.TECHNICAL,
        description="当日振幅 ((最高-最低)/昨收*100%)",
        direction="asc",
        data_source="daily",
        required_fields=["amplitude"],
        compute_func=lambda df: df["amplitude"],
        lookback_days=1,
    )
)

FactorLibrary.register(
    FactorDefinition(
        name="volume_ratio",
        display_name="量比",
        category=FactorCategory.LIQUIDITY,
        description="量比 (当日成交量/过去5日平均成交量)",
        direction="asc",
        data_source="daily",
        required_fields=["volume_ratio"],
        compute_func=lambda df: df["volume_ratio"],
        lookback_days=1,
    )
)

# ============== 辅助函数 ==============

def _safe_divide(a: pd.Series, b: pd.Series) -> pd.Series:
    """安全除法，避免除零"""
    return a / b.replace(0, np.nan)


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = _safe_divide(gain, loss)
    return 100 - (100 / (1 + rs))


# ============== 注册内置因子 ==============

# -------------------- 动量因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="momentum_5d",
    display_name="5日动量",
    category=FactorCategory.MOMENTUM,
    description="过去5个交易日的收益率",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=10,
    compute_func=lambda df: df["close"].pct_change(5),
))

FactorLibrary.register(FactorDefinition(
    name="momentum_20d",
    display_name="20日动量",
    category=FactorCategory.MOMENTUM,
    description="过去20个交易日的收益率",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=30,
    compute_func=lambda df: df["close"].pct_change(20),
))

FactorLibrary.register(FactorDefinition(
    name="momentum_60d",
    display_name="60日动量",
    category=FactorCategory.MOMENTUM,
    description="过去60个交易日的收益率",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=70,
    compute_func=lambda df: df["close"].pct_change(60),
))

# -------------------- 价值因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="pe_ttm",
    display_name="市盈率TTM",
    category=FactorCategory.VALUE,
    description="滚动市盈率，越低越便宜",
    direction="desc",  # 越小越好
    data_source="daily_basic",
    required_fields=["pe_ttm"],
    lookback_days=1,
    compute_func=lambda df: df["pe_ttm"],
))

FactorLibrary.register(FactorDefinition(
    name="pb",
    display_name="市净率",
    category=FactorCategory.VALUE,
    description="市净率，越低越便宜",
    direction="desc",
    data_source="daily_basic",
    required_fields=["pb"],
    lookback_days=1,
    compute_func=lambda df: df["pb"],
))

FactorLibrary.register(FactorDefinition(
    name="ps_ttm",
    display_name="市销率TTM",
    category=FactorCategory.VALUE,
    description="滚动市销率，越低越便宜",
    direction="desc",
    data_source="daily_basic",
    required_fields=["ps_ttm"],
    lookback_days=1,
    compute_func=lambda df: df["ps_ttm"],
))

FactorLibrary.register(FactorDefinition(
    name="dv_ttm",
    display_name="股息率TTM",
    category=FactorCategory.VALUE,
    description="滚动股息率，越高越好",
    direction="asc",
    data_source="daily_basic",
    required_fields=["dv_ttm"],
    lookback_days=1,
    compute_func=lambda df: df["dv_ttm"],
))

# -------------------- 质量因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="roe",
    display_name="ROE",
    category=FactorCategory.QUALITY,
    description="净资产收益率，越高越好",
    direction="asc",
    data_source="fina",
    required_fields=["roe"],
    lookback_days=1,
    compute_func=lambda df: df["roe"],
))

FactorLibrary.register(FactorDefinition(
    name="roa",
    display_name="ROA",
    category=FactorCategory.QUALITY,
    description="总资产收益率，越高越好",
    direction="asc",
    data_source="fina",
    required_fields=["roa"],
    lookback_days=1,
    compute_func=lambda df: df["roa"],
))

FactorLibrary.register(FactorDefinition(
    name="gross_margin",
    display_name="毛利率",
    category=FactorCategory.QUALITY,
    description="毛利率，越高越好",
    direction="asc",
    data_source="fina",
    required_fields=["grossprofit_margin"],
    lookback_days=1,
    compute_func=lambda df: df["grossprofit_margin"],
))

# -------------------- 成长因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="revenue_growth",
    display_name="营收增长率",
    category=FactorCategory.GROWTH,
    description="营业收入同比增长率",
    direction="asc",
    data_source="fina",
    required_fields=["revenue_yoy"],
    lookback_days=1,
    compute_func=lambda df: df["revenue_yoy"],
))

FactorLibrary.register(FactorDefinition(
    name="profit_growth",
    display_name="利润增长率",
    category=FactorCategory.GROWTH,
    description="净利润同比增长率",
    direction="asc",
    data_source="fina",
    required_fields=["netprofit_yoy"],
    lookback_days=1,
    compute_func=lambda df: df["netprofit_yoy"],
))

# -------------------- 波动因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="volatility_20d",
    display_name="20日波动率",
    category=FactorCategory.VOLATILITY,
    description="过去20日收益率标准差，低波动优先",
    direction="desc",  # 低波动优先
    data_source="daily",
    required_fields=["close"],
    lookback_days=30,
    compute_func=lambda df: df["close"].pct_change().rolling(20).std(),
))

FactorLibrary.register(FactorDefinition(
    name="volatility_60d",
    display_name="60日波动率",
    category=FactorCategory.VOLATILITY,
    description="过去60日收益率标准差，低波动优先",
    direction="desc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=70,
    compute_func=lambda df: df["close"].pct_change().rolling(60).std(),
))

# -------------------- 流动性因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="turnover_20d",
    display_name="20日换手率",
    category=FactorCategory.LIQUIDITY,
    description="过去20日平均换手率",
    direction="asc",  # 高换手（流动性好）
    data_source="daily_basic",
    required_fields=["turnover_rate"],
    lookback_days=30,
    compute_func=lambda df: df["turnover_rate"].rolling(20).mean(),
))

FactorLibrary.register(FactorDefinition(
    name="amount_20d",
    display_name="20日成交额",
    category=FactorCategory.LIQUIDITY,
    description="过去20日平均成交额（亿元）",
    direction="asc",
    data_source="daily",
    required_fields=["amount"],
    lookback_days=30,
    compute_func=lambda df: df["amount"].rolling(20).mean() / 100000,  # 千元 -> 亿元
))

FactorLibrary.register(FactorDefinition(
    name="total_mv",
    display_name="总市值",
    category=FactorCategory.LIQUIDITY,
    description="总市值（亿元），可用于大/小盘选择",
    direction="asc",  # 根据策略调整
    data_source="daily_basic",
    required_fields=["total_mv"],
    lookback_days=1,
    compute_func=lambda df: df["total_mv"],  # 已经是亿元
))

# -------------------- 技术因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="ma_deviation_20",
    display_name="20日均线偏离",
    category=FactorCategory.TECHNICAL,
    description="股价与20日均线的偏离程度",
    direction="desc",  # 超跌反弹
    data_source="daily",
    required_fields=["close"],
    lookback_days=30,
    compute_func=lambda df: (df["close"] / df["close"].rolling(20).mean() - 1),
))

FactorLibrary.register(FactorDefinition(
    name="rsi_14",
    display_name="RSI(14)",
    category=FactorCategory.TECHNICAL,
    description="14日相对强弱指标",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=20,
    compute_func=lambda df: _compute_rsi(df["close"], 14),
))

FactorLibrary.register(FactorDefinition(
    name="price_position",
    display_name="价格位置",
    category=FactorCategory.TECHNICAL,
    description="当前价格在60日高低点中的位置 (0~1)",
    direction="desc",  # 低位买入
    data_source="daily",
    required_fields=["close", "high", "low"],
    lookback_days=70,
    compute_func=lambda df: (
        (df["close"] - df["low"].rolling(60).min()) / 
        (df["high"].rolling(60).max() - df["low"].rolling(60).min() + 1e-10)
    ),
))


# -------------------- 游资策略专用因子 --------------------

FactorLibrary.register(FactorDefinition(
    name="limit_up_yesterday",
    display_name="昨日涨停",
    category=FactorCategory.TECHNICAL,
    description="昨日是否涨停，1=涨停，0=未涨停",
    direction="asc",
    data_source="daily",
    required_fields=["close", "up_limit"],
    lookback_days=2,
    compute_func=lambda df: (df["close"] >= df["up_limit"] * 0.998).shift(1).fillna(0),
))

FactorLibrary.register(FactorDefinition(
    name="open_below_limit",
    display_name="开盘低于涨停价",
    category=FactorCategory.TECHNICAL,
    description="(涨停价 - 开盘价) / 涨停价，越大越符合高开低走/半路追涨",
    direction="asc",
    data_source="daily",
    required_fields=["open", "up_limit"],
    lookback_days=1,
    compute_func=lambda df: (df["up_limit"] - df["open"]) / df["up_limit"].replace(0, np.nan),
))

FactorLibrary.register(FactorDefinition(
    name="limit_down_yesterday",
    display_name="昨日跌停",
    category=FactorCategory.TECHNICAL,
    description="昨日是否跌停，1=跌停，0=未跌停",
    direction="asc",
    data_source="daily",
    required_fields=["close", "down_limit"],
    lookback_days=2,
    compute_func=lambda df: (df["close"] <= df["down_limit"] * 1.002).shift(1).fillna(0),
))

FactorLibrary.register(FactorDefinition(
    name="open_above_limit",
    display_name="开盘高于跌停价",
    category=FactorCategory.TECHNICAL,
    description="(开盘价 - 跌停价) / 跌停价，越大越符合跌停翘板",
    direction="asc",
    data_source="daily",
    required_fields=["open", "down_limit"],
    lookback_days=1,
    compute_func=lambda df: (df["open"] - df["down_limit"]) / df["down_limit"].replace(0, np.nan),
))

FactorLibrary.register(FactorDefinition(
    name="price_near_ma5",
    display_name="价格靠近MA5",
    category=FactorCategory.TECHNICAL,
    description="价格与MA5的偏离程度，越小越靠近，适合低吸",
    direction="desc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=10,
    compute_func=lambda df: abs(df["close"] / df["close"].rolling(5).mean() - 1),
))

FactorLibrary.register(FactorDefinition(
    name="ma5",
    display_name="5日均线",
    category=FactorCategory.TECHNICAL,
    description="5日均线值",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=10,
    compute_func=lambda df: df["close"].rolling(5).mean(),
))

FactorLibrary.register(FactorDefinition(
    name="pullback_ma5",
    display_name="回踩MA5",
    category=FactorCategory.TECHNICAL,
    description="回踩MA5打分，价格回调到MA5附近得分高",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=10,
    compute_func=lambda df: 1 - abs(df["close"] / df["close"].rolling(5).mean() - 1),
))

FactorLibrary.register(FactorDefinition(
    name="leading_stock",
    display_name="领涨龙头",
    category=FactorCategory.TECHNICAL,
    description="近期涨幅排序，涨幅越大分数越高",
    direction="asc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=25,
    compute_func=lambda df: df["close"].pct_change(20),
))

FactorLibrary.register(FactorDefinition(
    name="market_leader",
    display_name="市场龙头",
    category=FactorCategory.TECHNICAL,
    description="市场总龙头判断，基于近期涨幅和成交量",
    direction="asc",
    data_source="daily",
    required_fields=["close", "amount"],
    lookback_days=30,
    compute_func=lambda df: (
        df["close"].pct_change(20) * 
        df["amount"].rolling(5).mean() / df["amount"].rolling(20).mean()
    ),
))

FactorLibrary.register(FactorDefinition(
    name="first_limit_up",
    display_name="首次涨停",
    category=FactorCategory.TECHNICAL,
    description="是否为近期首次涨停，1=首次，0=非首次",
    direction="asc",
    data_source="daily",
    required_fields=["close", "up_limit"],
    lookback_days=20,
    compute_func=lambda df: (
        (df["close"] >= df["up_limit"] * 0.998) & 
        (df["close"].rolling(20).apply(lambda x: sum(x >= x.iloc[-1] * 0.998) == 1))
    ).astype(float),
))

FactorLibrary.register(FactorDefinition(
    name="volume_increase",
    display_name="放量",
    category=FactorCategory.TECHNICAL,
    description="成交量相对于5日均量的放大比例，越大放量越明显",
    direction="asc",
    data_source="daily",
    required_fields=["vol"],
    lookback_days=10,
    compute_func=lambda df: df["vol"] / df["vol"].rolling(5).mean(),
))

FactorLibrary.register(FactorDefinition(
    name="lhb_buy_in",
    display_name="龙虎榜净买入",
    category=FactorCategory.TECHNICAL,
    description="龙虎榜净买入金额（单位：千万）",
    direction="asc",
    data_source="daily",
    required_fields=["lhb_net_buy"],
    lookback_days=5,
    compute_func=lambda df: df["lhb_net_buy"].fillna(0),
))

FactorLibrary.register(FactorDefinition(
    name="one_month_reversal",
    display_name="一月反转",
    category=FactorCategory.MOMENTUM,
    description="一个月收益反转，上月跌的越多本月得分越高",
    direction="desc",
    data_source="daily",
    required_fields=["close"],
    lookback_days=25,
    compute_func=lambda df: df["close"].pct_change(20),
))

# -------------------- 超短策略专属因子 --------------------
FactorLibrary.register(FactorDefinition(
    name="open_below_limit",
    display_name="开盘低于昨日涨停价",
    category=FactorCategory.TECHNICAL,
    description="当日开盘价 < 昨日涨停价（昨日收盘价*1.1），用于半路追涨策略",
    direction="asc",
    data_source="daily",
    required_fields=["open_below_limit"],
    lookback_days=1,
    compute_func=lambda df: df["open_below_limit"],
))

FactorLibrary.register(FactorDefinition(
    name="open_above_limit",
    display_name="开盘高于昨日跌停价",
    category=FactorCategory.TECHNICAL,
    description="当日开盘价 > 昨日跌停价（昨日收盘价*0.9），用于跌停翘板策略",
    direction="asc",
    data_source="daily",
    required_fields=["open_above_limit"],
    lookback_days=1,
    compute_func=lambda df: df["open_above_limit"],
))

FactorLibrary.register(FactorDefinition(
    name="limit_up_open_amount",
    display_name="涨停开板金额",
    category=FactorCategory.TECHNICAL,
    description="当日涨停开板成交总金额，用于涨停开板策略",
    direction="desc",
    data_source="daily",
    required_fields=["limit_up_open_amount"],
    lookback_days=1,
    compute_func=lambda df: df["limit_up_open_amount"],
))

FactorLibrary.register(FactorDefinition(
    name="limit_down_yesterday",
    display_name="昨日跌停标记",
    category=FactorCategory.TECHNICAL,
    description="前一交易日是否跌停（涨跌幅<=-9.8%）",
    direction="asc",
    data_source="daily",
    required_fields=["limit_down_yesterday"],
    lookback_days=1,
    compute_func=lambda df: df["limit_down_yesterday"],
))

FactorLibrary.register(FactorDefinition(
    name="volume_increase",
    display_name="放量标记",
    category=FactorCategory.TECHNICAL,
    description="当日成交量 > 过去5日平均成交量*1.5",
    direction="asc",
    data_source="daily",
    required_fields=["volume_increase"],
    lookback_days=1,
    compute_func=lambda df: df["volume_increase"],
))

FactorLibrary.register(FactorDefinition(
    name="limit_up_amount",
    display_name="涨停封单金额",
    category=FactorCategory.TECHNICAL,
    description="涨停时封单金额（单位：万元），越大越强",
    direction="asc",
    data_source="daily",
    required_fields=["limit_up_amount"],
    lookback_days=1,
    compute_func=lambda df: df["limit_up_amount"],
))

FactorLibrary.register(FactorDefinition(
    name="limit_down_count",
    display_name="连续跌停次数",
    category=FactorCategory.TECHNICAL,
    description="连续跌停天数",
    direction="desc",
    data_source="daily",
    required_fields=["limit_down_count"],
    lookback_days=1,
    compute_func=lambda df: df["limit_down_count"],
))

FactorLibrary.register(FactorDefinition(
    name="circ_mv",
    display_name="流通市值",
    category=FactorCategory.VALUE,
    description="流通市值估算（单位：万元）",
    direction="desc",
    data_source="daily",
    required_fields=["circ_mv"],
    lookback_days=1,
    compute_func=lambda df: df["circ_mv"],
))

FactorLibrary.register(FactorDefinition(
    name="turnover_rate",
    display_name="换手率",
    category=FactorCategory.LIQUIDITY,
    description="换手率百分比（%）",
    direction="asc",
    data_source="daily",
    required_fields=["turnover_rate"],
    lookback_days=1,
    compute_func=lambda df: df["turnover_rate"],
))

FactorLibrary.register(FactorDefinition(
    name="pullback_ma5",
    display_name="回踩MA5",
    category=FactorCategory.TECHNICAL,
    description="价格回调到MA5附近得分越高",
    direction="asc",
    data_source="daily",
    required_fields=["pullback_ma5"],
    lookback_days=1,
    compute_func=lambda df: df["pullback_ma5"],
))

FactorLibrary.register(FactorDefinition(
    name="sentiment_score",
    display_name="情绪评分",
    category=FactorCategory.MOMENTUM,
    description="基于涨跌停计算的市场情绪评分",
    direction="asc",
    data_source="daily",
    required_fields=["sentiment_score"],
    lookback_days=1,
    compute_func=lambda df: df["sentiment_score"],
))
