"""
财务数据采集器

采集上市公司完整财务数据：
- 利润表 (income)
- 资产负债表 (balance_sheet)  
- 现金流量表 (cashflow)
- 财务指标 (fina_indicator)

初始化模式：同步5年历史数据
增量模式：同步最近8个季度数据
"""

from typing import Dict, Any
from datetime import datetime, date

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


# 财务数据集合配置
FINA_COLLECTIONS = [
    ("income_statement", "fina_income", ["ts_code", "end_date"]),
    ("balance_sheet", "fina_balance", ["ts_code", "end_date"]),
    ("cashflow_statement", "fina_cashflow", ["ts_code", "end_date"]),
    ("financial_indicators", "fina_indicator", ["ts_code", "end_date"]),
]


class FinaIndicatorCollector(BaseCollector):
    """
    财务数据采集器
    
    采集上市公司的完整财务数据（三大报表 + 财务指标）。
    支持失败自动重试。
    
    调度时间:
    - 可通过 SYNC_FINA_INDICATOR_SCHEDULE 环境变量配置
    - 默认: 每月1号 09:00
    """
    
    name = "fina_indicator"
    description = "采集财务数据 (三大报表 + 财务指标)"
    default_schedule = "0 9 1 * *"
    
    MAX_CONCURRENT = 10
    _indexes_created = False
    
    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, 'fina_indicator_schedule', None) or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行增量采集 (获取每只股票最近8个季度的财务数据)"""
        today = date.today().strftime("%Y%m%d")
        
        if await mongo_manager.is_synced("fina_indicator", today, granularity="month"):
            self.logger.info(f"Fina indicator {today[:6]} already synced this month, skipping")
            return {"count": 0, "message": f"Already synced this month ({today[:6]})", "skipped": True}
        
        self.logger.info("Collecting fina_indicator (latest 8 quarters per stock)")
        
        result = await self._sync_all_stocks(limit=8)
        
        await mongo_manager.record_sync(
            sync_type="fina_indicator",
            sync_date=today,
            count=result["count"],
        )
        
        return result
    
    async def init_sync(self, years: int = 5) -> Dict[str, Any]:
        """初始化同步：同步所有股票的历史财务数据"""
        quarters = years * 4
        self.logger.info(f"Init sync fina_indicator: last {quarters} quarters ({years} years)")
        
        result = await self._sync_all_stocks(limit=quarters, include_delisted=True)
        await self._ensure_indexes()
        
        return result
    
    async def _sync_all_stocks(
        self, 
        limit: int = 8,
        include_delisted: bool = False,
    ) -> Dict[str, Any]:
        """同步所有股票的财务数据"""
        query = {} if include_delisted else {"list_status": "L"}
        stocks = await mongo_manager.find_many(
            "stock_basic",
            query,
            projection={"ts_code": 1},
        )
        ts_codes = [s["ts_code"] for s in stocks]
        
        if not ts_codes:
            self.logger.warning("No stocks found in stock_basic, please sync stock_basic first")
            return {"count": 0, "success": 0, "error": 0, "message": "No stocks in database"}
        
        self.logger.info(f"Syncing {len(ts_codes)} stocks (limit={limit} per stock)...")
        
        # 确保索引存在
        await self._ensure_indexes()
        
        record_counts = {"income": 0, "balance": 0, "cashflow": 0, "indicator": 0}
        
        async def process_stock(ts_code: str) -> int:
            """处理单只股票的财务数据"""
            financial_data, _ = await data_source_manager.get_financial_data(
                ts_code=ts_code,
                limit=limit,
            )
            
            if not financial_data:
                return 0
            
            now = datetime.utcnow()
            total = 0
            
            for data_key, collection_name, key_fields in FINA_COLLECTIONS:
                records = financial_data.get(data_key, [])
                if records:
                    for r in records:
                        r["updated_at"] = now
                    await self._write_buffer(
                        buffer=records,
                        collection=collection_name,
                        key_fields=key_fields,
                        batch_size=500,
                    )
                    total += len(records)
                    
                    # 更新统计
                    if "income" in data_key:
                        record_counts["income"] += len(records)
                    elif "balance" in data_key:
                        record_counts["balance"] += len(records)
                    elif "cashflow" in data_key:
                        record_counts["cashflow"] += len(records)
                    else:
                        record_counts["indicator"] += len(records)
            
            return total
        
        # 使用基类并行采集方法
        result = await self._parallel_collect(
            items=ts_codes,
            collect_func=process_stock,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        
        total_records = sum(record_counts.values())
        self.logger.info(
            f"Sync completed: success={result['success']}, error={result['failed']}, total={total_records}"
        )
        self.logger.info(
            f"  Income: {record_counts['income']}, Balance: {record_counts['balance']}, "
            f"Cashflow: {record_counts['cashflow']}, Indicator: {record_counts['indicator']}"
        )
        
        return {
            "count": total_records,
            "success": result["success"],
            "error": result["failed"],
            "details": record_counts,
            "message": f"Synced {total_records} records from {result['success']} stocks",
        }
    
    async def _ensure_indexes(self) -> None:
        """确保所有财务数据表的索引存在（只创建一次）"""
        if FinaIndicatorCollector._indexes_created:
            return
        
        self.logger.info("Creating fina indexes...")
        
        for _, collection_name, key_fields in FINA_COLLECTIONS:
            await mongo_manager.create_index(
                collection_name,
                [(key_fields[0], 1), (key_fields[1], -1)],
                unique=True,
            )
            await mongo_manager.create_index(collection_name, [(key_fields[1], -1)])
            await mongo_manager.create_index(collection_name, [(key_fields[0], 1)])
        
        FinaIndicatorCollector._indexes_created = True
        self.logger.info("Fina indexes created")
