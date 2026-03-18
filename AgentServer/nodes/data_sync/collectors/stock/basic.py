"""
股票基础信息采集器

采集股票基础信息，并合并最新交易日的指标数据（PE/PB/市值/换手率等）。
"""

from typing import Dict, Any
from datetime import datetime, date

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


def _add_financial_metrics(doc: Dict, daily_metrics: Dict) -> None:
    """
    将财务与交易指标写入 doc（就地修改）。
    - 市值：total_mv/circ_mv（从万元转换为亿元）
    - 估值：pe/pb/pe_ttm/ps/ps_ttm（过滤 NaN/None）
    - 交易：turnover_rate/volume_ratio（过滤 NaN/None）
    - 股本：total_share/float_share（万股，过滤 NaN/None）
    """
    # 市值（万元 -> 亿元）
    for field in ["total_mv", "circ_mv"]:
        if field in daily_metrics and daily_metrics[field] is not None:
            try:
                value = float(daily_metrics[field])
                if value == value:  # 非 NaN
                    doc[field] = value / 10000
            except (ValueError, TypeError):
                pass

    # 估值指标 (保留字段，即使为空也存储 None)
    for field in ["pe", "pb", "pe_ttm", "ps", "ps_ttm", "dv_ratio", "dv_ttm"]:
        if field in daily_metrics:
            val = daily_metrics[field]
            if val is None:
                doc[field] = None
            else:
                try:
                    value = float(val)
                    doc[field] = value if value == value else None
                except (ValueError, TypeError):
                    doc[field] = None

    # 交易指标
    for field in ["turnover_rate", "volume_ratio"]:
        if field in daily_metrics and daily_metrics[field] is not None:
            try:
                value = float(daily_metrics[field])
                if value == value:
                    doc[field] = value
            except (ValueError, TypeError):
                pass

    # 股本数据（万股）
    for field in ["total_share", "float_share"]:
        if field in daily_metrics and daily_metrics[field] is not None:
            try:
                value = float(daily_metrics[field])
                if value == value:
                    doc[field] = value
            except (ValueError, TypeError):
                pass


class StockBasicCollector(BaseCollector):
    """
    股票基础信息采集器
    
    采集所有上市股票的基础信息和最新估值指标。
    
    调度时间:
    - 可通过 SYNC_STOCK_BASIC_SCHEDULE 环境变量配置
    - 默认: 每个交易日 9:00
    """
    
    name = "stock_basic"
    description = "采集股票基础信息和估值指标"
    default_schedule = "0 9 * * 1-5"
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.stock_basic_schedule or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        today = date.today().strftime("%Y%m%d")
        
        if await mongo_manager.is_synced("stock_basic", today):
            self.logger.info(f"Stock basic {today} already synced, skipping")
            return {"count": 0, "message": f"Already synced {today}", "skipped": True}
        
        # Step 1: 获取股票基础信息
        records, source = await data_source_manager.get_stock_basic()
        
        if not records:
            return {"count": 0, "message": "No data"}
        
        self.logger.info(f"Fetched {len(records)} stocks from {source}")
        
        # Step 2: 获取最新交易日的 daily_basic 数据
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        daily_basic_map: Dict[str, Dict] = {}
        
        if latest_trade_date:
            daily_basic, _ = await data_source_manager.get_daily_basic(trade_date=latest_trade_date)
            if daily_basic:
                daily_basic_map = {item["ts_code"]: item for item in daily_basic if item.get("ts_code")}
                self.logger.info(f"Fetched {len(daily_basic_map)} daily_basic for {latest_trade_date}")
        
        # Step 3: 合并数据
        merged_count = 0
        for record in records:
            ts_code = record.get("ts_code")
            record["updated_at"] = datetime.utcnow()
            
            if ts_code and ts_code in daily_basic_map:
                _add_financial_metrics(record, daily_basic_map[ts_code])
                merged_count += 1
        
        # Step 4: 使用基类方法批量写入
        total_count = await self._write_buffer(
            buffer=records,
            collection="stock_basic",
            key_fields=["ts_code"],
        )
        
        # 记录同步完成
        await mongo_manager.record_sync(
            sync_type="stock_basic",
            sync_date=today,
            count=total_count,
        )
        
        return {
            "count": total_count,
            "merged": merged_count,
            "message": f"Synced {total_count} stocks with {merged_count} metrics",
        }
