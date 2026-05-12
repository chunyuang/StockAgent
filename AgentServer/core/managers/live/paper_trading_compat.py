"""
模拟盘交易兼容层

将 real_trading/paper_trading.py 的 PaperTradingEngine 
桥接到 AgentServer/core/managers/sim_trading_engine.py

两个引擎功能重叠:
- SimTradingEngine: MongoDB存储, 已整合进Web API, 支持下单/结算/绩效
- PaperTradingEngine: JSON文件存储, 有风控检查, 有持仓管理

整合策略: PaperTradingEngine → SimTradingEngine 的代理
保留 PaperTradingEngine 接口签名, 内部调用 SimTradingEngine
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from core.managers.sim_trading_engine import SimTradingEngine

logger = logging.getLogger("live.paper_trading_compat")


class PaperTradingEngine:
    """模拟盘引擎 — 代理到SimTradingEngine"""
    
    def __init__(self, account_id: str = "default", initial_cash: float = 1_000_000):
        self.engine = SimTradingEngine()
        self.account_id = account_id
        self.initial_cash = initial_cash
    
    async def buy(self, ts_code: str, stock_name: str, quantity: int,
                  price: float = None, strategy: str = None, reason: str = None) -> Dict:
        """买入"""
        ok, msg, data = await self.engine.place_order(
            account_id=self.account_id,
            ts_code=ts_code, stock_name=stock_name,
            direction='buy', quantity=quantity, price=price,
            strategy=strategy, reason=reason,
        )
        return {"success": ok, "message": msg, "data": data}
    
    async def sell(self, ts_code: str, stock_name: str, quantity: int,
                   price: float = None, strategy: str = None, reason: str = None) -> Dict:
        """卖出"""
        ok, msg, data = await self.engine.place_order(
            account_id=self.account_id,
            ts_code=ts_code, stock_name=stock_name,
            direction='sell', quantity=quantity, price=price,
            strategy=strategy, reason=reason,
        )
        return {"success": ok, "message": msg, "data": data}
    
    async def get_positions(self) -> List[Dict]:
        """获取持仓"""
        from core.managers import mongo_manager
        db = mongo_manager.get_db()
        return list(db.sim_positions.find({"account_id": self.account_id, "quantity": {"$gt": 0}}))
    
    async def get_account_info(self) -> Dict:
        """获取账户信息"""
        from core.managers import mongo_manager
        db = mongo_manager.get_db()
        acct = db.sim_accounts.find_one({"account_id": self.account_id})
        return acct or {"account_id": self.account_id, "cash": self.initial_cash}
    
    async def daily_settlement(self, trade_date: str = None) -> Dict:
        """每日结算"""
        return await self.engine.daily_settlement(trade_date)


class PaperAccount:
    """模拟账户 — 兼容旧接口"""
    
    def __init__(self, account_id: str, name: str = "", initial_cash: float = 1_000_000):
        self.account_id = account_id
        self.name = name or account_id
        self.initial_cash = initial_cash
        self.engine = PaperTradingEngine(account_id, initial_cash)
