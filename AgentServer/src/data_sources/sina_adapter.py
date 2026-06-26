"""
新浪财经实时行情适配器

数据源: https://hq.sinajs.cn/list=sz000001,sz000002
特点: 免费无限流, 返回全字段(含开高低收/量额/换手率)
限制: 需 Referer: https://finance.sina.com.cn

字段映射:
  新浪字段(按位置) → 标准字段
  0:  名称
  1:  昨收 → pre_close
  3:  当前价 → price
  4:  今开 → open
  5:  最高 → high
  6:  最低 → low
  7:  成交量(股) → vol
  8:  成交额(元) → amount
  9-18: 五档买卖
  29: 涨跌幅 → pct_chg (需计算)
  30: 振幅 → amplitude
  37: 换手率 → turnover_rate
"""

import asyncio
import logging
import time
from typing import Dict, Optional, List
import aiohttp

logger = logging.getLogger("sina_adapter")


class SinaAdapter:
    """新浪财经实时行情适配器"""

    BASE_URL = "https://hq.sinajs.cn/list="
    BATCH_SIZE = 800  # 每批最多800只

    def __init__(self, **kwargs):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict] = {}
        self._cache_time: float = 0
        self._cache_ttl: float = 5.0  # 5秒缓存
        self._total_stocks: int = 0
        self._fetch_count: int = 0
        self._last_fetch_time: float = 0
        self._stock_codes: List[str] = []  # 股票代码列表

    def name(self) -> str:
        return "sina"

    async def initialize(self) -> bool:
        """初始化: 创建HTTP session + 加载股票代码列表"""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={
                    "Referer": "https://finance.sina.com.cn",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
        # 加载股票代码列表(从MongoDB)
        try:
            from pymongo import MongoClient
            client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
            db = client["stock_agent"]
            # 获取最近交易日的所有股票代码
            latest = db["stock_daily_ak_full"].find_one(sort=[("trade_date", -1)])
            if latest:
                td = latest["trade_date"]
                codes = db["stock_daily_ak_full"].distinct("ts_code", {"trade_date": td})
                # 过滤掉北交所(新浪不太稳定), 保留沪深A
                self._stock_codes = [c for c in codes if c.endswith((".SH", ".SZ"))]
                logger.info(f"[SINA] 初始化: {len(self._stock_codes)}只股票(日期={td})")
            else:
                logger.warning("[SINA] MongoDB无数据, 用硬编码代码")
                self._stock_codes = self._get_hardcoded_codes()
        except Exception as e:
            logger.warning(f"[SINA] MongoDB加载失败({e}), 用硬编码代码")
            self._stock_codes = self._get_hardcoded_codes()

        # 预热: 拉一次验证连通性
        try:
            data = await self.get_all_realtime()
            if data:
                logger.info(f"[SINA] 预热成功, {len(data)}只股票")
                return True
        except Exception as e:
            logger.warning(f"[SINA] 预热失败({e})")

        return True  # 仍标记可用

    @staticmethod
    def _get_hardcoded_codes() -> List[str]:
        """硬编码代码列表(回退方案)"""
        codes = []
        for i in range(600000, 605000):
            codes.append(f"{i}.SH")
        for i in range(1, 3000):
            codes.append(f"{str(i).zfill(6)}.SZ")
        for i in range(300000, 301000):
            codes.append(f"{i}.SZ")
        return codes

    @staticmethod
    def _tscode_to_sina(ts_code: str) -> str:
        """ts_code → 新浪格式 (000001.SZ → sz000001)"""
        pure, suffix = ts_code.split(".") if "." in ts_code else (ts_code, "SZ")
        prefix = "sh" if suffix == "SH" else "sz"
        return f"{prefix}{pure}"

    @staticmethod
    def _sina_to_tscode(sina_code: str) -> str:
        """新浪格式 → ts_code (sz000001 → 000001.SZ)"""
        prefix = sina_code[:2]
        pure = sina_code[2:]
        if prefix == "sh":
            return f"{pure}.SH"
        else:
            return f"{pure}.SZ"

    async def _fetch_batch(self, sina_codes: List[str]) -> Dict[str, Dict]:
        """拉取一批行情(最多800只)"""
        if not self._session or not sina_codes:
            return {}

        url = f"{self.BASE_URL}{','.join(sina_codes)}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                logger.warning(f"[SINA] HTTP {resp.status}")
                return {}
            # 新浪返回 GBK 编码
            text = await resp.text(encoding="gbk", errors="replace")

        result = {}
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # 格式: var hq_str_sz000001="名称,昨收,今收,...";
            try:
                parts = line.split('="')
                if len(parts) < 2:
                    continue
                raw_code = parts[0].replace("var hq_str_", "").strip()
                data_str = parts[1].rstrip('";').strip()
                if not data_str:
                    continue
                fields = data_str.split(",")
                if len(fields) < 9:
                    continue

                ts_code = self._sina_to_tscode(raw_code)
                name = fields[0]

                # 解析数值字段
                def _f(idx, default=0.0):
                    if idx >= len(fields):
                        return default
                    v = fields[idx].strip()
                    try:
                        return float(v) if v else default
                    except (ValueError, TypeError):
                        return default

                pre_close = _f(1)
                price = _f(3)
                open_price = _f(2) if _f(2) else pre_close
                high = _f(4)
                low = _f(5)
                vol = _f(8)  # 股
                amount = _f(9)  # 元

                # 计算涨跌幅
                pct_chg = 0.0
                if pre_close and pre_close > 0:
                    pct_chg = round((price - pre_close) / pre_close * 100, 2)

                # 换手率(新浪无此字段, 从MongoDB补)
                turnover_rate = _f(38, None)

                # 振幅
                amplitude = 0.0
                if pre_close and pre_close > 0:
                    amplitude = round((high - low) / pre_close * 100, 2)

                result[ts_code] = {
                    "price": price,
                    "pct_chg": pct_chg,
                    "pre_close": pre_close,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "vol": vol,
                    "amount": amount,
                    "turnover_rate": turnover_rate,
                    "amplitude": amplitude,
                    "name": name,
                    "volume_ratio": None,  # 新浪无量比
                    "pe": None,
                    "pb": None,
                    "float_mv": None,
                }
            except Exception as e:
                logger.debug(f"[SINA] 解析失败: {line[:50]}... ({e})")
                continue

        return result

    async def get_all_realtime(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """获取全市场实时行情(带缓存)"""
        now = time.time()
        cache_age = now - self._cache_time

        if not force_refresh and self._cache and cache_age < self._cache_ttl:
            return self._cache

        if not self._stock_codes:
            logger.warning("[SINA] 股票代码列表为空")
            return {}

        all_data = {}
        # 分批拉取
        for i in range(0, len(self._stock_codes), self.BATCH_SIZE):
            batch = self._stock_codes[i:i + self.BATCH_SIZE]
            sina_codes = [self._tscode_to_sina(c) for c in batch]
            try:
                batch_data = await self._fetch_batch(sina_codes)
                all_data.update(batch_data)
            except Exception as e:
                logger.warning(f"[SINA] 批次{i//self.BATCH_SIZE}失败: {e}")
            await asyncio.sleep(0.05)  # 礼貌性延迟

        # 从MongoDB补充PE/PB/量比/流通市值
        if all_data:
            try:
                from pymongo import MongoClient
                client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
                db = client["stock_agent"]
                latest = db["daily_basic"].find_one(sort=[("trade_date", -1)])
                if latest:
                    td = latest["trade_date"]
                    supplemented = 0
                    for doc in db["daily_basic"].find(
                        {"trade_date": td},
                        {"ts_code": 1, "pe": 1, "pb": 1, "volume_ratio": 1, "circ_mv": 1}
                    ):
                        tc = doc.get("ts_code")
                        if tc and tc in all_data:
                            item = all_data[tc]
                            if item.get("volume_ratio") is None and doc.get("volume_ratio"):
                                item["volume_ratio"] = doc["volume_ratio"]
                            if item.get("pe") is None and doc.get("pe"):
                                item["pe"] = doc["pe"]
                            if item.get("pb") is None and doc.get("pb"):
                                item["pb"] = doc["pb"]
                            if item.get("float_mv") is None and doc.get("circ_mv"):
                                item["float_mv"] = doc["circ_mv"]
                            supplemented += 1
                    if supplemented:
                        logger.debug(f"[SINA] MongoDB补全: {supplemented}只PE/PB/量比")
            except Exception as e:
                logger.debug(f"[SINA] MongoDB补全失败(非致命): {e}")

        if all_data:
            self._total_stocks = len(all_data)
            self._cache = all_data
            self._cache_time = time.time()
            self._last_fetch_time = time.time()
            self._fetch_count += 1
            logger.info(f"[SINA] 获取 {len(all_data)} 只行情")

        return all_data

    async def get_realtime_quote(self, ts_code: str) -> Optional[Dict]:
        """获取单只股票实时行情"""
        sina_code = self._tscode_to_sina(ts_code)
        data = await self._fetch_batch([sina_code])
        return data.get(ts_code)

    async def is_available(self) -> bool:
        return self._session is not None

    async def shutdown(self):
        if self._session:
            await self._session.close()
            self._session = None

    def get_status(self) -> Dict:
        return {
            "source": "sina",
            "cached_stocks": self._total_stocks,
            "fetch_count": self._fetch_count,
            "last_fetch": time.strftime("%H:%M:%S", time.localtime(self._last_fetch_time)) if self._last_fetch_time else "N/A",
            "cache_age": round(time.time() - self._cache_time, 1) if self._cache_time else 999,
            "note": "免费无限流, 新浪财经" if self._total_stocks > 0 else "未初始化",
        }
