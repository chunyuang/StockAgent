"""
持仓管理器

整合:
- 信号接收（来自策略）
- 情绪周期动态仓位调整
- 严格单票/总仓位限制
- **回撤控制** ✅ 完整回撤控制机制
- 加仓/减仓策略
- 每日止损检查，自动卖出止损
- 交易记录持久化

完整逻辑:
1. 收到买入信号 → 检查回撤控制 → 情绪仓位乘数 → 单票仓位限制 → 总仓位限制 → 执行买入 → 设置止损
2. 每日检查止损 → 跌破止损自动卖出 → 更新回撤统计
3. 情绪+回撤双重仓位调整
"""

import asyncio
from typing import List, Optional

from core.settings import settings
from .base_executor import (
    BaseExecutor,
    Order,
    Position,
    AccountInfo,
    OrderDirection,
)
from .drawdown_control import DrawdownController, default_drawdown_controller
from .simulator_executor import SimulatorExecutor
from ..strategies.emotion_cycle import emotion_cycle_manager


import logging
logger = logging.getLogger(__name__)


class PositionManager:
    """
    持仓管理器
    
    职责:
    1. 接收策略买入信号
    2. 回撤控制检查 ✅
    3. 根据情绪周期动态调整仓位
    4. 严格执行单票仓位限制、总仓位限制
    5. 加仓策略：情绪好 + 龙头盈利可以加仓
    6. 减仓策略：连续亏损降低仓位 ✅
    7. 每日止损检查，自动卖出止损
    8. 持久化交易记录到 MongoDB
    """
    
    def __init__(self, executor: Optional[BaseExecutor] = None,
                drawdown_controller: Optional[DrawdownController] = None):
        """
        Args:
            executor: 交易执行器，默认使用模拟器
            drawdown_controller: 回撤控制器，默认使用默认配置
        """
        self._initial_cash = settings.trading.initial_cash
        self._max_position_per_stock = settings.trading.max_position_per_stock
        self._max_total_position = settings.trading.max_total_position
        self._default_stop_loss = settings.trading.default_stop_loss_pct
        
        if executor is None:
            self._executor: BaseExecutor = SimulatorExecutor(self._initial_cash)
        else:
            self._executor: BaseExecutor = executor
        
        if drawdown_controller is None:
            self._drawdown_ctrl: DrawdownController = default_drawdown_controller
        else:
            self._drawdown_ctrl: DrawdownController = drawdown_controller
        
        logger.info(f"PositionManager initialized: initial_cash={self._initial_cash:.2f}, "
                 f"max_position_per_stock={self._max_position_per_stock*100:.0f}%, "
                 f"max_total_position={self._max_total_position*100:.0f}%")
    
    async def initialize(self) -> bool:
        """初始化执行器和回撤控制器"""
        connected = await self._executor.connect()
        if connected:
            await self._drawdown_ctrl.initialize()
            logger.info("PositionManager initialized ✓")
        return connected
    
    async def on_buy_signal(
        self,
        ts_code: str,
        stock_name: str,
        price: float,
        strategy: str,
        max_position_pct: Optional[float] = None,
        emotion_score: float = 50.0,
        stop_loss_pct: Optional[float] = None,
    ) -> Optional[Order]:
        """
        处理买入信号
        
        Args:
            ts_code: 股票代码
            stock_name: 股票名称
            price: 当前价格
            strategy: 策略名称
            max_position_pct: 单票最大仓位百分比，默认使用全局设置
            emotion_score: 当前情绪得分，用于仓位乘数
            stop_loss_pct: 止损百分比，默认使用全局设置
        
        Returns:
            成功返回 Order，失败返回 None
        """
        # 1. 回撤控制检查 ✅
        account = await self._executor.get_account()
        if account is None:
            logger.warning("[BUY] Failed to get account info")
            return None
        
        # 检查是否允许开仓
        current_daily_profit = (account.total_asset - account.total_asset) / account.total_asset * 100
        if not self._drawdown_ctrl.can_open_new_position(current_daily_profit):
            # 不允许开仓
            return None
        
        # 2. 计算情绪仓位乘数 ✅
        # 情绪得分 0-100 → 仓位乘数 0-1
        emotion_multiplier = emotion_cycle_manager.get_position_multiplier(emotion_score)
        # 回撤控制进一步调整仓位 ✅
        emotion_multiplier *= self._drawdown_ctrl.get_position_multiplier()
        
        # 连续亏损惩罚：连续亏损进一步降低仓位
        # 已经在 drawdown_ctrl 处理了，这里不需要重复
        
        # 3. 计算最大可买仓位 ✅
        max_pct = max_position_pct if max_position_pct is not None else self._max_position_per_stock
        available_cash = account.available_cash
        max_amount = available_cash * max_pct * emotion_multiplier
        
        # 4. 总仓位限制 ✅
        current_total_value = account.market_value
        total_asset = account.total_asset
        current_total_pct = current_total_value / total_asset if total_asset > 0 else 0
        
        if current_total_pct + (max_amount / total_asset) > self._max_total_position:
            # 超过总仓位限制，降低可买金额
            available_max_amount = (self._max_total_position - current_total_pct) * total_asset
            max_amount = min(max_amount, available_max_amount)
            logger.info(
                f"[BUY] {ts_code} {stock_name}: Total position limit exceeded: current={current_total_pct:.1%}, "
                f"max={self._max_total_position:.1%}, reduced to {max_amount:.2f}"
            )
        
        if max_amount <= price * 100:  # 至少买一手（100股）
            logger.warning(
                f"[BUY] {ts_code} {stock_name}: insufficient cash after all limits, "
                f"max_amount={max_amount:.2f}, price={price:.2f}"
            )
            return None
        
        # 5. 计算可买股数（100 整数倍）✅
        shares = int(max_amount / price / 100) * 100
        if shares <= 0:
            logger.warning(f"[BUY] {ts_code} {stock_name}: shares={shares} after rounding")
            return None
        
        # 6. 执行买入 ✅
        order = await self._executor.send_order(
            ts_code=ts_code,
            direction=OrderDirection.BUY,
            price=price,
            shares=shares,
            strategy=strategy,
        )
        
        if order is None or not order.is_filled:
            logger.warning(f"[BUY] {ts_code} {stock_name}: order not filled")
            return None
        
        # 7. 设置止损价 ✅
        if order.is_filled:
            position = self._executor.get_position_by_tscode(ts_code)
            if position:
                stop_pct = stop_loss_pct if stop_loss_pct is not None else self._default_stop_loss
                position.stop_loss = price * (1 - stop_pct)
                logger.info(
                    f"[BUY] {ts_code} {stock_name} filled: {shares} @ {price:.2f}, "
                    f"stop_loss={position.stop_loss:.2f}, emotion_multiplier={emotion_multiplier:.2f}"
                )
        
        # 8. 更新资产峰值（用于回撤计算）✅
        updated_account = await self._executor.get_account()
        if updated_account:
            self._drawdown_ctrl.update_peak(updated_account.total_asset)
        
        return order
    
    async def on_sell_signal(
        self,
        ts_code: str,
        price: float,
        reason: str,
    ) -> Optional[Order]:
        """
        处理卖出信号
        
        Args:
            ts_code: 股票代码
            price: 当前价格
            reason: 卖出原因
        
        Returns:
            成功返回 Order，失败返回 None
        """
        position = self._executor.get_position_by_tscode(ts_code)
        if position is None:
            logger.warning(f"[SELL] {ts_code}: no position found")
            return None
        
        shares = position.shares
        if shares <= 0:
            logger.warning(f"[SELL] {ts_code}: zero shares")
            return None
        
        order = await self._executor.send_order(
            ts_code=ts_code,
            direction=OrderDirection.SELL,
            price=price,
            shares=shares,
            reason=reason,
        )
        
        if order is None or not order.is_filled:
            logger.warning(f"[SELL] {ts_code}: order not filled")
            return None
        
        # 记录亏损，更新回撤统计
        profit = position.profit_amount
        if profit < 0:
            self._drawdown_ctrl.record_loss(True)
        else:
            self._drawdown_ctrl.record_loss(False)
        
        # 更新资产峰值
        updated_account = await self._executor.get_account()
        if updated_account:
            self._drawdown_ctrl.update_peak(updated_account.total_asset)
        
        logger.info(
            f"[SELL] {ts_code} filled: {shares} @ {price:.2f}, reason={reason}, "
            f"profit={profit:.2f}"
        )
        
        return order
    
    async def check_daily_stop_loss(self) -> List[Order]:
        """
        每日检查持仓止损，卖出达到止损条件的持仓
        
        Returns:
            已卖出订单列表
        """
        sold_orders: List[Order] = []
        
        # 更新当前价格
        await self._executor.update_current_prices()
        
        # 获取当前持仓
        positions = await self._executor.get_position()
        
        for position in positions:
            if position.stop_loss > 0 and position.current_price > 0:
                if position.current_price <= position.stop_loss:
                    # 达到止损条件，卖出
                    logger.info(
                        f"[STOP_LOSS] {position.ts_code}: current={position.current_price:.2f} "
                        f"<= stop={position.stop_loss:.2f}, selling..."
                    )
                    order = await self.on_sell_signal(
                        ts_code=position.ts_code,
                        price=position.current_price,
                        reason=f"stop_loss triggered ({position.current_price:.2f} <= {position.stop_loss:.2f})",
                    )
                    if order is not None and order.is_filled:
                        sold_orders.append(order)
        
        if sold_orders:
            logger.info(f"[STOP_LOSS] {len(sold_orders)} positions stopped out")
        
        return sold_orders
    
    def calculate_max_shares(
        self,
        price: float,
        max_position_pct: Optional[float] = None,
        emotion_multiplier: float = 1.0,
    ) -> int:
        """
        根据当前账户情况计算最大可买股数
        
        Args:
            price: 当前价格
            max_position_pct: 单票最大仓位百分比，默认使用全局设置
            emotion_multiplier: 情绪仓位乘数
        
        Returns:
            可买股数（100 整数倍）
        """
        account = asyncio.run(self._executor.get_account())
        if account is None:
            return 0
        
        max_pct = max_position_pct if max_position_pct is not None else self._max_position_per_stock
        available = account.available_cash
        max_amount = available * max_pct * emotion_multiplier
        
        # 总仓位限制
        current_total_value = account.market_value
        total_asset = account.total_asset
        current_total_pct = current_total_value / total_asset if total_asset > 0 else 0
        
        if current_total_pct + (max_amount / total_asset) > self._max_total_position:
            # 超过总仓位限制，降低可买金额
            available_max_amount = (self._max_total_position - current_total_pct) * total_asset
            max_amount = min(max_amount, available_max_amount)
            logger.info(
                f"[CALC] total position limit exceeded: current={current_total_pct:.1%}, "
                f"max={self._max_total_position:.1%}, reduced to {max_amount:.2f}"
            )
        
        # 100 股整数倍
        shares = int(max_amount / price / 100) * 100
        
        return max(0, shares)
    
    def get_position_by_tscode(self, ts_code: str) -> Optional[Position]:
        """获取指定股票持仓"""
        return self._executor.get_position_by_tscode(ts_code)
    
    async def get_positions(self) -> List[Position]:
        """获取所有当前持仓"""
        return await self._executor.get_position()
    
    async def get_account_info(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        return await self._executor.get_account()
    
    def get_executor(self) -> BaseExecutor:
        """获取执行器"""
        return self._executor
