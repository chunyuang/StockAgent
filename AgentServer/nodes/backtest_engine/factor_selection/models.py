"""
回测引擎数据模型

包含所有数据类定义，用于回测过程中的数据传递和状态管理。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class RebalanceRecord:
    """调仓记录
    
    记录每一笔买入/卖出操作的详细信息。
    """
    date: str  # 交易日期 (YYYYMMDD)
    action: str  # "buy" | "sell"
    ts_code: str  # 股票代码 (如 000001.SZ)
    shares: int  # 股数
    price: float  # 成交价
    amount: float  # 成交金额（买入为负，卖出为正）
    reason: str  # 交易原因
    strategy_name: str = ""  # 策略名称（独立字段，不从reason提取）
    sentiment: str = ""  # 当日情绪周期状态


@dataclass
class PortfolioSnapshot:
    """组合快照
    
    记录某一时刻的投资组合状态。
    """
    date: str  # 快照日期 (YYYYMMDD)
    cash: float  # 现金
    holdings: Dict[str, int]  # 持仓 {ts_code: shares}
    prices: Dict[str, float]  # 价格 {ts_code: price}
    market_value: float  # 持仓市值
    total_value: float  # 总资产


@dataclass
class RunState:
    """回测运行时状态
    
    包含回测过程中的所有运行时状态，用于在方法间传递。
    """
    # 配置
    config: Dict[str, Any]
    
    # 资金和持仓
    cash: float
    holdings: Dict[str, int]
    initial_cash: float
    
    # 交易记录
    rebalance_records: List[RebalanceRecord]
    
    # 价格数据
    last_prices: Dict[str, Dict[str, float]]
    stock_names: Dict[str, str]
    
    # 净值和绩效
    net_value_series: List[Dict[str, Any]]
    daily_profit_list: List[float]
    drawdown_series: List[float]
    daily_cash_list: List[float]
    peak_value: float
    last_net_value: float
    
    # 日期信息
    all_trade_dates: List[str]
    rebalance_dates: List[str]
    rebalance_set: set
    total_days: int
    
    # 基准数据
    benchmark_data: Optional[Dict[str, Any]] = None
    
    # 排除规则
    exclude_rules: List[Any] = field(default_factory=list)
    
    # 错误信息
    error: Optional[str] = None


@dataclass
class StrategySignal:
    """策略信号
    
    记录某个策略在某一天的选股结果。
    """
    strategy_name: str  # 策略名称
    trade_date: str  # 交易日期
    candidates: List[str]  # 候选股票列表
    conditions: List[Dict[str, Any]]  # 筛选条件
    params: Dict[str, Any]  # 策略参数


@dataclass
class RiskConfig:
    """风控配置
    
    包含所有风控相关的配置参数。
    """
    enable_stop_loss: bool = True
    stop_loss_pct: float = 0.03  # 3%
    enable_take_profit: bool = True
    take_profit_pct: float = 0.07  # 7%
    max_hold_days: int = 3
    max_position_per_stock: float = 0.2  # 20%
    enable_ma60_filter: bool = True
    enable_sector_concentration: bool = True
    sector_concentration_top_n: int = 3
    enable_auction_filter: bool = True
    enable_sentiment_cycle: bool = True
    enable_force_empty: bool = True


@dataclass
class BacktestResult:
    """回测结果
    
    包含回测的所有结果数据。
    """
    # 基本信息
    task_id: str
    start_date: str
    end_date: str
    initial_cash: float
    final_value: float
    
    # 绩效指标
    total_return: float  # 总收益率
    annualized_return: float  # 年化收益率
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    sortino_ratio: float  # 索提诺比率
    calmar_ratio: float  # 卡玛比率
    win_rate: float  # 胜率
    profit_loss_ratio: float  # 盈亏比
    
    # 交易统计
    total_trades: int  # 总交易次数
    winning_trades: int  # 盈利次数
    losing_trades: int  # 亏损次数
    avg_hold_days: float  # 平均持仓天数
    
    # 详细数据
    trades: List[Dict[str, Any]] = field(default_factory=list)
    net_value_series: List[Dict[str, Any]] = field(default_factory=list)
    drawdown_series: List[float] = field(default_factory=list)
    daily_profit: List[float] = field(default_factory=list)
    
    # 策略分解
    strategy_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    factor_contribution: Dict[str, float] = field(default_factory=dict)
    monthly_profit: Dict[str, float] = field(default_factory=dict)
    
    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    execution_time_ms: int = 0
