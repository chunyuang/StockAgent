"""
价格计算模块（拆分Phase 4产物）

⚠️ 注意：本模块已从portfolio_backtest.py拆分出来，但尚未被主引擎引用。
   portfolio_backtest.py仍使用内联的_get_prices/_get_buy_price_for_stock等方法。
   待Phase 6-8完成拆分后，本模块将被正式集成。
   当前状态：独立可用，但未被调用。
"""

from typing import Dict, List, Set, Tuple
from core.managers import mongo_manager
from core.constants import C


class PriceCalculator:
    """价格计算器"""
    
    # 涨跌停限制映射
    LIMIT_PCT_MAP = {
        "SH_main": 0.10,  # 上海主板10%
        "SZ_main": 0.10,  # 深圳主板10%
        "SH_gem": 0.20,   # 科创板20%
        "SZ_gem": 0.20,   # 创业板20%
        "BJ": 0.30,       # 北交所30%
    }
    
    def __init__(self, log_func=None):
        self.log = log_func
        self._stock_name_cache = {}
        self._last_valid_price = {}
    
    async def get_prices(self, ts_codes: Set[str], trade_date) -> Dict[str, Dict[str, float]]:
        """批量获取股票价格数据
        
        Args:
            ts_codes: 股票代码集合
            trade_date: 交易日期
            
        Returns:
            Dict[str, Dict[str, float]]: {ts_code: {open, high, low, close, pre_close}}
        """
        if not ts_codes:
            return {}
        
        td = int(trade_date)
        prices = {}
        
        # 批量查询
        cursor = mongo_manager.find_many(
            C.STOCK_DAILY,
            {
                "trade_date": td,
                "ts_code": {"$in": list(ts_codes)}
            },
            {"ts_code": 1, "open": 1, "high": 1, "low": 1, "close": 1, "pre_close": 1}
        )
        
        docs = await cursor
        
        for doc in docs:
            code = doc.get("ts_code")
            if code:
                prices[code] = {
                    "open": doc.get("open", 0),
                    "high": doc.get("high", 0),
                    "low": doc.get("low", 0),
                    "close": doc.get("close", 0),
                    "pre_close": doc.get("pre_close", 0)
                }
                
                # 更新最后有效价格
                if prices[code]["close"] > 0:
                    self._last_valid_price[code] = prices[code]["close"]
        
        return prices
    
    def get_limit_pct(self, ts_code: str) -> float:
        """获取涨跌停限制百分比
        
        Args:
            ts_code: 股票代码
            
        Returns:
            float: 涨跌停限制（如0.10表示10%）
        """
        if ts_code.startswith('688'):
            return self.LIMIT_PCT_MAP["SH_gem"]
        elif ts_code.startswith('30'):
            return self.LIMIT_PCT_MAP["SZ_gem"]
        elif ts_code.startswith('8') or ts_code.startswith('4'):
            return self.LIMIT_PCT_MAP["BJ"]
        else:
            return self.LIMIT_PCT_MAP["SH_main"]
    
    def get_limit_up_price(self, ts_code: str, open_price: float, close_price: float,
                           high_price: float, low_price: float, pre_close: float) -> float:
        """计算涨停价买入价格
        
        Args:
            ts_code: 股票代码
            open_price: 开盘价
            close_price: 收盘价
            high_price: 最高价
            low_price: 最低价
            pre_close: 前收盘价
            
        Returns:
            float: 涨停价买入价格
        """
        if pre_close <= 0:
            return close_price
        
        limit_pct = self.get_limit_pct(ts_code)
        limit_price = pre_close * (1 + limit_pct)
        
        # 一字板：open=close=high=low
        if abs(open_price - close_price) < 0.01 and \
           abs(close_price - high_price) < 0.01 and \
           abs(high_price - low_price) < 0.01:
            return limit_price  # 一字板用涨停价
        
        # 非一字板：用收盘价（接近涨停价）
        return close_price
    
    def get_buy_price_for_stock(self, code: str, open_price: float, close_price: float,
                                 high_price: float, low_price: float, pre_close: float,
                                 stock_to_strategy: dict, strategy_params: dict) -> float:
        """计算股票买入价（多策略选同股时取最低价）
        
        Args:
            code: 股票代码
            open_price: 开盘价
            close_price: 收盘价
            high_price: 最高价
            low_price: 最低价
            pre_close: 前收盘价
            stock_to_strategy: 股票到策略的映射
            strategy_params: 策略参数
            
        Returns:
            float: 买入价格
        """
        sinfo = stock_to_strategy.get(code, '')
        strategies = sinfo if isinstance(sinfo, list) else [sinfo]
        
        prices = []
        for sname in strategies:
            if sname == '半路追涨':
                min_rise = strategy_params.get('半路追涨', {}).get('min_rise_pct', 0.02)
                signal_fraction = 0.6
                p = open_price * (1 + min_rise * signal_fraction) if open_price > 0 else 0
                p = max(p, open_price) if open_price > 0 else 0
            
            elif sname in ('首板打板', '涨停开板'):
                p = self.get_limit_up_price(code, open_price, close_price, high_price, low_price, pre_close)
            
            elif sname == '龙头低吸':
                if low_price > 0 and high_price > low_price:
                    p = low_price + (high_price - low_price) * 0.25
                elif low_price > 0:
                    p = low_price * 1.01
                else:
                    p = open_price * 0.98
            
            elif sname == '跌停翘板':
                p = low_price * 1.005 if low_price > 0 else open_price * 0.92
            
            else:
                p = open_price
            
            if p > 0:
                prices.append(p)
        
        if not prices:
            return open_price
        
        return min(prices)
    
    async def get_stock_names(self, ts_codes: List[str]) -> Dict[str, str]:
        """批量获取股票名称
        
        Args:
            ts_codes: 股票代码列表
            
        Returns:
            Dict[str, str]: {ts_code: name}
        """
        result = {}
        need_query = []
        
        def _standardize_code(code_str: str) -> str:
            """标准化股票代码为数据库格式"""
            code_str = str(code_str).strip()
            if code_str.endswith('.SH') or code_str.endswith('.SZ') or code_str.endswith('.BJ'):
                return code_str
            if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                return f"{code_str}.SH"
            elif code_str.startswith('8') or code_str.startswith('4'):
                return f"{code_str}.BJ"
            else:
                return f"{code_str}.SZ"
        
        for ts_code in ts_codes:
            standard_code = _standardize_code(ts_code)
            
            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                need_query.append(standard_code)
        
        if need_query:
            docs = await mongo_manager.find_many(
                C.STOCK_BASIC,
                {"ts_code": {"$in": need_query}},
                {"ts_code": 1, "name": 1}
            )
            
            for doc in docs:
                standard_code = doc["ts_code"]
                name = doc.get("name", standard_code)
                self._stock_name_cache[standard_code] = name
        
        for ts_code in ts_codes:
            standard_code = _standardize_code(ts_code)
            
            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                if '.' in ts_code:
                    result[ts_code] = ts_code.split('.')[0]
                else:
                    result[ts_code] = ts_code
        
        return result
