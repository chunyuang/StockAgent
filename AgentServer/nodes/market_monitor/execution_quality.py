"""
ExecutionQuality — 交易执行质量模块

解决核心问题: 实盘与回测执行层一致性
- 之前: L9买入执行"只有注释没有实现", 无流动性检查/冲击成本估算
- 现在: 补全执行层, 与回测SimulatedExecutor对齐

包含:
1. PreTradeChecker: 下单前流动性检查(涨停不可买/跌停不可卖/停牌/科创板门槛)
2. SlippageModel: 冲击成本估算(与回测should_apply_slippage对齐)
3. FillSimulator: 成交概率模拟(大单拆分/部分成交)

与回测对齐点:
- 涨跌停限制: broker.py已实现 _calc_limit_prices
- 佣金: 万3+千1印花税(broker.py已实现)
- 滑点: 回测 should_apply_slippage 规则(止损/超时/强制空仓不扣滑点)
- T+1: broker.py today_buy_qty 追踪

用法:
    from nodes.market_monitor.execution_quality import PreTradeChecker, SlippageModel
    
    # 下单前检查
    checker = PreTradeChecker(broker)
    ok, reason = checker.check_buy(ts_code, price, quantity)
    if not ok:
        return  # 跳过
    
    # 滑点估算
    slippage = SlippageModel.estimate(price, quantity, daily_volume, side="buy")
    adjusted_price = price * (1 + slippage)
"""

import logging
import math
from datetime import datetime
from typing import Tuple, Optional, Dict

logger = logging.getLogger("execution.quality")


class PreTradeChecker:
    """
    下单前检查
    
    检查项(与回测portfolio_backtest.py的买入逻辑对齐):
    1. 涨停不可买入(排板不确定性太高)
    2. 跌停不可卖出(挂单无法成交)
    3. 停牌股不可交易
    4. 科创板最低200股
    5. ST股过滤(已在L4层处理,此处二次确认)
    6. 单票仓位上限
    7. 总仓位上限
    8. 可用资金充足
    """
    
    def __init__(self, broker=None, config: Dict = None):
        self._broker = broker
        self._config = config or {}
        self._max_position_per_stock = self._config.get("max_position_per_stock", 0.35)
        self._max_total_position = self._config.get("max_total_position", 0.70)
    
    def check_buy(
        self,
        ts_code: str,
        price: float,
        quantity: int,
        stock_name: str = "",
        strategy: str = "",
    ) -> Tuple[bool, str]:
        """买入前检查(编排方法)"""
        if not self._broker:
            return True, "broker未关联,跳过检查"

        # 基础检查
        ok, reason = self._check_buy_basics(ts_code, price, quantity, stock_name)
        if not ok:
            return False, reason

        # 仓位+资金检查
        return self._check_buy_position_and_cash(ts_code, price, quantity)

    def _check_buy_basics(
        self, ts_code: str, price: float, quantity: int, stock_name: str,
    ) -> Tuple[bool, str]:
        """买入基础检查(参数+ST+涨停+停牌)"""
        if price <= 0:
            return False, f"价格异常: {price}"
        if quantity <= 0:
            return False, f"数量异常: {quantity}"
        if ts_code.startswith("688") and quantity < 200:
            return False, f"科创板最小200股, 当前{quantity}股"
        if stock_name and self._is_st_stock(stock_name):
            return False, f"ST股: {stock_name}"
        if self._is_at_limit_up(ts_code, price):
            return False, f"涨停价不可买入(排板不确定性)"
        if self._is_suspended(ts_code):
            return False, f"停牌: {ts_code}"
        return True, "通过"

    def _check_buy_position_and_cash(
        self, ts_code: str, price: float, quantity: int,
    ) -> Tuple[bool, str]:
        """买入仓位+资金检查"""
        acct = self._broker.get_account()
        if not acct:
            return True, "通过(无账户信息)"

        order_amount = price * quantity
        stock_mv = sum(
            p.current_price * p.total_qty
            for p in self._broker.get_positions()
            if p.ts_code == ts_code and p.current_price is not None
        )
        stock_mv += order_amount
        total_asset = acct.total_assets

        if total_asset > 0 and stock_mv / total_asset > self._max_position_per_stock:
            return False, f"单票仓位超限: {stock_mv/total_asset:.1%} > {self._max_position_per_stock:.1%}"

        total_mv = acct.market_value + order_amount
        if total_asset > 0 and total_mv / total_asset > self._max_total_position:
            return False, f"总仓位超限: {total_mv/total_asset:.1%} > {self._max_total_position:.1%}"

        if order_amount > acct.available_cash:
            return False, f"资金不足: 需{order_amount:.0f}, 可用{acct.available_cash:.0f}"

        return True, "通过"
    
    def check_sell(
        self,
        ts_code: str,
        price: float,
        quantity: int,
    ) -> Tuple[bool, str]:
        """卖出前检查"""
        # 1. 跌停不可卖出
        if self._is_at_limit_down(ts_code, price):
            return False, f"跌停价不可卖出(挂单无法成交)"
        
        # 2. 停牌
        if self._is_suspended(ts_code):
            return False, f"停牌: {ts_code}"
        
        return True, "通过"
    
    # ==================== 内部方法 ====================
    
    def _is_st_stock(self, name: str) -> bool:
        """判断ST股"""
        if not name:
            return False
        name_upper = name.upper()
        for pattern in ["*ST", "ST", "S*ST", "SST"]:
            if name_upper.startswith(pattern):
                return True
        return False
    
    def _is_at_limit_up(self, ts_code: str, price: float) -> bool:
        """判断是否在涨停价"""
        if not self._broker:
            return False
        info = self._broker.get_limit_prices(ts_code)
        up_limit = info.get("up_limit", 0)
        if up_limit > 0 and price >= up_limit:
            return True
        return False
    
    def _is_at_limit_down(self, ts_code: str, price: float) -> bool:
        """判断是否在跌停价"""
        if not self._broker:
            return False
        info = self._broker.get_limit_prices(ts_code)
        down_limit = info.get("down_limit", 0)
        if down_limit > 0 and price <= down_limit:
            return True
        return False
    
    def _is_suspended(self, ts_code: str) -> bool:
        """判断是否停牌(简化: 价格为0视为停牌)"""
        if not self._broker:
            return False
        price_info = self._broker.get_realtime_prices(ts_code)
        if isinstance(price_info, (int, float)):
            return price_info <= 0
        if isinstance(price_info, dict):
            return price_info.get("price", 0) <= 0
        return True


class SlippageModel:
    """
    滑点模型(与回测portfolio_backtest.py对齐)
    
    回测规则:
    - 止损卖出: 不扣滑点(已亏损,不加额外成本)
    - 超时卖出: 不扣滑点
    - 强制空仓: 不扣滑点
    - 正常买入/卖出: 扣滑点
    
    实盘规则(对齐):
    - 滑点 = 价格 × 滑点率 × 方向系数
    - 买入: 正滑点(实际成交价更高)
    - 卖出: 负滑点(实际成交价更低)
    - 大单冲击: 根据订单量/日成交量比率额外加滑点
    """
    
    # 基础滑点率(与回测 should_apply_slippage 对齐)
    BASE_SLIPPAGE = 0.001  # 0.1% (回测默认)
    
    # 大单冲击阈值
    LARGE_ORDER_RATIO = 0.01  # 订单量 > 日成交量1%视为大单
    
    @staticmethod
    def estimate(
        price: float,
        quantity: int,
        daily_volume: float = 0,
        side: str = "buy",
        reason: str = "",
    ) -> float:
        """
        估算滑点(返回滑点率, 正数=向上滑, 负数=向下滑)
        
        Args:
            price: 下单价格
            quantity: 下单数量
            daily_volume: 当日成交量(股), 0表示未知
            side: buy/sell
            reason: 卖出原因(止损/超时/强制空仓不扣滑点)
        
        Returns:
            滑点率(如0.001表示0.1%), 买入为正, 卖出为负
        """
        # 止损/超时/强制空仓: 不扣滑点(与回测对齐)
        no_slippage_reasons = ["止损", "stop_loss", "超时", "timeout", "强制空仓", "force_empty"]
        if any(r in reason for r in no_slippage_reasons):
            return 0.0
        
        # 基础滑点
        slippage = SlippageModel.BASE_SLIPPAGE
        
        # 大单冲击
        if daily_volume > 0:
            order_ratio = (quantity * price) / (daily_volume * price) if daily_volume > 0 else 0
            if order_ratio > SlippageModel.LARGE_ORDER_RATIO:
                # 大单: 额外加0.05%-0.5%滑点(按比例)
                impact = min(0.005, order_ratio * 0.5)  # 最多0.5%
                slippage += impact
        
        # 方向: 买入正滑点, 卖出负滑点
        if side == "sell":
            slippage = -slippage
        
        return slippage
    
    @staticmethod
    def apply_slippage(price: float, slippage_rate: float) -> float:
        """应用滑点到价格"""
        return price * (1 + slippage_rate)


class FillSimulator:
    """
    成交模拟器
    
    超短策略的特点: 
    - 涨停/跌停附近流动性极低
    - 封板瞬间买不进, 炸板瞬间卖不出
    - 大单可能只能部分成交
    
    模拟规则:
    1. 涨停附近(涨幅>9%): 成交概率30%
    2. 大涨(5-9%): 成交概率80%
    3. 正常(<5%): 成交概率95%
    4. 大单(>日成交量1%): 可能部分成交
    """
    
    @staticmethod
    def estimate_fill_rate(
        price: float,
        pre_close: float,
        quantity: int,
        daily_volume: float = 0,
        side: str = "buy",
        ts_code: str = "",
    ) -> Tuple[float, str]:
        """
        估算成交比率
        
        Returns:
            (fill_rate, reason) — fill_rate 0.0-1.0
        """
        if pre_close <= 0:
            return 0.95, "无前收盘价,默认95%"
        
        pct_chg = (price - pre_close) / pre_close * 100
        
        # 涨停/跌停附近 - 按板块区分阈值
        prefix = ts_code.split(".")[0][:3] if "." in ts_code else ts_code[:3]
        if prefix in ('688', '30'):
            limit_thresh = 19.5
        elif prefix in ('8', '4') and ts_code[:1] in ('8', '4'):
            limit_thresh = 29.5
        else:
            limit_thresh = 9.5
        if side == "buy" and pct_chg >= limit_thresh:
            return 0.30, "涨停附近,流动性极低"
        if side == "sell" and pct_chg <= -limit_thresh:
            return 0.30, "跌停附近,流动性极低"
        
        # 大涨/大跌
        if abs(pct_chg) >= 5:
            base_rate = 0.80
        else:
            base_rate = 0.95
        
        # 大单冲击
        if daily_volume > 0 and quantity > daily_volume * 0.01:
            # 订单量超过日成交量1%, 可能部分成交
            order_volume_ratio = quantity / daily_volume
            if order_volume_ratio > 0.05:
                base_rate *= 0.5  # 大单50%成交率
            elif order_volume_ratio > 0.02:
                base_rate *= 0.7  # 中单70%成交率
        
        return base_rate, f"预计成交{base_rate:.0%}"
