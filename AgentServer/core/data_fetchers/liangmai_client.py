"""
量脉金融数据平台客户端

统一网关接口，支持76个API，频率限制1分钟120次。
文档: docs/LIANGMAI_API.md

⚠️ 限制规则（两个独立限制，都必须遵守）:
    1. 请求限流: 每分钟120次 (TokenBucket控制)
    2. IP限制: Token绑定2个IP (4291错误=IP超限)

⚠️ IP被占时不要反复重试！等用户确认IP释放后再调用。
⚠️ 修改数据源前必须跟用户沟通（见 docs/DATA_SOURCE_POLICY.md）
"""
import asyncio
import time
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class LiangMaiClient:
    """量脉金融数据平台客户端

    特性:
    - 异步请求，支持并发控制
    - 内置速率限制(120次/分钟)
    - 自动重试(4291 IP限流)
    - 响应缓存(TTL 60s)
    """

    DEFAULT_BASE_URL = "http://124.220.44.71/api/gateway"
    RATE_LIMIT_PER_MINUTE = 120
    CACHE_TTL = 60  # 秒
    MIN_REQUEST_INTERVAL = 0.6  # 最小请求间隔(秒)，120/min=0.5s，留0.1s余量

    def __init__(
        self,
        token: str,
        base_url: str = None,
        rate_limit: int = None,
    ):
        self.token = token
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.rate_limit = rate_limit or self.RATE_LIMIT_PER_MINUTE
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_timestamps: List[float] = []
        self._cache: Dict[str, tuple] = {}  # key → (timestamp, data)
        self._lock = asyncio.Lock()

    async def initialize(self):
        """初始化HTTP会话"""
        if self._session is None or self._session.closed:
            # ⚠️ connection_pool=False: 不复用连接，避免429后连接池被污染
            # 每次请求独立TCP连接，牺牲少量性能换取稳定性
            connector = aiohttp.TCPConnector(force_close=True, limit=1)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "StockAgent-LiangMai/1.0"},
                connector=connector,
            )
            logger.info(f"LiangMaiClient initialized, base_url={self.base_url}")

    async def close(self):
        """关闭HTTP会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _wait_rate_limit(self):
        """等待速率限制窗口
        
        两层限流:
        1. 最小间隔: 每次请求至少间隔MIN_REQUEST_INTERVAL秒(0.6s)
        2. 窗口限流: 60秒内不超过RATE_LIMIT_PER_MINUTE次(120次)
        """
        async with self._lock:
            now = time.time()
            
            # 第一层: 最小请求间隔(防止突发并发)
            if self._request_timestamps:
                elapsed = now - self._request_timestamps[-1]
                if elapsed < self.MIN_REQUEST_INTERVAL:
                    wait = self.MIN_REQUEST_INTERVAL - elapsed
                    logger.debug(f"Min interval wait: {wait:.2f}s")
                    await asyncio.sleep(wait)
                    now = time.time()
            
            # 第二层: 窗口限流(60秒内不超过120次)
            self._request_timestamps = [
                t for t in self._request_timestamps if now - t < 60
            ]
            if len(self._request_timestamps) >= self.rate_limit:
                oldest = self._request_timestamps[0]
                wait_time = 60 - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    now = time.time()
            self._request_timestamps.append(now)

    def _cache_key(self, api: str, params: Dict) -> str:
        """生成缓存键"""
        sorted_params = sorted(params.items())
        return f"{api}:{sorted_params}"

    async def request(
        self,
        api: str,
        retry_on_rate_limit: bool = True,
        use_cache: bool = True,
        **params,
    ) -> Dict[str, Any]:
        """发送API请求

        Args:
            api: 接口名称(如 hs_list_main, pool_limit_up)
            retry_on_rate_limit: 4291时是否自动重试
            use_cache: 是否使用缓存
            **params: 接口参数

        Returns:
            API响应data字段内容

        Raises:
            ValueError: 接口返回错误
            RuntimeError: 重试次数耗尽
        """
        if self._session is None:
            await self.initialize()

        # 检查缓存
        cache_key = self._cache_key(api, params)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached and (time.time() - cached[0]) < self.CACHE_TTL:
                logger.debug(f"Cache hit: {api}")
                return cached[1]

        # 构建请求参数
        request_params = {"token": self.token, "api": api}
        request_params.update(params)

        # 速率限制
        await self._wait_rate_limit()

        # 发送请求
        max_retries = 3 if retry_on_rate_limit else 1
        for attempt in range(max_retries):
            try:
                async with self._session.get(
                    self.base_url, params=request_params
                ) as resp:
                    # ⚠️ 处理HTTP层面的429 (Too Many Requests)
                    # 量脉在请求频率超限时返回HTTP 429，不是JSON里的code=4291
                    if resp.status == 429:
                        if attempt < max_retries - 1:
                            wait = 5 * (attempt + 1)  # 5s, 10s, 15s
                            logger.warning(
                                f"HTTP 429 Too Many Requests (attempt {attempt+1}), "
                                f"waiting {wait}s"
                            )
                            # 重建session避免连接池污染
                            await self.close()
                            await self.initialize()
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(f"HTTP 429 rate limit after {max_retries} retries")
                    
                    data = await resp.json()

                    code = data.get("code", -1)
                    msg = data.get("msg", "")

                    if code == 0:
                        result = data.get("data", [])
                        # 更新缓存
                        if use_cache:
                            self._cache[cache_key] = (time.time(), result)
                        return result

                    elif code == 4291:
                        # 业务层IP限流(Token绑定IP超限)
                        if attempt < max_retries - 1:
                            wait = 30 * (attempt + 1)
                            logger.warning(
                                f"IP rate limited (attempt {attempt+1}), "
                                f"waiting {wait}s: {msg}"
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(f"IP rate limit exceeded after {max_retries} retries: {msg}")

                    else:
                        raise ValueError(f"API error code={code}: {msg}")

            except aiohttp.ClientError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Request error (attempt {attempt+1}): {e}")
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                raise

        raise RuntimeError(f"Failed after {max_retries} attempts")

    # ========== 便捷方法 ==========

    async def get_stock_list(self) -> List[Dict]:
        """沪深A股列表"""
        return await self.request("hs_list_main")

    async def get_kline(
        self,
        ts_code: str,
        klt: str = "d",
        fqt: str = "f",
        lt: int = None,
        beg: str = None,
        end: str = None,
    ) -> List[Dict]:
        """获取K线数据

        Args:
            ts_code: 6位股票代码(如 000001)
            klt: K线类型(1/5/15/30/60/d/w/m/y)
            fqt: 复权类型(n/f/b/fr/br)
            lt: 返回条数
            beg: 开始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD
        """
        params = {"ts_code": ts_code, "klt": klt, "fqt": fqt}
        if lt:
            params["lt"] = str(lt)
        if beg:
            params["beg"] = beg
        if end:
            params["end"] = end
        api = "quote_bars_history" if (beg or end) else "quote_bars_latest"
        return await self.request(api, **params)

    async def get_index_kline(
        self,
        ts_code: str,
        klt: str = "d",
        lt: int = None,
        beg: str = None,
        end: str = None,
    ) -> List[Dict]:
        """获取指数K线"""
        params = {"ts_code": ts_code, "klt": klt}
        if lt:
            params["lt"] = str(lt)
        if beg:
            params["beg"] = beg
        if end:
            params["end"] = end
        api = "index_bars_history" if (beg or end) else "index_bars_latest"
        return await self.request(api, **params)

    async def get_pool_limit_up(self, trade_date: str) -> List[Dict]:
        """涨停股池

        Args:
            trade_date: 日期 yyyy-MM-dd (从2019-11-28起)
        """
        return await self.request("pool_limit_up", trade_date=trade_date)

    async def get_pool_limit_down(self, trade_date: str) -> List[Dict]:
        """跌停股池"""
        return await self.request("pool_limit_down", trade_date=trade_date)

    async def get_pool_broken_board(self, trade_date: str) -> List[Dict]:
        """炸板股池"""
        return await self.request("pool_broken_board", trade_date=trade_date)

    async def get_pool_strong(self, trade_date: str) -> List[Dict]:
        """强势股池"""
        return await self.request("pool_strong", trade_date=trade_date)

    async def get_pool_subnew(self, trade_date: str) -> List[Dict]:
        """次新股池"""
        return await self.request("pool_subnew", trade_date=trade_date)

    async def get_realtime(self, ts_code: str) -> List[Dict]:
        """实时行情(网络源) - 含PE/PB/流通市值/总市值"""
        return await self.request("stock_realtime", ts_code=ts_code)

    async def get_realtime_broker(self, ts_code: str) -> List[Dict]:
        """实时行情(券商源) - 含换手率/市净率"""
        return await self.request("quote_realtime_broker", ts_code=ts_code)

    async def get_realtime_multi(self, codes: List[str]) -> List[Dict]:
        """多股实时行情(≤20只)"""
        return await self.request("stock_realtime_multi", ts_code=",".join(codes))

    async def get_capital_flow(
        self, ts_code: str, lt: int = None, beg: str = None, end: str = None
    ) -> List[Dict]:
        """资金流向(主力/大单/中单/小单)"""
        params = {"ts_code": ts_code}
        if lt:
            params["lt"] = str(lt)
        if beg:
            params["beg"] = beg
        if end:
            params["end"] = end
        return await self.request("capital_flow_history", **params)

    async def get_sector_tree(self) -> List[Dict]:
        """行业/概念/指数树"""
        return await self.request("sector_tree")

    async def get_sector_constituents(self, sector_code: str) -> List[Dict]:
        """板块成分股"""
        return await self.request("sector_constituents", sector_code=sector_code)

    async def get_stock_sectors(self, ts_code: str) -> List[Dict]:
        """个股所属板块/概念"""
        return await self.request("stock_sectors", ts_code=ts_code)

    async def get_company_profile(self, ts_code: str) -> List[Dict]:
        """公司简介(含概念板块)"""
        return await self.request("company_profile", ts_code=ts_code)

    async def get_tech_indicator(self, ts_code: str, indicator: str = "ma") -> List[Dict]:
        """技术指标

        Args:
            ts_code: 6位股票代码
            indicator: ma/macd/kdj/boll
        """
        api_map = {"ma": "tech_ma", "macd": "tech_macd", "kdj": "tech_kdj", "boll": "tech_boll"}
        api = api_map.get(indicator)
        if not api:
            raise ValueError(f"Unknown indicator: {indicator}, must be ma/macd/kdj/boll")
        return await self.request(api, ts_code=ts_code)

    async def get_stop_prices(self, ts_code: str) -> List[Dict]:
        """涨跌停价"""
        return await self.request("quote_stop_prices", ts_code=ts_code)

    # ========== StockAgent专用转换方法 ==========

    async def get_kline_as_stock_daily(
        self, ts_code: str, beg: str = None, end: str = None, lt: int = None
    ) -> List[Dict]:
        """获取K线并转换为stock_daily_ak_full格式

        返回字段与MongoDB stock_daily_ak_full集合对齐，
        可直接写入数据库。

        量脉字段 → StockAgent字段映射:
        t → trade_date (YYYYMMDD)
        o → open
        h → high
        l → low
        c → close
        v → vol (手→手, 保持一致)
        a → amount
        pc → pre_close
        """
        raw = await self.get_kline(ts_code, klt="d", fqt="f", lt=lt, beg=beg, end=end)

        # 转换代码格式: 000001 → 000001.SZ
        # 量脉返回dm含后缀(如000001.SZ)，如果ts_code不含后缀需要补上
        full_code = ts_code
        if "." not in full_code:
            # 默认深交所，需要根据实际情况判断
            if full_code.startswith(("6", "9")):
                full_code = f"{full_code}.SH"
            elif full_code.startswith(("8", "4")):
                full_code = f"{full_code}.BJ"
            else:
                full_code = f"{full_code}.SZ"

        result = []
        for bar in raw:
            # 日期转换: "2026-04-24 00:00:00" → "20260424"
            date_str = bar.get("t", "")
            trade_date = date_str[:10].replace("-", "") if date_str else ""

            record = {
                "ts_code": full_code,
                "trade_date": trade_date,
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "vol": bar.get("v"),
                "amount": bar.get("a"),
                "pre_close": bar.get("pc"),  # ⭐ 量脉直接提供pre_close！
                "suspend_flag": bar.get("sf", 0),
            }
            # 计算涨跌幅
            if record["pre_close"] and record["pre_close"] > 0:
                record["pct_chg"] = round(
                    (record["close"] - record["pre_close"]) / record["pre_close"] * 100, 2
                )
                record["change"] = round(record["close"] - record["pre_close"], 2)
            else:
                record["pct_chg"] = None
                record["change"] = None

            result.append(record)

        return result

    async def get_realtime_as_daily_basic(self, ts_code: str) -> Optional[Dict]:
        """获取实时行情并转换为daily_basic格式

        字段映射:
        pe → pe_ttm (动态市盈率)
        sjl → pb (市净率)
        lt → circ_mv (流通市值, 元→亿元 ÷100000000)
        sz → total_mv (总市值, 元→亿元)
        hs → turnover_rate (换手率%)
        lb → volume_ratio (量比)
        """
        raw = await self.get_realtime(ts_code)
        if not raw:
            return None

        r = raw[0] if isinstance(raw, list) else raw

        # 代码格式
        full_code = ts_code
        if "." not in full_code:
            if full_code.startswith(("6", "9")):
                full_code = f"{full_code}.SH"
            elif full_code.startswith(("8", "4")):
                full_code = f"{full_code}.BJ"
            else:
                full_code = f"{full_code}.SZ"

        circ_mv_raw = r.get("lt", 0)  # 元
        total_mv_raw = r.get("sz", 0)  # 元

        return {
            "ts_code": full_code,
            "pe_ttm": r.get("pe"),       # 动态市盈率
            "pb": r.get("sjl"),          # 市净率
            "circ_mv": round(circ_mv_raw / 1e8, 4) if circ_mv_raw else None,  # 元→亿元
            "total_mv": round(total_mv_raw / 1e8, 4) if total_mv_raw else None,  # 元→亿元
            "turnover_rate": r.get("hs"),  # 换手率%
            "volume_ratio": r.get("lb"),   # 量比
            "close": r.get("p"),           # 当前价
            "pre_close": r.get("yc"),      # 昨收
        }

    async def get_pool_limit_up_as_limit_list(self, trade_date: str) -> List[Dict]:
        """涨停池转换为limit_list格式

        量脉涨停池比Tushare limit_list更丰富:
        - 新增: 封板时间(fbt/lbt)、炸板次数(zbc)、封板资金(zj)、连板数(Lbc)
        - 新增: 涨停统计(tj: x天/y板)、行业(hy)
        """
        raw = await self.get_pool_limit_up(trade_date)

        result = []
        for r in raw:
            dm = r.get("dm", "")
            # 补全代码后缀
            if "." not in dm:
                if dm.startswith(("6", "9")):
                    dm = f"{dm}.SH"
                elif dm.startswith(("8", "4")):
                    dm = f"{dm}.BJ"
                else:
                    dm = f"{dm}.SZ"

            record = {
                "ts_code": dm,
                "trade_date": trade_date.replace("-", ""),
                "name": r.get("Mc", ""),
                "close": r.get("p"),
                "pct_chg": r.get("zf"),
                "amount": r.get("cje"),
                "circ_mv": round(r.get("lt", 0) / 1e8, 4) if r.get("lt") else None,
                "total_mv": round(r.get("zsz", 0) / 1e8, 4) if r.get("zsz") else None,
                "turnover_rate": r.get("hs"),
                "limit_times": r.get("Lbc", 0),       # 连板数
                "first_limit_time": r.get("fbt", ""),   # 首次封板时间
                "last_limit_time": r.get("lbt", ""),    # 最后封板时间
                "limit_amount": r.get("zj"),            # 封板资金(元)
                "broken_times": r.get("zbc", 0),        # 炸板次数
                "limit_stat": r.get("tj", ""),          # 涨停统计
                "industry": r.get("hy", ""),            # 所属行业
                "up_stat": 1,  # 涨停标记
            }
            result.append(record)

        return result


# 单例工厂
_client: Optional[LiangMaiClient] = None


async def get_liangmai_client(token: str = None) -> LiangMaiClient:
    """获取量脉客户端单例"""
    global _client
    if _client is None:
        if token is None:
            # 从配置或环境变量读取
            import os
            token = os.environ.get("LIANGMAI_TOKEN", "ebacbad6d64444cd037ac5504b63f25d")
        _client = LiangMaiClient(token=token)
        await _client.initialize()
    return _client
