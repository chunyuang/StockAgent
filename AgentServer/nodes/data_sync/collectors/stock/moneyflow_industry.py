"""
行业资金流向采集器

使用日期同步策略，支持并行采集和失败重试。
数据来源: 同花顺行业资金流向 (moneyflow_ind_ths)
"""

from typing import Dict, Any, List
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class MoneyflowIndustryCollector(BaseCollector):
    """
    行业资金流向采集器
    
    采集同花顺行业资金流向数据。支持并行采集和失败自动重试。
    
    调度时间:
    - 可通过 SYNC_MONEYFLOW_INDUSTRY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 16:00 (收盘后)
    """
    
    name = "moneyflow_industry"
    description = "采集行业资金流向数据"
    default_schedule = "0 16 * * 1-5"
    
    INITIAL_SYNC_DAYS = 30
    WRITE_BATCH_SIZE = 1000
    MAX_CONCURRENT = 5
    API_INTERVAL = 0.2
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.moneyflow_industry_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Moneyflow industry {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        sync_info = await self._determine_sync_range_simple(latest_trade_date)
        
        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        start_date, end_date = sync_info
        trade_dates = await self._get_trade_dates(start_date, end_date)
        
        if not trade_dates:
            return {"count": 0, "message": "No trade dates in range"}
        
        self.logger.info(f"Syncing moneyflow industry: {start_date} -> {end_date} ({len(trade_dates)} dates)")
        
        all_records: List[Dict[str, Any]] = []
        
        async def collect_single_date(trade_date: str) -> int:
            records, _ = await data_source_manager.get_moneyflow_industry(trade_date=trade_date)
            if records:
                all_records.extend(records)
            await asyncio.sleep(self.API_INTERVAL)
            return len(records) if records else 0
        
        result = await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_single_date,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        
        total_count = 0
        if all_records:
            total_count = await self._write_buffer(
                buffer=all_records,
                collection="moneyflow_industry",
                key_fields=["ts_code", "trade_date"],
            )
        
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=end_date,
            count=total_count,
        )
        
        return {
            "count": total_count,
            "start_date": start_date,
            "end_date": end_date,
            "success_dates": result["success"],
            "failed_dates": result["failed"],
            "message": f"Synced {total_count} records ({result['success']}/{result['total']} dates)",
        }
