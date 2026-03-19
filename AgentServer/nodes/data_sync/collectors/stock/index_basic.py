"""
指数基础信息采集器

同步主要市场的指数基础信息：
- SSE: 上交所指数
- SZSE: 深交所指数
- SW: 申万指数
- CSI: 中证指数
"""

from typing import Dict, Any, List
from datetime import date
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class IndexBasicCollector(BaseCollector):
    """
    指数基础信息采集器
    
    采集所有主要市场指数的基础信息。
    
    调度时间:
    - 可通过 SYNC_INDEX_BASIC_SCHEDULE 环境变量配置
    - 默认: 每个交易日 9:00
    """
    
    name = "index_basic"
    description = "采集指数基础信息"
    default_schedule = "0 9 * * 1-5"
    
    MARKETS = ["SSE", "SZSE", "SW", "CSI"]
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.index_basic_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        today = date.today().strftime("%Y%m%d")
        
        if await mongo_manager.is_synced("index_basic", today):
            self.logger.info(f"Index basic {today} already synced, skipping")
            return {"count": 0, "message": f"Already synced {today}", "skipped": True}
        
        total_count = 0
        
        async def collect_market(market: str) -> int:
            """采集单个市场的指数并立即写入"""
            nonlocal total_count
            records, source = await data_source_manager.get_index_basic(market=market)
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="index_basic",
                    key_fields=["ts_code"],
                )
                total_count += count
                self.logger.info(f"  {market}: {count} indices")
                return count
            return 0
        
        self.logger.info("Collecting index basic from all markets...")
        
        # 使用基类并行采集方法，每个市场采集后立即写入
        result = await self._parallel_collect(
            items=self.MARKETS,
            collect_func=collect_market,
            max_concurrent=4,
            retry_failures=True,
        )
        
        if total_count == 0:
            return {"count": 0, "message": "No data"}
        
        # 记录同步完成
        await mongo_manager.record_sync(
            sync_type="index_basic",
            sync_date=today,
            count=total_count,
        )
        
        return {
            "count": total_count,
            "markets": result["success"],
            "message": f"Synced {total_count} indices from {result['success']} markets",
        }
