"""
东方财富实时行情适配器

数据源: 东方财富push2 API (https://push2.eastmoney.com/api/qt/clist/get)
特点: 
  - 全市场5400+只股票一次请求(分页), 3秒完成
  - 免费, 无限流, 无IP限制
  - 返回: 价格/涨跌幅/换手率/量比/PE/PB/流通市值等

用途:
  - 半路追涨选股(全市场量比>2+换手>3%+涨3-7%)
  - 持仓止损止盈(全持仓实时价格)
  - 替代必盈逐只行情(0次必盈额度消耗)

字段映射 (东方财富f编号 → 标准字段):
  f2=最新价  f3=涨跌幅  f4=涨跌额  f5=成交量(手)  f6=成交额
  f7=振幅    f8=换手率  f9=PE(动态) f10=量比
  f12=代码   f14=名称   f15=最高   f16=最低       f17=开盘  f18=昨收
  f20=总市值 f21=流通市值 f23=PB
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from .base import (
    AsyncDataSourceAdapter,
    DataSourceCapability,
    DataSourceType,
    RealtimeQuoteRecord,
)

logger = logging.getLogger(__name__)


class EastmoneyAdapter(AsyncDataSourceAdapter):
    """东方财富实时行情适配器 — 全市场快照, 无限流"""

    BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    DELAY_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"  # v2.9.105: push2不可用时的延迟接口(15s延迟, 有量比)

    # 全市场字段: 价格+涨跌+换手+量比+PE+PB+市值
    FIELDS = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23"

    # 市场过滤: 沪深A+北交所
    FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"

    def __init__(self, **kwargs):
        super().__init__()
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict] = {}       # ts_code → 行情数据
        self._cache_time: float = 0              # 缓存时间戳
        self._cache_ttl: int = 5                 # 缓存TTL(秒), 盘中5秒刷新
        self._total_stocks: int = 0              # 总股票数
        self._last_fetch_time: float = 0
        self._fetch_count: int = 0

    # === 必须实现的抽象方法 ===

    def name(self) -> str:
        return "东方财富"

    def source_type(self) -> DataSourceType:
        return DataSourceType.REALTIME

    @property
    def capability(self) -> DataSourceCapability:
        return DataSourceCapability(
            realtime_quotes=True,
            daily_basic=True,          # PE/PB/市值
            limit_data=False,          # 涨停池用必盈
        )

    def _get_default_priority(self) -> int:
        return 5   # 低于必盈(10), 作为补充数据源

    async def initialize(self) -> bool:
        """初始化: 创建HTTP session"""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5, connect=3),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
        # 预热: 拉一次全市场数据验证连通性
        try:
            data = await self._fetch_all_stocks()
            if data:
                logger.info(f"[EASTMONEY] 初始化成功, {len(data)}只股票")
                return True
            else:
                logger.warning("[EASTMONEY] 初始化: 未获取到数据, 但仍标记可用")
                return True  # 仍标记可用, 后续请求可能成功
        except Exception as e:
            logger.warning(f"[EASTMONEY] 初始化预热失败({e}), 仍标记可用")
            return True

    async def is_available(self) -> bool:
        return self._session is not None

    async def shutdown(self):
        if self._session:
            await self._session.close()
            self._session = None

    # === 核心API: 全市场快照 ===

    async def _fetch_all_stocks(self) -> Dict[str, Dict]:
        """拉取全市场5400+只股票的实时行情
        
        优先东方财富push2(全市场一次, 3秒)
        回退腾讯行情(需分批, 每批800只)
        """
        if not self._session:
            return {}

        # === 方案1: 东方财富push2 ===
        try:
            data = await self._fetch_eastmoney_push2()
            if data:
                return data
        except Exception as e:
            logger.warning(f"[EASTMONEY] push2失败({e}), 尝试腾讯回退...")

        # === 方案2: 腾讯行情(回退) ===
        try:
            data = await self._fetch_tencent_batch()
            if data:
                return data
        except Exception as e:
            logger.warning(f"[EASTMONEY] 腾讯也失败({e})")

        return {}

    async def _fetch_eastmoney_push2(self) -> Dict[str, Dict]:
        """东方财富push2: 全市场5400只, 约3秒
        
        v2.9.105: push2不可用时回退到push2delay(延迟15s, 但含量比)
        """
        # 先试 push2 实时接口
        try:
            data = await self._fetch_from_url(self.BASE_URL)
            if data:
                return data
        except Exception as e:
            logger.debug(f"[EASTMONEY] push2失败({e}), 尝试push2delay...")
        
        # push2 失败 → 试 push2delay (延迟接口, 有量比)
        try:
            data = await self._fetch_from_url(self.DELAY_URL)
            if data:
                logger.info(f"[EASTMONEY] push2delay回退: {len(data)}只(延迟15s, 含量比)")
                return data
        except Exception as e:
            logger.debug(f"[EASTMONEY] push2delay也失败({e})")
        
        raise ConnectionError("push2和push2delay均不可用")

    async def _fetch_from_url(self, url: str) -> Dict[str, Dict]:
        """从指定URL拉取全市场行情

        v2.9.126: 59页串行 -> 分批并行(10页/批), 3.5s -> 0.1s
        """
        async def _fetch_page(pn: int) -> list:
            params = {
                "pn": pn, "pz": 200, "po": 1, "np": 1,
                "fltt": 2, "invt": 2, "fid": "f3",
                "fs": self.FS,
                "fields": self.FIELDS,
            }
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise ConnectionError(f"HTTP {resp.status}")
                d = await resp.json(content_type=None)
                return d.get("data", {}).get("diff", [])

        all_data = {}
        # 分批并行: 10页/批, 6批
        for batch_start in range(1, 60, 10):
            pages = range(batch_start, min(batch_start + 10, 60))
            results = await asyncio.gather(*[_fetch_page(pn) for pn in pages], return_exceptions=True)
            for diff in results:
                if isinstance(diff, Exception):
                    continue
                if not diff:
                    continue
                for item in diff:
                    ts_code = self._code_to_tscode(item.get("f12", ""))
                    if ts_code:
                        all_data[ts_code] = self._parse_em_item(item)

        if all_data:
            self._total_stocks = len(all_data)
            self._cache = all_data
            self._cache_time = time.time()
            self._last_fetch_time = time.time()
            self._fetch_count += 1
            return all_data
        raise ConnectionError(f"{url}返回空数据")

    async def _fetch_tencent_batch(self) -> Dict[str, Dict]:
        """腾讯行情: 分批拉取(每批最多800只), 回退方案
        
        缺点: 没有量比(volume_ratio)和PE, 需要从daily_basic补充
        """
        # 先从MongoDB获取股票代码列表
        try:
            from pymongo import MongoClient
            client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
            db = client["stock_agent"]
            codes = list(db["stock_daily_ak_full"].distinct("ts_code", {"trade_date": {"$gte": 20260501}}))
            if not codes:
                codes = list(db["daily_basic"].distinct("ts_code", {"trade_date": {"$gte": 20260501}}))
        except Exception:
            # 回退: 用硬编码的代码范围(沪深A)
            codes = []
            # 沪市
            for i in range(600000, 605000):
                codes.append(f"{i}.SH")
            # 深市
            for i in range(1, 3000):
                codes.append(f"{str(i).zfill(6)}.SZ")

        if not codes:
            return {}

        all_data = {}
        # 批量拉取: 每批800只
        batch_size = 800
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            # ts_code → 腾讯格式 (000001.SZ → sz000001)
            qq_codes = []
            for ts_code in batch:
                pure, suffix = ts_code.split(".") if "." in ts_code else (ts_code, "SZ")
                prefix = "sh" if suffix == "SH" else "sz"
                qq_codes.append(f"{prefix}{pure}")
            
            url = f"https://qt.gtimg.cn/q={','.join(qq_codes)}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    continue
                text = await resp.text()
                
            # 解析
            for line in text.strip().split(';'):
                if not line.strip():
                    continue
                parts = line.split('="')
                if len(parts) < 2:
                    continue
                raw_code = parts[0].replace('v_', '')
                data_str = parts[1].rstrip('"')
                if not data_str:
                    continue
                fields = data_str.split('~')
                if len(fields) < 40:
                    continue
                
                # 转回ts_code
                pure_code = fields[2] if len(fields) > 2 else raw_code[2:]
                ts_code = self._code_to_tscode(pure_code)
                if not ts_code:
                    continue
                
                try:
                    all_data[ts_code] = {
                        "price": float(fields[3]) if fields[3] else None,
                        "pct_chg": float(fields[32]) if fields[32] else None,
                        "pre_close": float(fields[4]) if fields[4] else None,
                        "open": float(fields[5]) if fields[5] else None,
                        "high": float(fields[33]) if fields[33] else None,
                        "low": float(fields[34]) if fields[34] else None,
                        "vol": float(fields[6]) * 100 if fields[6] else None,  # 手→股
                        "amount": float(fields[37]) * 10000 if fields[37] else None,  # 万→元
                        "turnover_rate": float(fields[38]) if fields[38] else None,
                        "amplitude": float(fields[43]) if len(fields) > 43 and fields[43] else None,
                        "name": fields[1] if len(fields) > 1 else "",
                        "volume_ratio": None,  # 腾讯无此字段
                        "pe": None,           # 腾讯无此字段
                        "pb": None,           # 腾讯无此字段
                        "float_mv": None,
                    }
                except (ValueError, IndexError):
                    continue
            
            await asyncio.sleep(0.1)

        if all_data:
            # 从MongoDB daily_basic补充PE/PB/量比(腾讯回退时缺这些)
            try:
                from pymongo import MongoClient
                client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
                db = client["stock_agent"]
                latest = db["daily_basic"].find_one(sort=[("trade_date", -1)])
                if latest:
                    latest_date = latest["trade_date"]
                    supplemented = 0
                    for doc in db["daily_basic"].find({"trade_date": latest_date},
                            {"ts_code": 1, "pe": 1, "pb": 1, "volume_ratio": 1, "turnover_rate": 1, "circ_mv": 1}):
                        ts_code = doc.get("ts_code")
                        if ts_code and ts_code in all_data:
                            item = all_data[ts_code]
                            if item.get("volume_ratio") is None and doc.get("volume_ratio"):
                                item["volume_ratio"] = doc["volume_ratio"]
                                supplemented += 1
                            if item.get("pe") is None and doc.get("pe"):
                                item["pe"] = doc["pe"]
                            if item.get("pb") is None and doc.get("pb"):
                                item["pb"] = doc["pb"]
                            if item.get("float_mv") is None and doc.get("circ_mv"):
                                item["float_mv"] = doc["circ_mv"] * 10000  # 万元→元(与push2 f21统一)
                    logger.info(f"[EASTMONEY] MongoDB补全: {supplemented}只PE/PB/量比")
            except Exception as e:
                logger.debug(f"[EASTMONEY] MongoDB补全失败(非致命): {e}")

            self._total_stocks = len(all_data)
            self._cache = all_data
            self._cache_time = time.time()
            self._last_fetch_time = time.time()
            self._fetch_count += 1
            logger.info(f"[EASTMONEY] 腾讯回退: {len(all_data)}只")
            return all_data
        return {}

    def _code_to_tscode(self, code_str: str) -> str:
        """纯数字代码 → ts_code (如 000001 → 000001.SZ)"""
        code = str(code_str).zfill(6)
        if code.startswith(('6', '9')):
            return f"{code}.SH"
        elif code.startswith(('8', '4')):
            return f"{code}.BJ"
        else:
            return f"{code}.SZ"

    def _tscode_to_code(self, ts_code: str) -> str:
        """ts_code → 纯数字 (如 000001.SZ → 000001)"""
        return ts_code.split(".")[0] if "." in ts_code else ts_code

    def _parse_em_item(self, item: Dict) -> Dict:
        """解析东方财富单条数据 → 标准格式"""
        return {
            "price": self._safe_float(item.get("f2")),
            "pct_chg": self._safe_float(item.get("f3")),
            "chg": self._safe_float(item.get("f4")),
            "vol": self._safe_float(item.get("f5"), 0) * 100 if self._safe_float(item.get("f5")) else None,  # 手→股
            "amount": self._safe_float(item.get("f6")),
            "amplitude": self._safe_float(item.get("f7")),
            "turnover_rate": self._safe_float(item.get("f8")),
            "pe": self._safe_float(item.get("f9")),
            "volume_ratio": self._safe_float(item.get("f10")),
            "code": str(item.get("f12", "")),
            "name": str(item.get("f14", "")),
            "high": self._safe_float(item.get("f15")),
            "low": self._safe_float(item.get("f16")),
            "open": self._safe_float(item.get("f17")),
            "pre_close": self._safe_float(item.get("f18")),
            "total_mv": self._safe_float(item.get("f20")),
            "float_mv": self._safe_float(item.get("f21")),
            "pb": self._safe_float(item.get("f23")),
        }

    @staticmethod
    def _safe_float(v, default=None) -> Optional[float]:
        if v is None or v == '-' or v == '':
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    # === 缓存 + 自动刷新 ===

    async def get_all_realtime(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """获取全市场实时行情 (带缓存, 默认5秒TTL)
        
        周末/非交易日: 优先用缓存, force_refresh时尝试刷新(失败不阻塞)
        """
        now = time.time()
        cache_age = now - self._cache_time
        
        # 周末: 优先用缓存, 不强制拉取(避免阻塞)
        from datetime import datetime as _dt
        if _dt.now().weekday() >= 5:
            if self._cache:
                return self._cache
            # 周末且无缓存: 尝试拉取一次(有15s超时)
            if force_refresh or not self._cache:
                try:
                    data = await asyncio.wait_for(self._fetch_all_stocks(), timeout=20)
                    if data:
                        return data
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"[EASTMONEY] 周末拉取超时/失败({e}), 返回空缓存")
            return self._cache or {}
        
        if force_refresh or cache_age > self._cache_ttl or not self._cache:
            data = await self._fetch_all_stocks()
            if data:
                return data
            # 刷新失败, 用旧缓存
            if self._cache:
                logger.warning(f"[EASTMONEY] 刷新失败, 使用{cache_age:.0f}秒前的缓存")
                return self._cache
            return {}
        
        return self._cache

    async def get_realtime_quote(self, ts_code: str) -> Optional[RealtimeQuoteRecord]:
        """获取单只股票实时行情 (从全市场缓存中提取, 0额外API)"""
        all_data = await self.get_all_realtime()
        item = all_data.get(ts_code)
        if not item:
            return None
        return RealtimeQuoteRecord(
            ts_code=ts_code,
            close=item.get("price"),
            open=item.get("open"),
            high=item.get("high"),
            low=item.get("low"),
            pre_close=item.get("pre_close"),
            pct_chg=item.get("pct_chg"),
            vol=item.get("vol"),
            amount=item.get("amount"),
        )

    async def get_realtime_quotes_batch(self, ts_codes: List[str]) -> Dict[str, RealtimeQuoteRecord]:
        """批量获取实时行情 (从全市场缓存提取, 0额外API)"""
        all_data = await self.get_all_realtime()
        result = {}
        for ts_code in ts_codes:
            item = all_data.get(ts_code)
            if item:
                result[ts_code] = RealtimeQuoteRecord(
                    ts_code=ts_code,
                    close=item.get("price"),
                    open=item.get("open"),
                    high=item.get("high"),
                    low=item.get("low"),
                    pre_close=item.get("pre_close"),
                    pct_chg=item.get("pct_chg"),
                    vol=item.get("vol"),
                    amount=item.get("amount"),
                )
        return result

    # === 半路追涨专用: 筛选候选股 ===

    async def screen_halfway_chase(
        self,
        pct_min: float = 3.0,
        pct_max: float = 7.0,
        volume_ratio_min: float = 2.0,
        turnover_min: float = 3.0,
        exclude_codes: set = None,
    ) -> List[Dict]:
        """半路追涨选股: 从全市场中筛选涨3-7%+量比>2+换手>3%的股票
        
        如果数据源无量比(腾讯回退), 则只按涨幅+换手率筛选
        
        Returns:
            List[Dict] 候选股列表, 按量比降序(有量比时)或涨幅降序
        """
        all_data = await self.get_all_realtime()
        exclude_codes = exclude_codes or set()
        has_volume_ratio = any(item.get("volume_ratio") is not None for item in all_data.values())
        
        candidates = []
        for ts_code, item in all_data.items():
            if ts_code in exclude_codes:
                continue
            pct = item.get("pct_chg")
            if pct is None:
                continue
            if not (pct_min <= pct <= pct_max):
                continue
            # 量比(有数据时才筛选)
            vr = item.get("volume_ratio")
            if has_volume_ratio and (vr is None or vr < volume_ratio_min):
                continue
            # 换手率
            tr = item.get("turnover_rate")
            if tr is None or tr < turnover_min:
                continue
            # 排除北交所
            if ts_code.endswith(".BJ"):
                continue
            
            candidates.append({
                "ts_code": ts_code,
                "name": item.get("name", ""),
                "price": item.get("price"),
                "pct_chg": pct,
                "volume_ratio": vr,
                "turnover_rate": tr,
                "pe": item.get("pe"),
                "pb": item.get("pb"),
                "float_mv": item.get("float_mv"),
                "amplitude": item.get("amplitude"),
            })
        
        # 排序
        if has_volume_ratio:
            candidates.sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)
        else:
            candidates.sort(key=lambda x: x.get("pct_chg", 0), reverse=True)
        logger.info(f"[EASTMONEY] 半路追涨候选: {len(candidates)}只 (全市场{len(all_data)}只, 量比={'有' if has_volume_ratio else '无'})")
        return candidates

    # === 持仓止损专用: 批量获取持仓价格 ===

    async def get_position_prices(self, ts_codes: List[str]) -> Dict[str, float]:
        """批量获取持仓股当前价格 (从全市场缓存, 0额外API)
        
        Returns:
            Dict[ts_code, price]
        """
        all_data = await self.get_all_realtime()
        result = {}
        for ts_code in ts_codes:
            item = all_data.get(ts_code)
            if item and item.get("price"):
                result[ts_code] = item["price"]
        return result

    # === 状态 ===

    def get_status(self) -> Dict:
        """返回适配器状态"""
        now = time.time()
        cache_age = now - self._cache_time if self._cache_time > 0 else -1
        return {
            "name": self.name(),
            "available": self._session is not None,
            "initialized": self._session is not None and self._total_stocks > 0,
            "total_stocks": self._total_stocks,
            "cached_stocks": len(self._cache),
            "cache_age_seconds": round(cache_age, 1) if cache_age >= 0 else None,
            "fetch_count": self._fetch_count,
            "last_fetch_time": datetime.fromtimestamp(self._last_fetch_time).strftime("%H:%M:%S") if self._last_fetch_time > 0 else None,
            "daily_calls": self._fetch_count,  # 东方财富无限流, 此为统计用
            "daily_limit": -1,                  # -1 = 无限制
            "daily_remaining": -1,               # -1 = 无限制
            "note": "免费无限流, 全市场快照3秒" if self._total_stocks > 0 else "push2被封, 腾讯回退",
        }
