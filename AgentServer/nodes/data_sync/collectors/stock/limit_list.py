"""
涨跌停数据采集器

使用日期同步策略：
- 如果没有同步记录，从前30天开始同步
- 增量同步：从上次同步日期的下一天同步到今天
- 已同步：如果今天已同步则跳过
- 支持失败自动重试

数据来源: 每日涨跌停统计 (limit_list_d)
"""

from typing import Dict, Any, List
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class LimitListCollector(BaseCollector):
    """
    涨跌停数据采集器
    
    采集每日涨跌停统计数据。
    
    同步策略:
    - 首次同步：从前30天开始同步
    - 增量同步：从上次同步日期的下一天同步到今天
    - 已同步：如果今天已同步则跳过
    - 失败自动记录并在下次运行时重试
    
    调度时间:
    - 可通过 SYNC_LIMIT_LIST_SCHEDULE 环境变量配置
    - 默认: 每个交易日 16:10 (收盘后)
    """
    
    name = "limit_list"
    description = "采集涨跌停统计数据"
    default_schedule = "10 16 * * 1-5"
    
    # 配置 (继承自 BaseCollector 的可覆盖)
    INITIAL_SYNC_DAYS = 30
    WRITE_BATCH_SIZE = 1000
    MAX_CONCURRENT = 3  # limit_list API 限流较严格
    API_INTERVAL = 0.5  # API 调用间隔（秒）
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.limit_list_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Limit list {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        # 使用基类方法确定同步范围
        sync_info = await self._determine_sync_range_simple(latest_trade_date)
        
        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        start_date, end_date = sync_info
        
        # 获取交易日列表
        trade_dates = await self._get_trade_dates(start_date, end_date)
        
        if not trade_dates:
            return {"count": 0, "message": "No trade dates in range"}
        
        self.logger.info(f"Syncing limit list: {start_date} -> {end_date} ({len(trade_dates)} dates)")
        
        # 使用并行采集（带失败重试）
        all_records: List[Dict[str, Any]] = []
        
        async def collect_single_date(trade_date: str) -> int:
            """采集单个日期的数据"""
            records, _ = await data_source_manager.get_limit_list(trade_date=trade_date)
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
        
        # 批量写入
        total_count = 0
        if all_records:
            total_count = await self._write_buffer(
                buffer=all_records,
                collection="limit_list",
                key_fields=["ts_code", "trade_date"],
            )
        
        # 记录同步完成
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
