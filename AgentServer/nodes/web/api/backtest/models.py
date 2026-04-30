"""
回测API数据模型

包含所有Pydantic模型和枚举定义。
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum

from pydantic import BaseModel, Field, root_validator


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestRequest(BaseModel):
    """回测请求"""
    ts_code: str = Field(..., description="股票代码", pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    start_date: str = Field(..., description="开始日期", pattern=r"^\d{8}$")
    end_date: str = Field(..., description="结束日期", pattern=r"^\d{8}$")

    # 资金配置
    initial_cash: float = Field(default=100000.0, ge=10000, le=100000000, description="初始资金")

    # 信号阈值
    entry_threshold: float = Field(default=0.7, ge=0.5, le=0.95, description="买入阈值")
    exit_threshold: float = Field(default=0.3, ge=0.05, le=0.5, description="卖出阈值")

    # 仓位管理
    position_size: float = Field(default=1.0, ge=0.1, le=1.0, description="仓位比例")

    # 因子权重 (可选)
    factor_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="因子权重配置，key 为因子名，value 为权重"
    )

    # 是否自动计算技术指标
    auto_technical: bool = Field(default=True, description="自动计算技术指标")

    class Config:
        json_schema_extra = {
            "example": {
                "ts_code": "000001.SZ",
                "start_date": "20240101",
                "end_date": "20241231",
                "initial_cash": 100000,
                "entry_threshold": 0.7,
                "exit_threshold": 0.3,
                "position_size": 1.0,
                "factor_weights": {
                    "tech_rsi": 0.3,
                    "tech_macd_signal": 0.3,
                    "tech_price_position": 0.4,
                },
                "auto_technical": True,
            }
        }


class FactorConfig(BaseModel):
    """因子配置"""
    name: str = Field(..., description="因子名称")
    weight: float = Field(default=1.0, ge=0, le=1.0, description="因子权重")
    direction: Optional[str] = Field(default=None, description="因子方向: asc(越大越好) / desc(越小越好)")


class FactorSelectionRequest(BaseModel):
    """因子选股回测请求"""
    universe: str = Field(default="all_a", description="股票池类型")
    start_date: str = Field(..., description="开始日期", pattern=r"^\d{8}$")
    end_date: str = Field(..., description="结束日期", pattern=r"^\d{8}$")

    initial_cash: float = Field(default=1000000.0, ge=100000, le=100000000, description="初始资金")
    rebalance_freq: str = Field(default="monthly", description="调仓频率: daily/weekly/monthly/quarterly")
    top_n: int = Field(default=20, ge=1, le=100, description="选股数量")
    weight_method: str = Field(default="equal", description="权重方法: equal/factor_weighted")

    factors: List[FactorConfig] = Field(..., description="因子配置列表", min_length=1)
    exclude: List[str] = Field(default=["st", "new_stock"], description="排除规则")
    benchmark: str = Field(default="000300.SH", description="基准指数")

    class Config:
        json_schema_extra = {
            "example": {
                "universe": "all_a",
                "start_date": "20230101",
                "end_date": "20260101",
                "initial_cash": 1000000,
                "rebalance_freq": "monthly",
                "top_n": 20,
                "weight_method": "equal",
                "factors": [
                    {"name": "momentum_20d", "weight": 0.3},
                    {"name": "pb", "weight": 0.3},
                    {"name": "roe", "weight": 0.4},
                ],
                "exclude": ["st", "new_stock"],
                "benchmark": "000300.SH",
            }
        }


class UltraShortParams(BaseModel):
    """超短策略参数配置"""
    volume_threshold: float = Field(default=1.5, ge=1.0, le=10.0, description="量能放大倍数")
    stop_loss_pct: float = Field(default=0.02, ge=0.01, le=0.2, description="止损比例(超短严格止损2%)")
    take_profit_pct: float = Field(default=0.07, ge=0.01, le=0.5, description="止盈比例(超短快进快出7%)")
    max_hold_days: int = Field(default=3, ge=1, le=10, description="最大持仓天数")
    max_position: float = Field(default=0.7, ge=0.1, le=1.0, description="总仓位上限")
    commission_rate: float = Field(default=0.0003, ge=0.0001, le=0.003, description="综合佣金率(万3)")
    stamp_duty_rate: float = Field(default=0.001, ge=0.0005, le=0.005, description="印花税率(千1)")
    slippage_pct: float = Field(default=0.002, ge=0.0, le=0.01, description="滑点比例(0.2%)")
    liquidity_threshold: float = Field(default=500.0, ge=100.0, le=5000.0, description="流动性门槛（万元）")
    max_position_per_stock: float = Field(default=0.2, ge=0.05, le=1.0, description="单票最大仓位比例(20%分散风险)")
    enable_stop_loss: bool = Field(default=True, description="是否启用止损")
    enable_take_profit: bool = Field(default=True, description="是否启用止盈")
    enable_ma60_filter: bool = Field(default=True, description="是否启用大盘MA60过滤")
    enable_sector_concentration: bool = Field(default=True, description="是否启用板块集中度过滤")
    force_empty_position: bool = Field(default=True, description="是否启用强制空仓规则")
    sentiment_cycle: bool = Field(default=True, description="是否启用情绪周期算法")
    auction_filter: bool = Field(default=True, description="是否启用竞价过滤规则")
    selected_strategies: List[Dict[str, Any]] = Field(default_factory=list, description="选中策略的完整配置（包含独立参数）")


# 中文策略名映射，放在类外面避免pydantic v2私有属性问题
strategy_name_map: Dict[str, str] = {
    "半路追涨": "halfway_chase",
    "首板打板": "first_limit_up",
    "涨停开板": "limit_up_open",
    "龙头低吸": "leader_buy_dip",
    "跌停翘板": "limit_down_qiao",
}

# 英文→中文的反向映射
strategy_name_map_reverse: Dict[str, str] = {v: k for k, v in strategy_name_map.items()}


class UltraShortBacktestRequest(BaseModel):
    """超短策略回测请求"""
    strategies: Optional[List[str]] = Field(None, description="策略列表，可选值: halfway_chase(半路追涨), first_limit_up(首板打板), limit_up_open(涨停开板), leader_buy_dip(龙头低吸), limit_down_qiao(跌停翘板)", min_length=1)
    selected_strategies: Optional[List[Dict[str, Any]]] = Field(None, description="前端提交的选中策略对象数组，兼容老版本")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")

    # 数据源配置
    data_source: str = Field(default="mongodb", description="数据源：固定为mongodb")
    period: str = Field(default="daily", description="周期：daily/1min")
    ts_codes: Optional[str] = Field(default=None, description="股票代码列表，逗号分隔，空为全市场")
    adjust_type: str = Field(default="qfq", description="复权方式：none(不复权), qfq(前复权)")

    initial_cash: Optional[float] = Field(default=1000000.0, ge=10000, le=100000000, description="初始资金")
    initial_capital: Optional[float] = Field(default=1000000.0, ge=10000, le=100000000, description="初始资金，兼容前端字段名")
    params: UltraShortParams = Field(default_factory=UltraShortParams, description="全局策略参数配置")
    strategy_params: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="各策略独立参数配置，key为策略id，value为参数字典")

    enable_sentiment_cycle: bool = Field(default=True, description="启用情绪周期适配")
    enable_auction_filter: bool = Field(default=True, description="启用集合竞价过滤")
    enable_force_empty: bool = Field(default=True, description="启用强制空仓规则")

    @root_validator(skip_on_failure=True)
    def compatibility_convert(cls, values):
        # 兼容前端selected_strategies结构，转换为strategies和strategy_params
        selected_strategies = values.get('selected_strategies')
        strategies = values.get('strategies')
        if selected_strategies and not strategies:
            strategies = []
            strategy_params = values.get('strategy_params', {})
            for s in selected_strategies:
                s_name = s.get('name', '')
                s_params = s.get('params', {})
                if s_name in strategy_name_map:
                    s_id = strategy_name_map[s_name]
                    strategies.append(s_id)
                    strategy_params[s_id] = s_params
            values['strategies'] = strategies
            values['strategy_params'] = strategy_params

        # 兼容start_date/end_date在params里的情况
        params = values.get('params')
        if not values.get('start_date') and hasattr(params, 'start_date') and params.start_date:
            # 确保始终是字符串，避免datetime对象导致JSON序列化失败
            if isinstance(params.start_date, datetime):
                values['start_date'] = params.start_date.strftime('%Y%m%d')
            else:
                values['start_date'] = str(params.start_date)
        if not values.get('end_date') and hasattr(params, 'end_date') and params.end_date:
            # 确保始终是字符串，避免datetime对象导致JSON序列化失败
            if isinstance(params.end_date, datetime):
                values['end_date'] = params.end_date.strftime('%Y%m%d')
            else:
                values['end_date'] = str(params.end_date)

        # 兼容initial_capital字段
        initial_capital = values.get('initial_capital')
        if initial_capital and values.get('initial_cash') == 1000000.0:
            values['initial_cash'] = initial_capital

        # 兼容params里的enable字段
        if hasattr(params, 'force_empty_position'):
            values['enable_force_empty'] = getattr(params, 'force_empty_position', True)
        if hasattr(params, 'sentiment_cycle'):
            values['enable_sentiment_cycle'] = getattr(params, 'sentiment_cycle', True)
        if hasattr(params, 'auction_filter'):
            values['enable_auction_filter'] = getattr(params, 'auction_filter', True)

        return values

    # 允许所有额外字段，不会过滤任何前端提交的内容
    class Config:
        extra = 'allow'
        json_schema_extra = {
            "example": {
                "strategies": ["halfway_chase"],
                "start_date": "20260105",
                "end_date": "20260320",
                "initial_cash": 1000000,
                "params": {
                    "liquidity_threshold": 500,
                    "volume_threshold": 1.5,
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.07,
                    "max_hold_days": 3,
                    "max_position_per_stock": 0.2,
                    "max_position": 0.7,
                },
                "enable_force_empty": True,
                "enable_sentiment_cycle": True,
                "enable_auction_filter": True,
            }
        }


class BacktestTaskResponse(BaseModel):
    """回测任务响应"""
    task_id: str
    status: str
    message: str
