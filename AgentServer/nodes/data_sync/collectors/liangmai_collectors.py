"""
量脉金融数据采集器

数据来源: 量脉金融数据平台 (http://124.220.44.71/api/gateway)
优势:
- K线直接含pre_close字段(解决Tushare前复权缺失问题)
- 涨停池含封板时间/炸板次数/连板数(比Tushare limit_list更丰富)
- 实时PE/PB/流通市值/换手率(替代Tushare daily_basic)

频率限制: 1分钟120次, IP上限2个
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import time
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.constants import C
from core.managers import mongo_manager
from core.data_fetchers.liangmai_client import LiangMaiClient


class LiangMaiKlineCollector(BaseCollector):
    """量脉K线数据采集器
    
    采集沪深A股日K线，直接写入stock_daily_ak_full集合。
    优势: 数据直接含pre_close字段，无需运行时补算。
    
    调度: 每个交易日16:30(收盘后)
    """
    name = "liangmai_kline"
    description = "量脉K线数据采集(含pre_close)"
    default_schedule = "30 16 * * 1-5"
    
    WRITE_BATCH_SIZE = 500
    # 每批股票数(避免一次请求太多)
    STOCK_BATCH_SIZE = 50
    # 历史回补天数
    INITIAL_SYNC_DAYS = 30
    
    def __init__(self):
        super().__init__()
        self._client: Optional[LiangMaiClient] = None
    
    async def _get_client(self) -> LiangMaiClient:
        if self._client is None:
            from core.data_fetchers.liangmai_client import get_liangmai_client
            self._client = await get_liangmai_client()
        return self._client
    
    @property
    def schedule(self) -> str:
        return getattr(settings, 'data_sync', None) and \
               getattr(settings.data_sync, 'liangmai_kline_schedule', None) or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        client = await self._get_client()
        
        # 1. 获取股票列表
        stock_list = await client.get_stock_list()
        if not stock_list:
            return {"count": 0, "message": "No stock list available"}
        
        # 2. 确定同步范围
        today = datetime.now().strftime("%Y%m%d")
        last_sync = await mongo_manager.get_last_sync_date(self.name)
        
        if last_sync and last_sync >= today:
            self.logger.info(f"Kline already synced for {today}")
            return {"count": 0, "skipped": True}
        
        start_date = last_sync or (datetime.now() - timedelta(days=self.INITIAL_SYNC_DAYS)).strftime("%Y%m%d")
        
        self.logger.info(f"Syncing kline: {len(stock_list)} stocks, {start_date} -> {today}")
        
        total_count = 0
        errors = 0
        buffer: List[Dict[str, Any]] = []
        
        # 3. 逐只股票获取K线
        for i, stock in enumerate(stock_list):
            dm = stock.get("dm", "")  # 如 000001.SZ 或 000001
            # 提取6位代码
            code = dm.split(".")[0] if "." in dm else dm
            
            try:
                records = await client.get_kline_as_stock_daily(
                    ts_code=code,
                    beg=start_date,
                    end=today,
                )
                
                if records:
                    buffer.extend(records)
                    if (i + 1) % 100 == 0:
                        self.logger.info(f"  Progress: {i+1}/{len(stock_list)} stocks, buffer={len(buffer)}")
                
            except Exception as e:
                errors += 1
                if errors <= 5:
                    self.logger.warning(f"Failed to fetch kline for {code}: {e}")
            
            # 批量写入
            if len(buffer) >= self.WRITE_BATCH_SIZE:
                result = await mongo_manager.bulk_upsert(
                    collection=C.STOCK_DAILY,
                    documents=buffer,
                    key_fields=["ts_code", "trade_date"],
                    batch_size=self.WRITE_BATCH_SIZE,
                )
                total_count += result["upserted"] + result["modified"]
                buffer.clear()
            
            # 速率限制: 120次/分钟 → 0.5秒间隔(加上client内部限制)
            await asyncio.sleep(0.5)
        
        # 写入剩余数据
        if buffer:
            result = await mongo_manager.bulk_upsert(
                collection=C.STOCK_DAILY,
                documents=buffer,
                key_fields=["ts_code", "trade_date"],
                batch_size=self.WRITE_BATCH_SIZE,
            )
            total_count += result["upserted"] + result["modified"]
        
        # 记录同步
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=today,
            count=total_count,
        )
        
        self.logger.info(f"Kline sync done: {total_count} records, {errors} errors")
        return {
            "count": total_count,
            "stocks": len(stock_list),
            "errors": errors,
            "start_date": start_date,
            "end_date": today,
        }


class LiangMaiLimitUpCollector(BaseCollector):
    """量脉涨停池采集器
    
    采集每日涨停股票池，含封板时间/炸板次数/连板数/封板资金。
    数据比Tushare limit_list更丰富，写入C.LIMIT_LIST集合。
    
    调度: 每个交易日16:15(收盘后)
    """
    name = "liangmai_limit_up"
    description = "量脉涨停池采集(含封板时间/炸板次数)"
    default_schedule = "15 16 * * 1-5"
    
    WRITE_BATCH_SIZE = 500
    INITIAL_SYNC_DAYS = 30
    
    def __init__(self):
        super().__init__()
        self._client: Optional[LiangMaiClient] = None
    
    async def _get_client(self) -> LiangMaiClient:
        if self._client is None:
            from core.data_fetchers.liangmai_client import get_liangmai_client
            self._client = await get_liangmai_client()
        return self._client
    
    async def collect(self) -> Dict[str, Any]:
        client = await self._get_client()
        
        today_display = datetime.now().strftime("%Y-%m-%d")
        today_int = datetime.now().strftime("%Y%m%d")
        
        # 检查是否已同步
        if await mongo_manager.is_synced(self.name, today_int):
            self.logger.info(f"Limit up {today_int} already synced")
            return {"count": 0, "skipped": True}
        
        # 确定日期范围
        last_sync = await mongo_manager.get_last_sync_date(self.name)
        start_dt = datetime.strptime(last_sync, "%Y%m%d") + timedelta(days=1) if last_sync else \
                   datetime.now() - timedelta(days=self.INITIAL_SYNC_DAYS)
        
        total_count = 0
        current = start_dt
        
        while current <= datetime.now():
            # 跳过周末
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            
            date_str = current.strftime("%Y-%m-%d")
            date_int = current.strftime("%Y%m%d")
            
            try:
                records = await client.get_pool_limit_up_as_limit_list(date_str)
                
                if records:
                    # 标记数据来源为量脉
                    for r in records:
                        r["data_source"] = "liangmai"
                    
                    result = await mongo_manager.bulk_upsert(
                        collection=C.LIMIT_LIST,
                        documents=records,
                        key_fields=["ts_code", "trade_date"],
                        batch_size=self.WRITE_BATCH_SIZE,
                    )
                    count = result["upserted"] + result["modified"]
                    total_count += count
                    self.logger.info(f"  {date_str}: {len(records)} 涨停, upserted={count}")
                
                # 同时采集跌停池
                try:
                    down_records = await client.get_pool_limit_down(date_str)
                    if down_records:
                        down_formatted = []
                        for r in down_records:
                            dm = r.get("dm", "")
                            if "." not in dm:
                                if dm.startswith(("6", "9")): dm = f"{dm}.SH"
                                elif dm.startswith(("8", "4")): dm = f"{dm}.BJ"
                                else: dm = f"{dm}.SZ"
                            down_formatted.append({
                                "ts_code": dm,
                                "trade_date": date_int,
                                "name": r.get("mc", ""),
                                "close": r.get("p"),
                                "pct_chg": r.get("zf"),
                                "amount": r.get("Cje", r.get("cje")),
                                "circ_mv": round(r.get("lt", 0) / 1e8, 4) if r.get("lt") else None,
                                "turnover_rate": r.get("hs"),
                                "limit_times": r.get("lbc", 0),
                                "last_limit_time": r.get("lbt", ""),
                                "limit_amount": r.get("zj"),
                                "broken_times": r.get("zbc", 0),
                                "industry": "",
                                "up_stat": 0,  # 跌停标记
                                "data_source": "liangmai",
                            })
                        
                        if down_formatted:
                            result = await mongo_manager.bulk_upsert(
                                collection=C.LIMIT_LIST,
                                documents=down_formatted,
                                key_fields=["ts_code", "trade_date"],
                                batch_size=self.WRITE_BATCH_SIZE,
                            )
                            self.logger.info(f"  {date_str}: {len(down_formatted)} 跌停")
                
                except Exception as e:
                    self.logger.warning(f"Failed limit_down for {date_str}: {e}")
                
                # 采集炸板池
                try:
                    broken = await client.get_pool_broken_board(date_str)
                    if broken:
                        self.logger.info(f"  {date_str}: {len(broken)} 炸板")
                        # 炸板数据存入单独的liangmai_broken_board集合或合并到limit_list
                        broken_formatted = []
                        for r in broken:
                            dm = r.get("dm", "")
                            if "." not in dm:
                                if dm.startswith(("6", "9")): dm = f"{dm}.SH"
                                elif dm.startswith(("8", "4")): dm = f"{dm}.BJ"
                                else: dm = f"{dm}.SZ"
                            broken_formatted.append({
                                "ts_code": dm,
                                "trade_date": date_int,
                                "name": r.get("mc", ""),
                                "close": r.get("p"),
                                "pct_chg": r.get("zf"),
                                "broken_times": r.get("zbc", 0),
                                "first_limit_time": r.get("fbt", ""),
                                "limit_price": r.get("ztp"),
                                "data_source": "liangmai",
                                "is_broken_board": True,
                            })
                        
                        if broken_formatted:
                            await mongo_manager.bulk_upsert(
                                collection=C.LIMIT_LIST,
                                documents=broken_formatted,
                                key_fields=["ts_code", "trade_date"],
                                batch_size=self.WRITE_BATCH_SIZE,
                            )
                except Exception as e:
                    self.logger.warning(f"Failed broken_board for {date_str}: {e}")
                
            except Exception as e:
                self.logger.warning(f"Failed limit pool for {date_str}: {e}")
            
            # 速率限制
            await asyncio.sleep(0.6)
            current += timedelta(days=1)
        
        # 记录同步
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=today_int,
            count=total_count,
        )
        
        return {"count": total_count, "end_date": today_int}


class LiangMaiRealtimeCollector(BaseCollector):
    """量脉实时行情采集器
    
    采集实时PE/PB/流通市值/换手率/量比，写入daily_basic集合。
    解决daily_basic数据缺失/延迟问题，提供当日精确数据。
    
    调度: 交易日15:05(收盘后第一时间)和20:00(数据稳定后)
    """
    name = "liangmai_realtime"
    description = "量脉实时行情采集(PE/PB/流通市值)"
    default_schedule = "5 15,20 * * 1-5"
    
    WRITE_BATCH_SIZE = 500
    
    def __init__(self):
        super().__init__()
        self._client: Optional[LiangMaiClient] = None
    
    async def _get_client(self) -> LiangMaiClient:
        if self._client is None:
            from core.data_fetchers.liangmai_client import get_liangmai_client
            self._client = await get_liangmai_client()
        return self._client
    
    async def collect(self) -> Dict[str, Any]:
        client = await self._get_client()
        
        today_int = datetime.now().strftime("%Y%m%d")
        
        # 获取股票列表
        stock_list = await client.get_stock_list()
        if not stock_list:
            return {"count": 0, "message": "No stock list"}
        
        self.logger.info(f"Fetching realtime data for {len(stock_list)} stocks")
        
        total_count = 0
        errors = 0
        buffer: List[Dict[str, Any]] = []
        
        for i, stock in enumerate(stock_list):
            dm = stock.get("dm", "")
            code = dm.split(".")[0] if "." in dm else dm
            
            try:
                record = await client.get_realtime_as_daily_basic(code)
                
                if record:
                    record["trade_date"] = today_int
                    buffer.append(record)
                
            except Exception as e:
                errors += 1
                if errors <= 5:
                    self.logger.warning(f"Failed realtime for {code}: {e}")
            
            # 批量写入
            if len(buffer) >= self.WRITE_BATCH_SIZE:
                result = await mongo_manager.bulk_upsert(
                    collection=C.DAILY_BASIC,
                    documents=buffer,
                    key_fields=["ts_code", "trade_date"],
                    batch_size=self.WRITE_BATCH_SIZE,
                )
                total_count += result["upserted"] + result["modified"]
                self.logger.info(f"  Written {len(buffer)} records, total={total_count}")
                buffer.clear()
            
            # 进度日志
            if (i + 1) % 200 == 0:
                self.logger.info(f"  Progress: {i+1}/{len(stock_list)}")
            
            # 速率限制
            await asyncio.sleep(0.5)
        
        # 写入剩余
        if buffer:
            result = await mongo_manager.bulk_upsert(
                collection=C.DAILY_BASIC,
                documents=buffer,
                key_fields=["ts_code", "trade_date"],
                batch_size=self.WRITE_BATCH_SIZE,
            )
            total_count += result["upserted"] + result["modified"]
        
        # 记录同步
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=today_int,
            count=total_count,
        )
        
        self.logger.info(f"Realtime sync done: {total_count} records, {errors} errors")
        return {"count": total_count, "stocks": len(stock_list), "errors": errors}


class LiangMaiIndexCollector(BaseCollector):
    """量脉指数K线采集器
    
    采集沪深主要指数日K线，写入index_daily集合。
    解决基准数据缺失问题(之前查错集合导致基准收益率恒为0)。
    
    调度: 每个交易日16:20
    """
    name = "liangmai_index"
    description = "量脉指数K线采集"
    default_schedule = "20 16 * * 1-5"
    
    # 主要指数
    MAIN_INDICES = {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000016": "上证50",
        "000300": "沪深300",
        "000905": "中证500",
        "000852": "中证1000",
    }
    
    WRITE_BATCH_SIZE = 100
    INITIAL_SYNC_DAYS = 30
    
    def __init__(self):
        super().__init__()
        self._client: Optional[LiangMaiClient] = None
    
    async def _get_client(self) -> LiangMaiClient:
        if self._client is None:
            from core.data_fetchers.liangmai_client import get_liangmai_client
            self._client = await get_liangmai_client()
        return self._client
    
    async def collect(self) -> Dict[str, Any]:
        client = await self._get_client()
        
        today = datetime.now().strftime("%Y%m%d")
        last_sync = await mongo_manager.get_last_sync_date(self.name)
        start_date = last_sync or (datetime.now() - timedelta(days=self.INITIAL_SYNC_DAYS)).strftime("%Y%m%d")
        
        total_count = 0
        
        for code, name in self.MAIN_INDICES.items():
            try:
                raw = await client.get_index_kline(code, klt="d", beg=start_date, end=today)
                
                if not raw:
                    continue
                
                records = []
                for bar in raw:
                    date_str = bar.get("t", "")
                    trade_date = date_str[:10].replace("-", "") if date_str else ""
                    
                    # 代码后缀: 上证指数000001.SH, 深证399001.SZ
                    suffix = "SH" if code.startswith(("000", "880")) else "SZ"
                    
                    records.append({
                        "ts_code": f"{code}.{suffix}",
                        "trade_date": trade_date,
                        "index_code": code,
                        "name": name,
                        "open": bar.get("o"),
                        "high": bar.get("h"),
                        "low": bar.get("l"),
                        "close": bar.get("c"),
                        "vol": bar.get("v"),
                        "amount": bar.get("a"),
                        "pre_close": bar.get("pc"),
                    })
                
                if records:
                    result = await mongo_manager.bulk_upsert(
                        collection=C.INDEX_DAILY,
                        documents=records,
                        key_fields=["ts_code", "trade_date"],
                        batch_size=self.WRITE_BATCH_SIZE,
                    )
                    count = result["upserted"] + result["modified"]
                    total_count += count
                    self.logger.info(f"  {name}({code}): {len(records)} bars, upserted={count}")
                
            except Exception as e:
                self.logger.warning(f"Failed index kline for {code}: {e}")
            
            await asyncio.sleep(0.5)
        
        await mongo_manager.record_sync(sync_type=self.name, sync_date=today, count=total_count)
        
        return {"count": total_count, "indices": len(self.MAIN_INDICES)}
