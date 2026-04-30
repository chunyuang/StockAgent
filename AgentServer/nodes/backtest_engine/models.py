"""
回测引擎数据模型

从 backtester.py 拆出的数据类，供多个模块共享使用。
backtester.py 已废弃，数据类保留在此。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any
from datetime import datetime
from enum import Enum

import pandas as pd


class TradeDirection(Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class BacktestConfig:
    """回测配置"""
    # 资金配置
    initial_cash: float = 1000000.0

    # 信号阈值
    entry_threshold: float = 0.7
    exit_threshold: float = 0.3

    # 仓位管理
    position_size: float = 1.0
    max_position_pct: float = 0.7

    # 费用配置 (A股标准)
    commission_rate: float = 0.0002
    stamp_duty_rate: float = 0.001
    min_commission: float = 5.0

    # 滑点
    slippage: float = 0.001

    # A股规则
    enable_t1: bool = True
    enable_limit_check: bool = True

    # 因子权重
    factor_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class Trade:
    """交易记录"""
    date: datetime
    direction: TradeDirection
    price: float
    shares: int
    amount: float
    commission: float
    stamp_duty: float
    reason: str = ""


@dataclass
class BacktestResult:
    """回测结果"""
    # 基础信息
    ts_code: str
    start_date: str
    end_date: str
    config: BacktestConfig

    # 净值曲线
    daily_nav: pd.Series = None
    daily_equity: pd.Series = None
    daily_cash: pd.Series = None
    daily_position_value: pd.Series = None

    # 交易记录
    trades: List[Trade] = field(default_factory=list)

    # 信号数据
    signal_series: pd.Series = None
    position_series: pd.Series = None

    # 基准对比
    benchmark_nav: pd.Series = None

    # 执行状态
    success: bool = True
    error_message: str = ""
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化的字典"""
        return {
            "ts_code": self.ts_code,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "success": self.success,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "config": {
                "initial_cash": self.config.initial_cash,
                "entry_threshold": self.config.entry_threshold,
                "exit_threshold": self.config.exit_threshold,
                "position_size": self.config.position_size,
            },
            "nav_series": self.daily_nav.tolist() if self.daily_nav is not None else [],
            "nav_dates": [d.strftime("%Y-%m-%d") for d in self.daily_nav.index] if self.daily_nav is not None else [],
            "benchmark_nav": self.benchmark_nav.tolist() if self.benchmark_nav is not None else [],
            "trades_count": len(self.trades),
            "trades": [
                {
                    "date": t.date.strftime("%Y-%m-%d"),
                    "direction": t.direction.value,
                    "price": round(t.price, 2),
                    "shares": t.shares,
                    "amount": round(t.amount, 2),
                    "commission": round(t.commission, 2),
                    "reason": t.reason,
                }
                for t in self.trades[:50]
            ],
        }
