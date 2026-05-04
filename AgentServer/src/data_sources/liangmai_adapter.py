"""
量脉金融数据源适配器

实现AsyncDataSourceAdapter接口，将量脉API接入数据源管理器。
核心优势: 实时行情免费、PE/PB/流通市值精确、涨停池数据丰富。

频率限制: 1分钟120次, IP上限2个
"""

from typing import Optional, List, Dict, Any
import asyncio
import logging

from src.data_sources.base import AsyncDataSourceAdapter


logger = logging.getLogger(__name__)


class LiangMaiAdapter(AsyncDataSourceAdapter):
    """量脉金融数据平台适配器
    
    优先用于:
    - 实时行情(免费，含PE/PB/流通市值)
    - 涨停池(比Tushare更丰富)
    - 日K线(含pre_close)
    - 资金流向(全新数据维度)
    """
    
    name = "liangmai"
    description = "量脉金融数据平台"
    priority = 5  # 高优先级(数字越小越优先)
    
    def __init__(self, token: str = None, **kwargs):
        super().__init__(**kwargs)
        self._token = token
        self._client = None
    
    @property
    def token(self):
        if self._token is None:
            import os
            self._token = os.environ.get("LIANGMAI_TOKEN", "ebacbad6d64444cd037ac5504b63f25d")
        return self._token
    
    async def initialize(self) -> None:
        """初始化量脉客户端"""
        try:
            from core.data_fetchers.liangmai_client import LiangMaiClient
            self._client = LiangMaiClient(token=self.token)
            await self._client.initialize()
            self._available = True
            self.logger.info(f"LiangMaiAdapter initialized, token=...{self.token[-6:]}")
        except Exception as e:
            self._available = False
            self.logger.warning(f"LiangMaiAdapter initialization failed: {e}")
    
    async def shutdown(self) -> None:
        """关闭客户端"""
        if self._client:
            await self._client.close()
            self._client = None
        self._available = False
    
    async def is_available(self) -> bool:
        """检查可用性"""
        if not self._client:
            return False
        try:
            # 简单ping测试
            stocks = await self._client.get_stock_list()
            return len(stocks) > 0
        except Exception:
            return False
    
    # ==================== 实时行情(核心优势) ====================
    
    async def get_realtime_quotes(
        self,
        ts_codes: Optional[List[str]] = None,
        batch_size: int = 20,
        timeout: float = 30.0,
    ) -> Dict[str, Dict[str, Any]]:
        """获取实时行情 - 量脉核心优势
        
        量脉stock_realtime接口返回:
        - p: 当前价, o: 开盘价, h: 最高价, l: 最低价
        - yc: 昨收价, pc: 涨跌幅, ud: 涨跌额
        - pe: 动态市盈率, sjl: 市净率
        - lt: 流通市值(元), sz: 总市值(元)
        - hs: 换手率, lb: 量比
        - cje: 成交额, v: 成交量(手)
        
        Args:
            ts_codes: 股票代码列表(6位,如["000001","600000"])
            batch_size: 量脉stock_realtime_multi支持≤20只/次
        
        Returns:
            {code6: RealtimeQuoteRecord}
        """
        if not self._client or not ts_codes:
            return {}
        
        result = {}
        
        # stock_realtime_multi支持≤20只/次
        for i in range(0, len(ts_codes), batch_size):
            batch = ts_codes[i:i + batch_size]
            
            try:
                # 使用stock_realtime_multi批量获取
                raw = await self._client.get_realtime_multi(batch)
                
                if raw and isinstance(raw, list):
                    for r in raw:
                        # 量脉返回的代码格式可能是000001或000001.SZ
                        dm = r.get("dm", r.get("ts_code", ""))
                        code6 = dm.split(".")[0] if "." in dm else dm
                        
                        # 标准化ts_code格式
                        if dm and "." not in dm:
                            if dm.startswith(("6", "9")): dm_full = f"{dm}.SH"
                            elif dm.startswith(("8", "4")): dm_full = f"{dm}.BJ"
                            else: dm_full = f"{dm}.SZ"
                        else:
                            dm_full = dm
                        
                        lt_raw = r.get("lt", 0) or 0
                        sz_raw = r.get("sz", 0) or 0
                        
                        result[code6] = {
                            "ts_code": dm_full,
                            "close": self._safe_float(r.get("p")),
                            "open": self._safe_float(r.get("o")),
                            "high": self._safe_float(r.get("h")),
                            "low": self._safe_float(r.get("l")),
                            "pre_close": self._safe_float(r.get("yc")),
                            "pct_chg": self._safe_float(r.get("pc")),
                            "change": self._safe_float(r.get("ud")),
                            "vol": self._safe_float(r.get("v")),
                            "amount": self._safe_float(r.get("cje")),
                            # 量脉额外字段(比Tushare更丰富)
                            "pe": self._safe_float(r.get("pe")),
                            "pb": self._safe_float(r.get("sjl")),
                            "circ_mv": round(lt_raw / 1e8, 4) if lt_raw else None,  # 元→亿元
                            "total_mv": round(sz_raw / 1e8, 4) if sz_raw else None,
                            "turnover_rate": self._safe_float(r.get("hs")),
                            "volume_ratio": self._safe_float(r.get("lb")),
                            "amplitude": self._safe_float(r.get("zf")),
                            "source": "liangmai",
                        }
                
            except Exception as e:
                self.logger.warning(f"LiangMai realtime batch failed: {e}")
            
            # 速率限制
            if i + batch_size < len(ts_codes):
                await asyncio.sleep(0.6)
        
        # 如果multi接口失败，逐只获取(更可靠但更慢)
        if not result and ts_codes:
            for code in ts_codes[:50]:  # 限制最多50只
                try:
                    record = await self._client.get_realtime_as_daily_basic(code)
                    if record:
                        code6 = code.split(".")[0] if "." in code else code
                        result[code6] = {
                            "ts_code": record.get("ts_code", code),
                            "close": record.get("close"),
                            "pre_close": record.get("pre_close"),
                            "pe": record.get("pe_ttm"),
                            "pb": record.get("pb"),
                            "circ_mv": record.get("circ_mv"),
                            "total_mv": record.get("total_mv"),
                            "turnover_rate": record.get("turnover_rate"),
                            "volume_ratio": record.get("volume_ratio"),
                            "pct_chg": None,  # 逐只接口不返回涨跌幅
                            "source": "liangmai",
                        }
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        
        return result
    
    async def get_realtime_index_quotes(self) -> Dict[str, Dict[str, Any]]:
        """获取指数实时行情"""
        if not self._client:
            return {}
        
        indices = {
            "000001": "上证指数",
            "399001": "深证成指",
            "399006": "创业板指",
        }
        
        result = {}
        for code, name in indices.items():
            try:
                raw = await self._client.get_index_kline(code, klt="d", lt=1)
                if raw:
                    bar = raw[0]
                    code6 = code
                    result[code6] = {
                        "ts_code": f"{code}.SH" if code.startswith("000") else f"{code}.SZ",
                        "name": name,
                        "close": bar.get("c"),
                        "open": bar.get("o"),
                        "high": bar.get("h"),
                        "low": bar.get("l"),
                        "pre_close": bar.get("pc"),
                        "vol": bar.get("v"),
                        "amount": bar.get("a"),
                        "source": "liangmai",
                    }
            except Exception as e:
                self.logger.warning(f"LiangMai index {code} failed: {e}")
            await asyncio.sleep(0.5)
        
        return result
    
    # ==================== K线数据 ====================
    
    async def get_daily(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取日K线"""
        if not self._client:
            return []
        
        code6 = ts_code.split(".")[0] if "." in ts_code else ts_code
        
        try:
            params = {"ts_code": code6, "klt": "d", "fqt": "f"}
            if start_date:
                params["beg"] = start_date.replace("-", "")
            if end_date:
                params["end"] = end_date.replace("-", "")
            
            api = "quote_bars_history" if (start_date or end_date) else "quote_bars_latest"
            raw = await self._client.request(api, **params)
            
            result = []
            for bar in raw:
                date_str = bar.get("t", "")
                trade_date = date_str[:10].replace("-", "") if date_str else ""
                
                result.append({
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "pre_close": bar.get("pc"),
                    "vol": bar.get("v"),
                    "amount": bar.get("a"),
                    "suspend_flag": bar.get("sf", 0),
                    "source": "liangmai",
                })
            
            return result
            
        except Exception as e:
            self.logger.warning(f"LiangMai daily failed for {ts_code}: {e}")
            return []
    
    # ==================== 涨停池 ====================
    
    async def get_limit_list(
        self,
        trade_date: str,
        limit_type: str = "up",
    ) -> List[Dict[str, Any]]:
        """获取涨跌停股池
        
        量脉涨停池比Tushare limit_list更丰富:
        - 封板时间(first_limit_time/last_limit_time)
        - 炸板次数(broken_times)
        - 连板数(limit_times)
        - 封板资金(limit_amount)
        """
        if not self._client:
            return []
        
        # 转换日期格式: 20260430 → 2026-04-30
        if len(trade_date) == 8:
            date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        else:
            date_display = trade_date
        
        try:
            if limit_type == "up":
                return await self._client.get_pool_limit_up_as_limit_list(date_display)
            elif limit_type == "down":
                raw = await self._client.get_pool_limit_down(date_display)
                # 转换格式...
                return raw if raw else []
            elif limit_type == "broken":
                return await self._client.get_pool_broken_board(date_display) or []
        except Exception as e:
            self.logger.warning(f"LiangMai limit list failed for {date_display}: {e}")
            return []
    
    # ==================== 每日指标 ====================
    
    async def get_daily_basic(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取每日指标(PE/PB/换手率/市值等)
        
        量脉实时行情接口可替代daily_basic的部分功能。
        """
        if not self._client or not ts_code:
            return []
        
        try:
            record = await self._client.get_realtime_as_daily_basic(ts_code)
            if record:
                if trade_date:
                    record["trade_date"] = trade_date
                record["source"] = "liangmai"
                return [record]
        except Exception as e:
            self.logger.warning(f"LiangMai daily_basic failed for {ts_code}: {e}")
        
        return []
    
    # ==================== 资金流向(量脉独有) ====================
    
    async def get_capital_flow(
        self,
        ts_code: str,
        lt: int = None,
        beg: str = None,
        end: str = None,
    ) -> List[Dict[str, Any]]:
        """获取资金流向数据(主力/大单/中单/小单净流入)"""
        if not self._client:
            return []
        
        code6 = ts_code.split(".")[0] if "." in ts_code else ts_code
        
        try:
            return await self._client.get_capital_flow(code6, lt=lt, beg=beg, end=end)
        except Exception as e:
            self.logger.warning(f"LiangMai capital_flow failed for {ts_code}: {e}")
            return []
    
    # ==================== 板块/概念 ====================
    
    async def get_stock_sectors(self, ts_code: str) -> List[Dict[str, Any]]:
        """获取个股所属板块/概念"""
        if not self._client:
            return []
        
        code6 = ts_code.split(".")[0] if "." in ts_code else ts_code
        
        try:
            return await self._client.get_stock_sectors(code6)
        except Exception as e:
            self.logger.warning(f"LiangMai stock_sectors failed for {ts_code}: {e}")
            return []
    
    # ==================== 工具方法 ====================
    
    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """安全转float"""
        if val is None:
            return None
        try:
            f = float(val)
            return f if f == f else None  # NaN检查
        except (ValueError, TypeError):
            return None
