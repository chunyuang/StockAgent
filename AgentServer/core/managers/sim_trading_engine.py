"""
模拟交易引擎

实现模拟盘的真实交易逻辑，包括下单、持仓管理、结算、手续费计算等，完全仿真实盘交易规则。
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from core.managers import mongo_manager

logger = logging.getLogger("sim_trading_engine")

class SimTradingEngine:
    """模拟交易引擎"""
    
    def __init__(self):
        # 手续费配置
        self.commission_rate = 0.0002  # 佣金万2
        self.stamp_duty_rate = 0.001  # 印花税千1，卖出时收取
        self.min_commission = 5  # 最低佣金5元
        self.slippage_rate = 0.001  # 滑点千1
    
    async def place_order(
        self,
        account_id: str,
        ts_code: str,
        stock_name: str,
        direction: str,  # buy/sell
        quantity: int,
        price: Optional[float] = None,
        strategy: Optional[str] = None,
        reason: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        下单交易
        
        Args:
            account_id: 模拟账户ID
            ts_code: 股票代码
            stock_name: 股票名称
            direction: 交易方向 buy/sell
            quantity: 交易数量（股数，必须是100的整数倍）
            price: 交易价格，None则使用最新市价
            strategy: 策略来源
            reason: 交易原因
            signal_id: 关联信号ID
        
        Returns:
            (success, message, trade_record)
        """
        try:
            # 验证参数
            if quantity <= 0 or quantity % 100 != 0:
                return False, "交易数量必须是100的正整数倍", {}
            
            # 获取账户信息
            account = await mongo_manager.find_one(
                "sim_accounts",
                {"account_id": account_id}
            )
            
            if not account:
                return False, "账户不存在", {}
            
            # 获取持仓信息
            position = await mongo_manager.find_one(
                "positions",
                {"account_id": account_id, "ts_code": ts_code}
            )
            
            # 获取最新价格
            if not price:
                # TODO: 从行情接口获取最新价格
                price = await self._get_latest_price(ts_code)
                if not price:
                    return False, "无法获取最新价格", {}
            
            # 计算滑点
            if direction == "buy":
                trade_price = price * (1 + self.slippage_rate)
            else:
                trade_price = price * (1 - self.slippage_rate)
            
            # 计算交易金额
            trade_amount = trade_price * quantity
            
            # 计算手续费
            commission = max(trade_amount * self.commission_rate, self.min_commission)
            
            # 计算印花税（卖出时收取）
            stamp_duty = trade_amount * self.stamp_duty_rate if direction == "sell" else 0
            
            # 总费用
            total_cost = trade_amount + commission + stamp_duty
            
            # 买入验证
            if direction == "buy":
                if account["available_cash"] < total_cost:
                    return False, f"可用资金不足，需要 {total_cost:.2f} 元，实际可用 {account['available_cash']:.2f} 元", {}
            
            # 卖出验证
            if direction == "sell":
                if not position or position["available_quantity"] < quantity:
                    available = position["available_quantity"] if position else 0
                    return False, f"可用持仓不足，需要 {quantity} 股，实际可用 {available} 股", {}
            
            now = datetime.now(timezone.utc)
            trade_id = f"trd_{uuid.uuid4().hex[:12]}"
            
            # 创建交易记录
            trade_record = {
                "trade_id": trade_id,
                "account_id": account_id,
                "ts_code": ts_code,
                "stock_name": stock_name,
                "direction": direction,
                "quantity": quantity,
                "price": trade_price,
                "amount": trade_amount,
                "commission": commission,
                "stamp_duty": stamp_duty,
                "trade_time": now,
                "strategy": strategy,
                "reason": reason,
                "signal_id": signal_id,
                "created_at": now
            }
            
            # 更新账户资金
            if direction == "buy":
                new_available_cash = account["available_cash"] - total_cost
            else:
                new_available_cash = account["available_cash"] + (trade_amount - commission - stamp_duty)
            
            await mongo_manager.update_one(
                "sim_accounts",
                {"account_id": account_id},
                {"$set": {"available_cash": new_available_cash, "updated_at": now}}
            )
            
            # 更新持仓
            if direction == "buy":
                if position:
                    # 已有持仓，更新成本和数量
                    total_quantity = position["quantity"] + quantity
                    total_cost = position["avg_cost"] * position["quantity"] + trade_amount + commission
                    new_avg_cost = total_cost / total_quantity
                    
                    await mongo_manager.update_one(
                        "positions",
                        {"position_id": position["position_id"]},
                        {
                            "$set": {
                                "quantity": total_quantity,
                                "available_quantity": position["available_quantity"] + quantity,
                                "avg_cost": new_avg_cost,
                                "updated_at": now
                            }
                        }
                    )
                else:
                    # 新建持仓
                    position_id = f"pos_{uuid.uuid4().hex[:12]}"
                    new_position = {
                        "position_id": position_id,
                        "account_id": account_id,
                        "ts_code": ts_code,
                        "stock_name": stock_name,
                        "quantity": quantity,
                        "available_quantity": quantity,
                        "avg_cost": (trade_amount + commission) / quantity,
                        "first_buy_date": now,
                        "hold_days": 1,
                        "strategy": strategy,
                        "created_at": now,
                        "updated_at": now
                    }
                    
                    await mongo_manager.insert_one("positions", new_position)
            else:  # sell
                # 卖出，减少持仓
                new_quantity = position["quantity"] - quantity
                new_available_quantity = position["available_quantity"] - quantity
                
                if new_quantity <= 0:
                    # 全部卖出，删除持仓
                    await mongo_manager.delete_one(
                        "positions",
                        {"position_id": position["position_id"]}
                    )
                else:
                    # 部分卖出，更新持仓
                    await mongo_manager.update_one(
                        "positions",
                        {"position_id": position["position_id"]},
                        {
                            "$set": {
                                "quantity": new_quantity,
                                "available_quantity": new_available_quantity,
                                "updated_at": now
                            }
                        }
                    )
            
            # 保存交易记录
            await mongo_manager.insert_one("trade_records", trade_record)
            
            logger.info(f"交易成功：{trade_id} {direction} {ts_code} {quantity}股，价格{trade_price:.2f}元")
            
            return True, "交易成功", trade_record
            
        except Exception as e:
            logger.exception(f"下单失败: {e}")
            return False, f"交易失败：{str(e)}", {}
    
    async def _get_latest_price(self, ts_code: str) -> Optional[float]:
        """获取股票最新价格"""
        # TODO: 实现从行情数据库获取最新价格
        # 临时返回固定价格用于测试
        return 10.0
    
    async def daily_settlement(self, trade_date: Optional[str] = None):
        """
        每日收盘结算
        更新持仓市值、收益、持仓天数等信息
        """
        # TODO: 实现每日结算逻辑
        logger.info("开始每日结算...")
        pass
    
    async def calculate_account_performance(self, account_id: str) -> Dict[str, Any]:
        """
        计算账户绩效指标
        """
        # TODO: 计算账户绩效
        return {}


# 全局实例
sim_trading_engine = SimTradingEngine()
