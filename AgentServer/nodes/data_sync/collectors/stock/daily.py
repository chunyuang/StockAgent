"""
日线数据采集器

支持增量同步和失败重试：
- 首次同步：从 2003-01-27 开始同步所有历史数据
- 增量同步：从上次同步日期同步到今天
- 已同步：如果今天已同步则跳过

注意：Tushare API 每次调用最多返回 6000 条数据，
历史数据（20多年）可能接近此限制，因此首次同步需要逐只股票获取。
"""

from typing import Dict, Any, List

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class StockDailyCollector(BaseCollector):
    """
    日线数据采集器
    
    采集所有股票的日线行情数据。支持失败自动重试。
    
    Tushare API 限制:
    - 每次调用最多返回 6000 条数据
    - 历史数据跨度大时，需要单只股票逐个获取
    - 增量同步（少量天数）可以批量获取
    
    调度时间:
    - 可通过 SYNC_STOCK_DAILY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 15:30 (收盘后)
    """
    
    name = "stock_daily"
    description = "采集股票日线数据"
    default_schedule = "30 15 * * 1-5"
    
    # 配置（覆盖基类默认值）
    HISTORY_START_DATE = "20030127"
    HISTORY_SYNC_DAYS_THRESHOLD = 30
    WRITE_BATCH_SIZE = 1000
    
    # 批次大小 - 根据同步类型动态调整
    FETCH_BATCH_SIZE_HISTORY = 1       # 历史同步：每批 1 只股票（数据量大）
    FETCH_BATCH_SIZE_INCREMENTAL = 500 # 增量同步：每批 500 只股票
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.stock_daily_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Stock daily {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        # 获取所有股票代码
        stocks = await mongo_manager.find_many(
            "stock_basic",
            {"list_status": "L"},
            projection={"ts_code": 1},
        )
        
        if not stocks:
            return {"count": 0, "message": "No stocks found"}
        
        ts_codes = [s["ts_code"] for s in stocks]
        
        # 使用基类方法确定同步范围
        sync_info = await self._determine_sync_range(latest_trade_date)
        
        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        start_date, end_date, is_history_sync = sync_info
        
        # 根据同步类型选择批次大小
        fetch_batch_size = (
            self.FETCH_BATCH_SIZE_HISTORY 
            if is_history_sync 
            else self.FETCH_BATCH_SIZE_INCREMENTAL
        )
        
        sync_type_desc = "历史同步" if is_history_sync else "增量同步"
        self.logger.info(
            f"[{sync_type_desc}] Syncing stock daily: {start_date} -> {end_date} "
            f"({len(ts_codes)} stocks, batch_size={fetch_batch_size})"
        )
        
        # 将股票代码按批次分组
        batches = [
            ts_codes[i:i + fetch_batch_size] 
            for i in range(0, len(ts_codes), fetch_batch_size)
        ]
        
        total_count = 0
        
        async def collect_batch(batch: List[str]) -> int:
            """采集一批股票的数据并立即写入"""
            nonlocal total_count
            ts_code_str = ",".join(batch)
            records, _ = await data_source_manager.get_daily(
                ts_code=ts_code_str,
                start_date=start_date,
                end_date=end_date,
            )
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="stock_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                return count
            return 0
        
        # 使用基类并行采集方法，每批次采集后立即写入
        result = await self._parallel_collect(
            items=batches,
            collect_func=collect_batch,
            max_concurrent=3,
            retry_failures=True,
            item_id_func=lambda b: f"batch_{b[0]}",
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
            "success_batches": result["success"],
            "failed_batches": result["failed"],
            "message": f"[{sync_type_desc}] Synced {total_count} records ({result['success']}/{result['total']} batches)",
        }