"""
交易信号生成器

负责每日盘前运行所有策略，生成交易信号并存储到数据库。
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


from core.managers import mongo_manager
from core.constants import C

try:
    from backtest_module.strategies import (
        HalfwayChaseStrategy,
        FirstLimitUpStrategy,
        LimitUpOpenStrategy,
        LeaderBuyDipStrategy,
        LimitDownQiaoStrategy,
    )
    _HAS_STRATEGIES = True
except ImportError:
    _HAS_STRATEGIES = False
    HalfwayChaseStrategy = None
    FirstLimitUpStrategy = None
    LimitUpOpenStrategy = None
    LeaderBuyDipStrategy = None
    LimitDownQiaoStrategy = None
from core.utils.date_utils import get_previous_trade_date

logger = logging.getLogger("signal_generator")

# 策略映射
STRATEGY_MAP = {
    "halfway_chase": HalfwayChaseStrategy,
    "first_limit_up": FirstLimitUpStrategy,
    "limit_up_open": LimitUpOpenStrategy,
    "leader_buy_dip": LeaderBuyDipStrategy,
    "limit_down_qiao": LimitDownQiaoStrategy,
}

STRATEGY_NAME_MAP = {
    "halfway_chase": "半路追涨",
    "first_limit_up": "首板打板",
    "limit_up_open": "涨停开板",
    "leader_buy_dip": "龙头低吸",
    "limit_down_qiao": "跌停翘板",
}

class SignalGenerator:
    """交易信号生成器"""
    
    def __init__(self):
        self.strategies = {}
        if not _HAS_STRATEGIES:
            logger.warning("backtest_module.strategies不可用，信号生成器将返回空信号")
            return
        for strategy_id, strategy_cls in STRATEGY_MAP.items():
            if strategy_cls is not None:
                self.strategies[strategy_id] = strategy_cls()
    
    async def generate_daily_signals(self, trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        生成指定交易日的所有策略信号
        
        Args:
            trade_date: 交易日期，格式YYYYMMDD，默认取最近一个交易日
        
        Returns:
            生成的信号列表
        """
        if not trade_date:
            trade_date = get_previous_trade_date()
        
        logger.info(f"开始生成 {trade_date} 交易信号...")
        
        all_signals = []
        
        # 加载当日行情数据
        # TODO: 加载当日/最近行情数据，预处理
        market_data = await self._load_market_data(trade_date)
        
        # 运行所有策略
        for strategy_id, strategy in self.strategies.items():
            try:
                logger.info(f"运行策略: {strategy_id} ({STRATEGY_NAME_MAP[strategy_id]})")
                
                # 运行策略，获取信号
                signals = await strategy.generate_signals(trade_date, market_data)
                
                for signal in signals:
                    signal_id = f"sig_{uuid.uuid4().hex[:12]}"
                    now = datetime.now(timezone.utc)
                    
                    # 计算过期时间：当日收盘后过期
                    expired_at = datetime.strptime(f"{trade_date} 15:00:00", "%Y%m%d %H:%M:%S")
                    
                    signal_doc = {
                        "signal_id": signal_id,
                        "ts_code": signal["ts_code"],
                        "stock_name": signal.get("stock_name", ""),
                        "strategy": strategy_id,
                        "strategy_name": STRATEGY_NAME_MAP[strategy_id],
                        "signal_type": signal["signal_type"],  # buy/sell/hold
                        "price": signal["price"],
                        "suggest_quantity": signal.get("suggest_quantity", 100),
                        "confidence": signal.get("confidence", 0.7),
                        "reason": signal.get("reason", ""),
                        "generated_at": now,
                        "expired_at": expired_at,
                        "status": "pending",
                        "created_at": now,
                        "updated_at": now
                    }
                    
                    all_signals.append(signal_doc)
                    
            except Exception as e:
                logger.exception(f"策略 {strategy_id} 运行失败: {e}")
                continue
        
        # 批量保存信号到数据库
        if all_signals:
            await mongo_manager.insert_many(C.TRADING_SIGNALS, all_signals)
            logger.info(f"成功生成 {len(all_signals)} 个交易信号，已存入数据库")
        
        return all_signals
    
    async def _load_market_data(self, trade_date: str) -> Dict[str, Any]:
        """加载指定交易日的市场数据"""
        # TODO: 加载行情数据、龙虎榜、北向资金等
        # 1. 加载当日日线数据
        daily_data = await mongo_manager.find_many(
            C.STOCK_DAILY,
            {"trade_date": int(trade_date)}
        )
        
        # 2. 加载基础信息
        basic_info = await mongo_manager.find_many(
            C.STOCK_BASIC,
            {}
        )
        
        # 3. 加载涨跌停数据
        limit_data = await mongo_manager.find_many(
            C.LIMIT_LIST,
            {"trade_date": int(trade_date)}
        )
        
        # 转换为字典方便查询
        daily_dict = {d["ts_code"]: d for d in daily_data}
        basic_dict = {b["ts_code"]: b for b in basic_info}
        limit_dict = {l["ts_code"]: l for l in limit_data}
        
        return {
            "trade_date": trade_date,
            "daily": daily_dict,
            "basic": basic_dict,
            "limit": limit_dict
        }
    
    async def get_latest_signals(self, limit: int = 50, only_pending: bool = False) -> List[Dict[str, Any]]:
        """获取最新交易信号"""
        query = {}
        if only_pending:
            query["status"] = "pending"
        
        signals = await mongo_manager.find_many(
            C.TRADING_SIGNALS,
            query,
            sort=[("generated_at", -1)],
            limit=limit
        )
        
        return signals


# 全局实例
signal_generator = SignalGenerator()
