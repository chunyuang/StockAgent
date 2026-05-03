"""
每日复盘数据采集器

在每日收盘后采集复盘所需的各类数据。
支持并行采集和失败自动重试。

数据来源:
- limit_step: 连板天梯
- limit_cpt_list: 最强板块统计
- top_inst: 龙虎榜机构明细
- ths_hot: 同花顺热股排行
- ths_daily: 板块日线行情
- moneyflow_hsgt: 北向资金

存储集合:
- review_limit_step: 连板天梯
- review_sector_limit: 板块涨停统计
- review_sector_daily: 板块日线
- review_dragon: 龙虎榜
- review_hot: 热股排行
- review_northbound: 北向资金
"""

from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


# 子采集器配置：(名称, 集合名, API方法, 索引定义)
REVIEW_SUB_COLLECTORS: List[Tuple[str, str, str, List[Tuple]]] = [
    ("limit_step", "review_limit_step", "get_limit_step", [
        ([("trade_date", 1), ("ts_code", 1)], {}),
        ([("trade_date", 1), ("step", -1)], {}),
    ]),
    ("sector_limit", "review_sector_limit", "get_limit_cpt_list", [
        ([("trade_date", 1), ("ts_code", 1)], {}),
        ([("trade_date", 1), ("up_num", -1)], {}),
    ]),
    ("sector_daily", "review_sector_daily", "get_ths_daily", [
        ([("trade_date", 1), ("ts_code", 1)], {}),
        ([("trade_date", 1), ("pct_change", -1)], {}),
    ]),
    ("dragon", "review_dragon", "get_top_inst", [
        ([("trade_date", 1), ("ts_code", 1)], {}),
        ([("trade_date", 1), ("net_buy", -1)], {}),
        ([("exalter", 1)], {}),
    ]),
    ("hot", "review_hot", "get_ths_hot", [
        ([("trade_date", 1), ("ts_code", 1)], {}),
        ([("trade_date", 1), ("rank", 1)], {}),
        ([("trade_date", 1), ("hot", -1)], {}),
    ]),
    ("northbound", "review_northbound", "get_moneyflow_hsgt", [
        ([("trade_date", 1)], {}),
    ]),
]


class ReviewDataCollector(BaseCollector):
    """
    每日复盘数据采集器
    
    采集连板天梯、板块强弱、龙虎榜、热股等复盘数据。
    支持失败自动记录和重试。
    
    调度时间:
    - 默认: 每个交易日 19:30（收盘后数据稳定）
    """
    
    name = "review_data"
    description = "采集每日复盘数据（连板/龙虎榜/热股等）"
    default_schedule = "30 19 * * 1-5"
    
    INITIAL_SYNC_DAYS = 60
    MAX_CONCURRENT = 5
    _indexes_created = False  # 类级别标记，避免重复创建索引
    
    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "review_data_schedule", None) or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if not latest_trade_date:
            latest_trade_date = datetime.now().strftime("%Y%m%d")
        
        # 首次运行时采集历史数据
        has_synced_before = await self._has_synced_before()
        if not has_synced_before:
            self.logger.info("No review_data sync records found, collecting initial history...")
            await self._collect_initial_history()
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Review data {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        self.logger.info(f"Starting review data collection for {latest_trade_date}...")
        
        # 确保索引存在（只在首次执行）
        await self._ensure_indexes()
        
        # 采集当天数据
        stats, errors = await self._collect_single_date(latest_trade_date)
        total_count = sum(stats.values())
        
        # 记录同步完成
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=latest_trade_date,
            count=total_count,
        )
        
        return {
            "trade_date": latest_trade_date,
            "count": total_count,
            "stats": stats,
            "errors": errors,
            "message": f"Collected {total_count} review records for {latest_trade_date}",
        }
    
    async def _collect_single_date(self, trade_date: str) -> Tuple[Dict[str, int], List[str]]:
        """采集单个日期的所有数据"""
        stats = {}
        errors = []
        
        for name, collection_name, api_method, _ in REVIEW_SUB_COLLECTORS:
            try:
                count = await self._collect_sub_data(trade_date, collection_name, api_method)
                stats[name] = count
                self.logger.debug(f"  {name}: {count} records")
            except Exception as e:
                self.logger.error(f"Failed to collect {name}: {e}")
                errors.append(f"{name}: {str(e)}")
                # 记录失败
                await self._record_failure(f"{trade_date}:{name}", str(e))
        
        return stats, errors
    
    async def _collect_sub_data(self, trade_date: str, collection_name: str, api_method: str) -> int:
        """通用子数据采集"""
        # 动态调用 data_source_manager 的方法
        api_func = getattr(data_source_manager, api_method)
        data, _ = await api_func(trade_date=trade_date)
        
        if not data:
            return 0
        
        db = mongo_manager.db
        collection = db[collection_name]
        
        # 删除当天旧数据并插入新数据
        await collection.delete_many({"trade_date": trade_date})
        
        for item in data:
            item["collected_at"] = datetime.now(timezone.utc)
        
        await collection.insert_many(data)
        
        return len(data)
    
    async def _ensure_indexes(self) -> None:
        """确保所有集合的索引存在（只创建一次）"""
        if ReviewDataCollector._indexes_created:
            return
        
        self.logger.info("Creating review data indexes...")
        db = mongo_manager.db
        
        for name, collection_name, _, indexes in REVIEW_SUB_COLLECTORS:
            collection = db[collection_name]
            for index_keys, index_opts in indexes:
                try:
                    await collection.create_index(index_keys, **index_opts, background=True)
                except Exception as e:
                    self.logger.warning(f"Failed to create index on {collection_name}: {e}")
        
        ReviewDataCollector._indexes_created = True
        self.logger.info("Review data indexes created")
    
    async def _has_synced_before(self) -> bool:
        """检查是否曾经同步过"""
        try:
            db = mongo_manager.db
            count = await db["sync_records"].count_documents({"sync_type": self.name})
            return count > 0
        except Exception as e:
            self.logger.error(f"Failed to check sync records: {e}")
            return False
    
    async def _collect_initial_history(self) -> Dict[str, Any]:
        """首次运行时采集历史数据"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.INITIAL_SYNC_DAYS)
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        
        self.logger.info(f"Collecting initial history: {start_str} ~ {end_str}")
        
        # 确保索引存在
        await self._ensure_indexes()
        
        # 使用基类方法获取交易日列表
        trade_dates = await self._get_trade_dates(start_str, end_str)
        
        if not trade_dates:
            return {"error": "No trade dates found"}
        
        self.logger.info(f"Trade dates to collect: {len(trade_dates)}")
        
        total_records = 0
        
        async def collect_single_day(trade_date: str) -> int:
            nonlocal total_records
            stats, _ = await self._collect_single_date(trade_date)
            count = sum(stats.values())
            total_records += count
            await asyncio.sleep(0.2)  # API 限流
            return count
        
        # 使用基类并行采集方法
        result = await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_single_day,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        
        self.logger.info(f"Initial history complete: {total_records} records from {result['success']} days")
        return {"days_collected": result["success"], "total_records": total_records}
    
    async def collect_history(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """采集历史数据（外部调用接口）"""
        await self._ensure_indexes()
        trade_dates = await self._get_trade_dates(start_date, end_date)
        
        if not trade_dates:
            return []
        
        results = []
        
        async def collect_and_record(trade_date: str) -> Dict[str, Any]:
            stats, errors = await self._collect_single_date(trade_date)
            result = {"trade_date": trade_date, "stats": stats, "errors": errors}
            results.append(result)
            await asyncio.sleep(0.2)
            return sum(stats.values())
        
        await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_and_record,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        
        return results
