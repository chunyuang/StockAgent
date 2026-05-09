#!/usr/bin/env python3
"""
量脉批量数据拉取脚本 — 智能利用4291间歇窗口

功能：
1. 补充stock_daily_ak_full缺失因子(volume_ratio/circ_mv/PE/PB)
2. 补充daily_basic全市场PE/PB/circ_mv
3. 拉取涨停池/跌停池/开板池
4. 拉取指数日K

策略：
- 4291=IP槽位被占，等20-30秒重试
- 成功一次后立即尝试下一个请求(趁槽位还在)
- 连续失败3次则等60秒
- 速率限制120次/分，每请求间隔0.5秒
"""
import asyncio
import sys
import os
import time
import json
import logging
import aiohttp
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne, MongoClient
from core.data_fetchers.liangmai_client import LiangMaiClient

TOKEN = os.environ.get("LIANGMAI_TOKEN", "ebacbad6d64444cd037ac5504b63f25d")
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("liangmai_fetch")


class BatchFetcher:
    """智能4291窗口批量拉取器"""

    def __init__(self):
        self.client = LiangMaiClient(token=TOKEN)
        self.mongo = MongoClient(MONGO_URI)
        self.db = self.mongo[DB_NAME]
        self.stats = {"success": 0, "4291": 0, "error": 0, "cache_hit": 0}
        self._consecutive_4291 = 0
        self._request_times = []

    async def initialize(self):
        await self.client.initialize()
        log.info("LiangMaiClient initialized")

    async def close(self):
        await self.client.close()
        self.mongo.close()
        log.info(
            f"Done. success={self.stats['success']} 4291={self.stats['4291']} "
            f"error={self.stats['error']} cache={self.stats['cache_hit']}"
        )

    async def smart_request(self, api: str, use_cache: bool = True, **params):
        """智能请求：利用4291间歇窗口，连续失败退避"""
        # 检查内存缓存
        if use_cache:
            cached = self.client._cache.get(self.client._cache_key(api, params))
            if cached and (time.time() - cached[0]) < self.client.CACHE_TTL:
                self.stats["cache_hit"] += 1
                return cached[1]

        # 速率限制：120/min → 0.5s间隔
        now = time.time()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= 118:
            wait = 60 - (now - self._request_times[0]) + 1
            log.info(f"Rate limit approaching, waiting {wait:.0f}s")
            await asyncio.sleep(wait)

        # 4291退避：连续3次4291→等60秒
        if self._consecutive_4291 >= 3:
            log.info("3 consecutive 4291, waiting 60s...")
            await asyncio.sleep(60)
            self._consecutive_4291 = 0

        self._request_times.append(time.time())

        try:
            result = await self.client.request(
                api, retry_on_rate_limit=False, use_cache=False, **params
            )
            self.stats["success"] += 1
            self._consecutive_4291 = 0
            # 手动更新缓存
            self.client._cache[self.client._cache_key(api, params)] = (
                time.time(),
                result,
            )
            return result
        except RuntimeError as e:
            err = str(e)
            if "4291" in err or "IP rate limit" in err:
                self.stats["4291"] += 1
                self._consecutive_4291 += 1
                wait = 25 + self._consecutive_4291 * 5
                log.warning(f"4291 IP limit (consecutive={self._consecutive_4291}), waiting {wait}s")
                await asyncio.sleep(wait)
                return None
            elif "429" in err:
                self.stats["4291"] += 1
                self._consecutive_4291 += 1
                await asyncio.sleep(30)
                return None
            else:
                self.stats["error"] += 1
                log.error(f"RuntimeError: {e}")
                return None
        except aiohttp.ClientError as e:
            self.stats["error"] += 1
            log.error(f"HTTP error: {e}")
            await asyncio.sleep(5)
            return None
        except Exception as e:
            self.stats["error"] += 1
            log.error(f"Request error: {e}")
            await asyncio.sleep(5)
            return None

    # ==================== 任务1: 涨停池/跌停池 ====================
    async def fetch_limit_pools(self, start_date: int, end_date: int):
        """拉取涨停池/跌停池/开板池"""
        log.info(f"=== 涨停池任务: {start_date}~{end_date} ===")

        # 获取已有日期避免重复
        existing = set()
        for coll in ["limit_pool_up", "limit_pool_down", "limit_pool_broken"]:
            dates = self.db[coll].distinct("trade_date")
            existing.update([(coll, d) for d in dates])

        trade_dates = self.db.stock_daily_ak_full.distinct(
            "trade_date", {"trade_date": {"$gte": start_date, "$lte": end_date}}
        )
        trade_dates.sort()

        for td in trade_dates:
            td_str = str(td)
            tasks = [
                ("pool_limit_up", "limit_pool_up", "涨停池"),
                ("pool_limit_down", "limit_pool_down", "跌停池"),
                ("pool_broken_board", "limit_pool_broken", "开板池"),
            ]
            for api, coll, name in tasks:
                if (coll, td) in existing:
                    continue
                date_str = f"{str(td)[:4]}-{str(td)[4:6]}-{str(td)[6:8]}"
                result = await self.smart_request(api, date=date_str)
                if result and len(result) > 0:
                    for r in result:
                        r["trade_date"] = td
                    try:
                        self.db[coll].insert_many(result, ordered=False)
                        log.info(f"  {td} {name}: {len(result)}只 ✅")
                    except Exception as e:
                        if "duplicate" in str(e).lower():
                            existing.add((coll, td))
                        else:
                            log.error(f"  {td} {name} insert error: {e}")
                elif result is not None:
                    log.info(f"  {td} {name}: 0只 (空)")
                    existing.add((coll, td))

                await asyncio.sleep(0.5)

            existing.update([(c, td) for c, _, _ in tasks])

    # ==================== 任务2: 全市场实时行情→daily_basic ====================
    async def fetch_realtime_to_daily_basic(self):
        """用stock_realtime逐只拉取→写daily_basic(PE/PB/circ_mv/volume_ratio)"""
        log.info("=== 全市场实时行情→daily_basic ===")

        # 获取全市场股票列表
        today = int(datetime.now().strftime("%Y%m%d"))
        codes = self.db.stock_daily_ak_full.distinct(
            "ts_code", {"trade_date": {"$gte": 20260501}}
        )
        log.info(f"活跃股票: {len(codes)}只")

        # 已有daily_basic的今天跳过
        existing_today = set()
        if self.db.daily_basic.count_documents({"trade_date": today}) > 100:
            log.info(f"今天{today}已有daily_basic数据>100条，跳过")
            return

        # 按量脉格式转换代码
        def to_liangmai_code(ts_code):
            return ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

        batch_size = 0
        updates = []
        total = len(codes)

        for i, ts_code in enumerate(codes):
            lm_code = to_liangmai_code(ts_code)

            # 尝试stock_realtime
            result = await self.smart_request("stock_realtime", ts_code=lm_code)
            if result is None:
                # 4291等了，继续
                continue

            if not result or not isinstance(result, list) or len(result) == 0:
                continue

            r = result[0]
            lt = r.get("lt", 0)  # 流通市值(元)
            sz = r.get("sz", 0)  # 总市值(元)

            doc = {
                "ts_code": ts_code,
                "trade_date": today,
                "pe": r.get("pe"),
                "pb": r.get("sjl"),
                "circ_mv": round(lt / 1e8, 4) if lt else None,  # 元→亿元
                "total_mv": round(sz / 1e8, 4) if sz else None,
                "turnover_rate": r.get("hs"),
                "volume_ratio": r.get("lb"),
                "close": r.get("p"),
                "pre_close": r.get("yc"),
            }
            updates.append(
                UpdateOne(
                    {"ts_code": ts_code, "trade_date": today},
                    {"$set": doc},
                    upsert=True,
                )
            )
            batch_size += 1

            if batch_size >= 50:
                try:
                    self.db.daily_basic.bulk_write(updates, ordered=False)
                except Exception as e:
                    log.error(f"bulk_write error: {e}")
                log.info(f"  已写入 {i+1}/{total} ({batch_size}条)")
                updates = []
                batch_size = 0

            if (i + 1) % 100 == 0:
                log.info(f"  进度: {i+1}/{total}, stats={self.stats}")

            await asyncio.sleep(0.5)

        # 写入剩余
        if updates:
            try:
                self.db.daily_basic.bulk_write(updates, ordered=False)
            except Exception as e:
                log.error(f"final bulk_write error: {e}")

        log.info(f"  daily_basic写入完成, 进度 {total}/{total}")

    # ==================== 任务3: multi实时行情(批量20只) ====================
    async def fetch_realtime_multi_batch(self):
        """用stock_realtime_multi批量20只拉，更高效"""
        log.info("=== 批量实时行情(multi)→daily_basic ===")

        today = int(datetime.now().strftime("%Y%m%d"))

        # 获取需要更新的股票
        existing_today = set(
            d["ts_code"]
            for d in self.db.daily_basic.find(
                {"trade_date": today, "pe": {"$ne": None}},
                {"ts_code": 1},
            )
        )
        codes = self.db.stock_daily_ak_full.distinct(
            "ts_code", {"trade_date": {"$gte": 20260501}}
        )
        need = [c for c in codes if c not in existing_today]
        log.info(f"需要更新: {len(need)}只 (已有{len(existing_today)}只)")

        if not need:
            log.info("全部已更新，跳过")
            return

        updates = []
        total = len(need)

        # multi一次20只
        for i in range(0, len(need), 20):
            batch = need[i : i + 20]
            lm_codes = ",".join(
                c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
                for c in batch
            )

            result = await self.smart_request("stock_realtime_multi", stock_codes=lm_codes)
            if result is None:
                continue

            if not isinstance(result, list):
                continue

            for r in result:
                dm = r.get("dm", "")
                # 转回ts_code
                code = str(dm).zfill(6)
                if code.startswith(("6", "9")):
                    ts_code = f"{code}.SH"
                elif code.startswith(("8", "4")):
                    ts_code = f"{code}.BJ"
                else:
                    ts_code = f"{code}.SZ"

                lt = r.get("lt", 0)
                sz = r.get("sz", 0)

                doc = {
                    "ts_code": ts_code,
                    "trade_date": today,
                    "pe": r.get("pe"),
                    "pb": r.get("sjl"),
                    "circ_mv": round(lt / 1e8, 4) if lt else None,
                    "total_mv": round(sz / 1e8, 4) if sz else None,
                    "turnover_rate": r.get("hs"),
                    "volume_ratio": r.get("lb"),
                    "close": r.get("p"),
                    "pre_close": r.get("yc"),
                }
                updates.append(
                    UpdateOne(
                        {"ts_code": ts_code, "trade_date": today},
                        {"$set": doc},
                        upsert=True,
                    )
                )

            if len(updates) >= 100:
                try:
                    self.db.daily_basic.bulk_write(updates, ordered=False)
                except Exception as e:
                    log.error(f"bulk_write error: {e}")
                log.info(
                    f"  已写入 {min(i+20, total)}/{total} "
                    f"({len(updates)}条) stats={self.stats}"
                )
                updates = []

            await asyncio.sleep(0.5)

        if updates:
            try:
                self.db.daily_basic.bulk_write(updates, ordered=False)
            except Exception as e:
                log.error(f"final bulk_write error: {e}")

        log.info(f"  multi批量写入完成, stats={self.stats}")

    # ==================== 任务4: 指数日K ====================
    async def fetch_index_daily(self, index_codes=None, days=30):
        """拉取指数日K"""
        if index_codes is None:
            index_codes = [
                "000001.SH", "399001.SZ", "399006.SZ",
                "000016.SH", "000300.SH", "000905.SH",
            ]

        log.info(f"=== 指数日K: {index_codes} ===")

        for code in index_codes:
            result = await self.smart_request("index_kline", ts_code=code, klt=101, ktype=1)
            if result and isinstance(result, list):
                updates = []
                for r in result:
                    td = r.get("d", "")
                    if not td:
                        continue
                    td_int = int(td.replace("-", ""))
                    doc = {
                        "ts_code": code,
                        "trade_date": td_int,
                        "open": r.get("o"),
                        "high": r.get("h"),
                        "low": r.get("l"),
                        "close": r.get("p"),
                        "vol": r.get("v"),
                        "amount": r.get("a"),
                    }
                    updates.append(
                        UpdateOne(
                            {"ts_code": code, "trade_date": td_int},
                            {"$set": doc},
                            upsert=True,
                        )
                    )
                if updates:
                    try:
                        self.db.index_daily.bulk_write(updates, ordered=False)
                        log.info(f"  {code}: {len(updates)}条 ✅")
                    except Exception as e:
                        log.error(f"  {code} bulk_write error: {e}")
            await asyncio.sleep(0.5)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="量脉批量数据拉取")
    parser.add_argument(
        "--task",
        choices=["pools", "realtime", "multi", "index", "all"],
        default="all",
        help="任务类型: pools=涨停池, realtime=逐只实时, multi=批量实时, index=指数, all=全部",
    )
    parser.add_argument(
        "--start-date", type=int, default=20260101, help="涨停池起始日"
    )
    parser.add_argument("--end-date", type=int, default=20260507, help="涨停池结束日")

    args = parser.parse_args()

    fetcher = BatchFetcher()
    await fetcher.initialize()

    try:
        if args.task in ("pools", "all"):
            await fetcher.fetch_limit_pools(args.start_date, args.end_date)

        if args.task in ("multi", "all"):
            # 优先用multi(一次20只，更高效)
            await fetcher.fetch_realtime_multi_batch()

        if args.task == "realtime":
            # 逐只拉(4291时fallback)
            await fetcher.fetch_realtime_to_daily_basic()

        if args.task in ("index", "all"):
            await fetcher.fetch_index_daily()

    except KeyboardInterrupt:
        log.info("用户中断")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
