"""
模拟交易引擎

实现模拟盘的真实交易逻辑，包括下单、持仓管理、结算、手续费计算等，完全仿真实盘交易规则。
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from core.managers import mongo_manager
from core.constants import C

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
                C.SIM_ACCOUNTS,
                {"account_id": account_id}
            )
            
            if not account:
                return False, "账户不存在", {}
            
            # 获取持仓信息
            position = await mongo_manager.find_one(
                C.POSITIONS,
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
                if account.get("available_cash", 0) < total_cost:
                    return False, f"可用资金不足，需要 {total_cost:.2f} 元，实际可用 {account.get('available_cash', 0):.2f} 元", {}
            
            # 卖出验证
            if direction == "sell":
                if not position or position.get("available_quantity", 0) < quantity:
                    available = position.get("available_quantity", 0) if position else 0
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
            # 【P1修复：买入总成本已含佣金+印花税，但印花税买入时为0，所以total_cost=trade_amount+commission】
            # 卖出时：净收入=trade_amount-commission-stamp_duty
            if direction == "buy":
                new_available_cash = account.get("available_cash", 0) - total_cost
            else:
                new_available_cash = account.get("available_cash", 0) + (trade_amount - commission - stamp_duty)
            
            await mongo_manager.update_one(
                C.SIM_ACCOUNTS,
                {"account_id": account_id},
                {"$set": {"available_cash": new_available_cash, "updated_at": now}}
            )
            
            # 更新持仓
            if direction == "buy":
                if position:
                    # 已有持仓，更新成本和数量
                    # 【P0修复：avg_cost计算含买入佣金是正确的，但外层total_cost变量名遮蔽了此处】
                    # 外层total_cost=trade_amount+commission+stamp_duty(含卖出印花税)，此处只需trade_amount+commission
                    total_quantity = position.get("quantity", 0) + quantity
                    buy_total_cost = position.get("avg_cost", 0) * position.get("quantity", 0) + trade_amount + commission
                    new_avg_cost = buy_total_cost / total_quantity
                    
                    await mongo_manager.update_one(
                        C.POSITIONS,
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
                    # 【P0修复：avg_cost应含买入佣金，(trade_amount+commission)/quantity是正确成本价】
                    position_id = f"pos_{uuid.uuid4().hex[:12]}"
                    new_position = {
                        "position_id": position_id,
                        "account_id": account_id,
                        "ts_code": ts_code,
                        "stock_name": stock_name,
                        "quantity": quantity,
                        "available_quantity": quantity,
                        "avg_cost": (trade_amount + commission) / quantity,  # 含佣金成本价
                        "first_buy_date": now,
                        "hold_days": 1,
                        "strategy": strategy,
                        "created_at": now,
                        "updated_at": now
                    }
                    
                    await mongo_manager.insert_one(C.POSITIONS, new_position)
            else:  # sell
                # 卖出，减少持仓
                new_quantity = position["quantity"] - quantity
                new_available_quantity = position["available_quantity"] - quantity
                
                if new_quantity <= 0:
                    # 全部卖出，删除持仓
                    # 【P1修复：全卖时删除持仓而非设quantity=0，与_check_and_execute_risk_sells设0不一致】
                    # 统一为删除(更干净)
                    await mongo_manager.delete_one(
                        C.POSITIONS,
                        {"position_id": position.get("position_id")}
                    )
                else:
                    # 部分卖出，更新持仓
                    await mongo_manager.update_one(
                        C.POSITIONS,
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
            await mongo_manager.insert_one(C.TRADE_RECORDS, trade_record)
            
            logger.info(f"交易成功：{trade_id} {direction} {ts_code} {quantity}股，价格{trade_price:.2f}元")
            
            return True, "交易成功", trade_record
            
        except Exception as e:
            logger.exception(f"下单失败: {e}")
            return False, f"交易失败：{str(e)}", {}
    
    async def _check_and_execute_risk_sells(self, accounts: list) -> int:
        """每日结算后检查止损/止盈/超期，执行强卖
        
        回测引擎已有非调仓日止损(第十轮P1-5)，但sim_trading_engine的
        daily_settlement只更新估值不执行卖出。此方法补全实盘/模拟交易侧。
        
        Returns:
            执行卖出的数量
        """
        risk_sell_count = 0
        
        # 风控参数(从配置读取，未配置则用默认值)
        stop_loss_pct = 0.02   # 止损: -2%
        take_profit_pct = 0.07 # 止盈: +7%
        max_hold_days = 10     # 超期: 10个交易日
        
        try:
            from core.settings import settings
            risk_cfg = getattr(settings, 'risk', {})
            stop_loss_pct = risk_cfg.get('stop_loss_pct', stop_loss_pct)
            take_profit_pct = risk_cfg.get('take_profit_pct', take_profit_pct)
            max_hold_days = risk_cfg.get('max_hold_days', max_hold_days)
        except Exception:
            pass
        
        for account in accounts:
            account_id = account.get("account_id")
            if not account_id:
                continue
            
            positions = await mongo_manager.find_many(
                C.POSITIONS,
                {"account_id": account_id, "quantity": {"$gt": 0}},
            )
            if not positions:
                continue
            
            sell_codes = []  # [(ts_code, reason, price)]
            
            for pos in positions:
                ts_code = pos["ts_code"]
                avg_cost = pos.get("avg_cost", 0)
                quantity = pos.get("quantity", 0)
                hold_days = pos.get("hold_days", 0)
                
                if avg_cost <= 0 or quantity <= 0:
                    continue
                
                # 获取最新价
                current_price = await self._get_latest_price(ts_code)
                if not current_price or current_price <= 0:
                    continue
                
                # 止损检查
                if current_price <= avg_cost * (1 - stop_loss_pct):
                    sell_codes.append((ts_code, f'止损({current_price/avg_cost-1:.1%})', current_price))
                    continue
                
                # 止盈检查
                if current_price >= avg_cost * (1 + take_profit_pct):
                    sell_codes.append((ts_code, f'止盈({current_price/avg_cost-1:.1%})', current_price))
                    continue
                
                # 超期检查
                if hold_days >= max_hold_days:
                    sell_codes.append((ts_code, f'超期({hold_days}天)', current_price))
                    continue
            
            # 执行卖出
            for ts_code, reason, sell_price in sell_codes:
                try:
                    # 更新持仓: quantity→0
                    pos_doc = await mongo_manager.find_one(
                        C.POSITIONS,
                        {"account_id": account_id, "ts_code": ts_code, "quantity": {"$gt": 0}},
                    )
                    if not pos_doc:
                        continue
                    
                    quantity = pos_doc["quantity"]
                    sell_amount = sell_price * quantity
                    # 【P1修复：手续费使用引擎配置而非硬编码，与place_order一致】
                    commission = max(sell_amount * self.commission_rate, self.min_commission)
                    stamp_tax = sell_amount * self.stamp_duty_rate
                    net_amount = sell_amount - commission - stamp_tax
                    
                    # 【P1修复：全卖后删除持仓(与place_order一致)，而非设quantity=0留僵尸记录】
                    await mongo_manager.delete_one(
                        C.POSITIONS,
                        {"position_id": pos_doc.get("position_id")}
                    )
                    
                    # 回收资金到账户
                    await mongo_manager.update_one(
                        C.SIM_ACCOUNTS,
                        {"account_id": account_id},
                        {"$inc": {"available_cash": net_amount}},
                    )
                    
                    risk_sell_count += 1
                    logger.info(
                        f"风控卖出: account={account_id} {ts_code} "
                        f"qty={quantity} price={sell_price:.2f} reason={reason}"
                    )
                    
                except Exception as e:
                    logger.error(f"风控卖出执行失败: {ts_code} {e}")
        
        return risk_sell_count
    
    async def _get_latest_price(self, ts_code: str) -> Optional[float]:
        """获取股票最新价格"""
        # 【P1修复：不再返回硬编码10.0，从MongoDB获取最近收盘价】
        try:
            doc = await mongo_manager.find_one(
                C.STOCK_DAILY,
                {"ts_code": ts_code},
                projection={"close": 1, "trade_date": 1},
                sort=[("trade_date", -1)],
            )
            if doc and doc.get("close", 0) > 0:
                return doc["close"]
        except Exception as e:
            logger.warning(f"Failed to get latest price for {ts_code}: {e}")
        return None
    
    async def daily_settlement(self, trade_date: Optional[str] = None):
        """
        每日收盘结算
        更新持仓市值、收益、持仓天数等信息
        
        流程:
        1. 获取所有活跃账户
        2. 对每个账户的每个持仓:
           a. 获取最新收盘价
           b. 更新持仓天数(近似交易日=日历天数×0.67)
           c. 计算当前市值和浮动盈亏
        3. 更新账户总资产
        """
        logger.info(f"开始每日结算 trade_date={trade_date}...")
        
        # 获取所有活跃账户
        accounts = await mongo_manager.find_many(
            C.SIM_ACCOUNTS,
            {},
            projection={"account_id": 1},
        )
        if not accounts:
            logger.info("无活跃账户，跳过结算")
            return
        
        settled_count = 0
        for account in accounts:
            account_id = account["account_id"]
            
            # 获取该账户所有持仓
            positions = await mongo_manager.find_many(
                C.POSITIONS,
                {"account_id": account_id, "quantity": {"$gt": 0}},
            )
            if not positions:
                continue
            
            total_market_value = 0
            now = datetime.now(timezone.utc)
            
            for pos in positions:
                ts_code = pos["ts_code"]
                latest_price = await self._get_latest_price(ts_code)
                
                if not latest_price or latest_price <= 0:
                    logger.warning(f"{ts_code} 无法获取最新价，跳过结算")
                    # 用成本价估算
                    latest_price = pos.get("avg_cost", 0)
                
                market_value = latest_price * pos["quantity"]
                total_market_value += market_value
                
                # 更新持仓天数(近似交易日)
                first_buy = pos.get("first_buy_date")
                hold_days = pos.get("hold_days", 1)
                if first_buy:
                    if isinstance(first_buy, str):
                        first_buy = datetime.fromisoformat(first_buy.replace('Z', '+00:00'))
                    calendar_days = (now - first_buy).days
                    # 【P1修复：日历天数→交易日，系数0.67(5/7≈0.71，考虑节假日0.67更保守)】
                    hold_days = max(1, int(calendar_days * 0.67))
                
                # 更新持仓记录
                await mongo_manager.update_one(
                    C.POSITIONS,
                    {"position_id": pos["position_id"]},
                    {"$set": {
                        "current_price": latest_price,
                        "market_value": market_value,
                        "profit": market_value - pos["avg_cost"] * pos["quantity"],
                        "profit_pct": (latest_price / pos["avg_cost"] - 1) if pos["avg_cost"] > 0 else 0,
                        "hold_days": hold_days,
                        "updated_at": now,
                    }}
                )
            
            # 更新账户总资产
            account_data = await mongo_manager.find_one(
                C.SIM_ACCOUNTS, {"account_id": account_id}
            )
            if account_data:
                total_assets = account_data["available_cash"] + total_market_value
                await mongo_manager.update_one(
                    C.SIM_ACCOUNTS,
                    {"account_id": account_id},
                    {"$set": {
                        "total_assets": total_assets,
                        "position_value": total_market_value,
                        "updated_at": now,
                    }}
                )
            
            settled_count += 1
        
        # ========= 非调仓日止损/止盈/超期检查 =========
        # 每日结算后检查是否需要强卖
        risk_sell_count = await self._check_and_execute_risk_sells(accounts)
        if risk_sell_count > 0:
            logger.info(f"每日结算: 执行 {risk_sell_count} 笔风控卖出(止损/止盈/超期)")
        
        logger.info(f"每日结算完成，共结算 {settled_count} 个账户")
    
    async def calculate_account_performance(self, account_id: str) -> Dict[str, Any]:
        """
        计算账户绩效指标
        
        返回: 总资产、总收益、收益率、持仓数、持仓市值等
        """
        account = await mongo_manager.find_one(
            C.SIM_ACCOUNTS, {"account_id": account_id}
        )
        if not account:
            return {}
        
        # 获取持仓
        positions = await mongo_manager.find_many(
            C.POSITIONS,
            {"account_id": account_id, "quantity": {"$gt": 0}},
        )
        
        # 计算当前持仓总市值
        total_market_value = 0
        total_cost = 0
        for pos in positions:
            # 【P0修复：avg_cost回退导致虚增盈亏——停牌股current_price为None时回退到avg_cost】
            # 这会让浮亏显示为0(成本价=市价)，应改为用最后有效价或标记为估值不可靠
            price = pos.get("current_price") or await self._get_latest_price(pos["ts_code"]) or pos.get("avg_cost", 0)
            mv = price * pos.get("quantity", 0)
            total_market_value += mv
            total_cost += pos.get("avg_cost", 0) * pos.get("quantity", 0)
        
        total_assets = account["available_cash"] + total_market_value
        initial_cash = account.get("initial_cash", total_assets)
        total_profit = total_assets - initial_cash
        total_profit_pct = (total_profit / initial_cash * 100) if initial_cash > 0 else 0
        unrealized_profit = total_market_value - total_cost
        
        return {
            "account_id": account_id,
            "initial_cash": initial_cash,
            "available_cash": account["available_cash"],
            "total_assets": total_assets,
            "position_value": total_market_value,
            "position_count": len(positions),
            "total_profit": total_profit,
            "total_profit_pct": total_profit_pct,
            "unrealized_profit": unrealized_profit,
            "return_rate": total_profit_pct,
        }


# 全局实例
sim_trading_engine = SimTradingEngine()
