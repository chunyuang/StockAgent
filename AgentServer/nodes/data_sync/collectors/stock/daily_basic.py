"""
每日指标数据采集器

采集每日指标数据（PE/PB/换手率/市值等），用于因子选股回测。
支持并行采集和失败自动重试。

字段说明：
- ts_code: 股票代码
- trade_date: 交易日期
- close: 收盘价
- turnover_rate: 换手率（%）
- turnover_rate_f: 换手率（自由流通股）
- volume_ratio: 量比
- pe: 市盈率（总市值/净利润，亏损为空）
- pe_ttm: 市盈率TTM（总市值/滚动净利润）
- pb: 市净率
- ps: 市销率
- ps_ttm: 市销率TTM
- dv_ratio: 股息率（%）
- dv_ttm: 股息率TTM（%）
- total_share: 总股本（万股）
- float_share: 流通股本（万股）
- free_share: 自由流通股本（万股）
- total_mv: 总市值（亿元，已转换）
- circ_mv: 流通市值（亿元，已转换）
"""

from typing import Dict, Any
from datetime import datetime

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


def _clean_daily_basic_record(record: Dict) -> Dict:
    """
    清洗 daily_basic 记录
    
    参考 stock_basic.py 的 _add_financial_metrics 逻辑:
    - 市值：从万元转换为亿元
    - 估值：过滤 NaN/None，亏损公司保留 None
    - 交易指标：过滤 NaN
    """
    cleaned = {
        "ts_code": record.get("ts_code"),
        "trade_date": record.get("trade_date"),
    }
    
    # 收盘价
    if "close" in record and record["close"] is not None:
        try:
            value = float(record["close"])
            if value == value:  # 非 NaN
                cleaned["close"] = value
        except (ValueError, TypeError):
            pass
    
    # 市值（万元 -> 亿元）
    for field in ["total_mv", "circ_mv"]:
        if field in record and record[field] is not None:
            try:
                value = float(record[field])
                if value == value:  # 非 NaN
                    cleaned[field] = value / 10000  # 转换为亿元
            except (ValueError, TypeError):
                pass
    
    # 估值指标 (保留字段，即使为空也存储 None，因为亏损公司 PE 就是空)
    for field in ["pe", "pb", "pe_ttm", "ps", "ps_ttm", "dv_ratio", "dv_ttm"]:
        if field in record:
            val = record[field]
            if val is None:
                cleaned[field] = None
            else:
                try:
                    value = float(val)
                    if value == value:  # 非 NaN
                        cleaned[field] = value
                    else:
                        cleaned[field] = None
                except (ValueError, TypeError):
                    cleaned[field] = None
    
    # 交易指标
    for field in ["turnover_rate", "turnover_rate_f", "volume_ratio"]:
        if field in record and record[field] is not None:
            try:
                value = float(record[field])
                if value == value:  # 非 NaN
                    cleaned[field] = value
            except (ValueError, TypeError):
                pass
    
    # 股本数据（万股，保持原单位）
    for field in ["total_share", "float_share", "free_share"]:
        if field in record and record[field] is not None:
            try:
                value = float(record[field])
                if value == value:  # 非 NaN
                    cleaned[field] = value
            except (ValueError, TypeError):
                pass
    
    return cleaned


class DailyBasicCollector(BaseCollector):
    """
    每日指标数据采集器
    
    采集所有股票的每日指标数据（PE/PB/换手率/市值等）。
    支持并行采集和失败自动重试。
    
    数据清洗:
    - 市值从万元转换为亿元
    - 过滤 NaN 值
    - 亏损公司 PE 保留 None
    
    调度时间:
    - 可通过 SYNC_DAILY_BASIC_SCHEDULE 环境变量配置
    - 默认: 每个交易日 16:00 (收盘后)
    """
    
    name = "daily_basic"
    description = "采集股票每日指标数据（PE/PB/换手率/市值等）"
    default_schedule = "0 16 * * 1-5"
    
    # 配置（覆盖基类默认值）
    HISTORY_START_DATE = "20180101"
    HISTORY_SYNC_DAYS_THRESHOLD = 30
    WRITE_BATCH_SIZE = 5000
    MAX_CONCURRENT = 3
    
    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, 'daily_basic_schedule', None) or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if not latest_trade_date:
            return {"count": 0, "message": "Cannot get latest trade date"}
        
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            self.logger.info(f"Daily basic {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        # 使用基类方法确定同步范围
        sync_info = await self._determine_sync_range(latest_trade_date)
        
        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}
        
        start_date, end_date, is_history_sync = sync_info
        sync_type_desc = "历史同步" if is_history_sync else "增量同步"
        
        # 使用基类方法获取交易日列表
        trade_dates = await self._get_trade_dates(start_date, end_date)
        
        if not trade_dates:
            return {"count": 0, "message": "No trade dates found in range"}
        
        self.logger.info(f"[{sync_type_desc}] Syncing daily_basic: {start_date} -> {end_date} ({len(trade_dates)} dates)")
        
        total_count = 0
        
        async def collect_single_date(trade_date: str) -> int:
            """采集单个日期的数据"""
            nonlocal total_count
            
            records, _ = await data_source_manager.get_daily_basic(trade_date=trade_date)
            
            if records:
                cleaned_records = []
                for record in records:
                    cleaned = _clean_daily_basic_record(record)
                    cleaned["updated_at"] = datetime.utcnow()
                    cleaned_records.append(cleaned)
                
                # 直接写入（避免内存问题）
                count = await self._write_buffer(
                    buffer=cleaned_records,
                    collection="daily_basic",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                return count
            return 0
        
        # 使用基类并行采集方法（带失败重试）
        result = await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_single_date,
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
            "success_dates": result["success"],
            "failed_dates": result["failed"],
            "message": f"[{sync_type_desc}] Synced {total_count} records ({result['success']}/{result['total']} dates)",
        }
