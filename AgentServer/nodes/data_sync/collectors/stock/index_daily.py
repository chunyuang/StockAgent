"""
指数日线数据采集器

只同步三个核心指数：
- 000001.SH 上证指数
- 399001.SZ 深证成指  
- 399006.SZ 创业板指

支持增量同步和失败重试。
"""

from typing import Dict, Any, List

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class IndexDailyCollector(BaseCollector):
    """
    指数日线数据采集器
    
    采集核心指数的日线行情数据。支持失败自动重试。
    
    调度时间:
    - 可通过 SYNC_INDEX_DAILY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 15:35 (收盘后)
    """
    
    name = "index_daily"
    description = "采集指数日线数据"
    default_schedule = "35 15 * * 1-5"
    
    # 配置（覆盖基类默认值）
    HISTORY_START_DATE = "20030127"
    HISTORY_SYNC_DAYS_THRESHOLD = 30
    WRITE_BATCH_SIZE = 1000
    MAX_CONCURRENT = 3
    
    # 核心指数列表
    CORE_INDICES = [
        "000001.SH",  # 上证指数
        "399001.SZ",  # 深证成指
        "399006.SZ",  # 创业板指
    ]
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.index_daily_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Index daily {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        # 使用基类方法确定同步范围
        sync_info = await self._determine_sync_range(latest_trade_date)
        
        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        start_date, end_date, is_history_sync = sync_info
        sync_type_desc = "历史同步" if is_history_sync else "增量同步"
        
        self.logger.info(
            f"[{sync_type_desc}] Syncing index daily: {start_date} -> {end_date} "
            f"({len(self.CORE_INDICES)} indices)"
        )
        
        total_count = 0
        
        async def collect_single_index(ts_code: str) -> int:
            """采集单个指数的数据并立即写入"""
            nonlocal total_count
            records, _ = await data_source_manager.get_index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="index_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                return count
            return 0
        
        # 使用基类并行采集方法，每个指数采集后立即写入
        result = await self._parallel_collect(
            items=self.CORE_INDICES,
            collect_func=collect_single_index,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
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
            "sync_type": sync_type_desc,
            "success": result["success"],
            "failed": result["failed"],
            "message": f"[{sync_type_desc}] Synced {total_count} records ({result['success']}/{result['total']} indices)",
        }
