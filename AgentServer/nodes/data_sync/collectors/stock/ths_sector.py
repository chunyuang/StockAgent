"""
同花顺板块数据采集器

采集板块列表和成分股，建立个股-板块双向映射。
支持并行采集和失败重试。

数据来源:
- ths_index: 同花顺板块列表（概念/行业）
- ths_member: 板块成分股

存储集合:
- ths_sectors: 板块列表
- stock_sector_map: 个股 -> 板块列表
- sector_stocks: 板块 -> 成分股列表
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers import data_source_manager, mongo_manager


class ThsSectorCollector(BaseCollector):
    """
    同花顺板块采集器
    
    采集板块列表和成分股，建立双向映射。
    支持并行采集成分股数据。
    
    调度时间:
    - 默认: 每周六凌晨2点
    """
    
    name = "ths_sector"
    description = "采集同花顺板块和成分股映射"
    default_schedule = "0 2 * * 6"
    
    SECTOR_TYPES = ["N", "I"]  # N-概念, I-行业
    SYNC_INTERVAL_DAYS = 7  # 同步间隔天数
    MAX_CONCURRENT = 10  # 成分股采集并发数
    
    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "ths_sector_schedule", None) or self.default_schedule
    
    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        # 检查是否需要更新
        if not await self._should_update():
            self.logger.info("THS sector data is up to date, skipping")
            return {"count": 0, "message": "Already synced this week", "skipped": True}
        
        self.logger.info("Starting THS sector collection...")
        
        # 1. 采集板块列表
        sector_stats = await self._collect_sectors()
        
        # 2. 并行采集成分股并建立映射
        mapping_stats = await self._collect_members_parallel()
        
        # 3. 记录同步时间
        today = datetime.now().strftime("%Y%m%d")
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=today,
            count=mapping_stats["stocks_mapped"],
        )
        
        return {
            "count": mapping_stats["stocks_mapped"],
            "sectors": sector_stats,
            "mapping": mapping_stats,
            "message": f"Collected {sum(sector_stats.values())} sectors, mapped {mapping_stats['stocks_mapped']} stocks",
        }
    
    async def _should_update(self) -> bool:
        """检查是否需要更新（N天内已同步则跳过）"""
        last_sync_date = await mongo_manager.get_last_sync_date(self.name)
        
        if not last_sync_date:
            return True
        
        try:
            last_sync = datetime.strptime(last_sync_date, "%Y%m%d")
            days_since_sync = (datetime.now() - last_sync).days
            
            if days_since_sync < self.SYNC_INTERVAL_DAYS:
                self.logger.debug(f"Last sync was {days_since_sync} days ago, skipping")
                return False
            return True
        except Exception:
            return True
    
    async def _collect_sectors(self) -> Dict[str, int]:
        """采集板块列表"""
        self.logger.info("Collecting sector list...")
        
        stats = {"概念": 0, "行业": 0}
        all_sectors = []
        
        for sector_type in self.SECTOR_TYPES:
            type_name = "概念" if sector_type == "N" else "行业"
            
            sectors, _ = await data_source_manager.get_ths_index(exchange="A", type=sector_type)
            
            if sectors:
                for sector in sectors:
                    sector["sector_type"] = sector_type
                    sector["type_name"] = type_name
                    sector["updated_at"] = datetime.utcnow()
                
                all_sectors.extend(sectors)
                stats[type_name] = len(sectors)
                self.logger.info(f"  {type_name}板块: {len(sectors)} 个")
            
            await asyncio.sleep(0.5)
        
        # 使用 bulk_upsert 替代 delete + insert（更安全）
        if all_sectors:
            await self._write_buffer(
                buffer=all_sectors,
                collection="ths_sectors",
                key_fields=["ts_code"],
            )
            
            # 创建索引
            db = mongo_manager.db
            collection = db["ths_sectors"]
            await collection.create_index("sector_type", background=True)
            await collection.create_index("name", background=True)
        
        return stats
    
    async def _collect_members_parallel(self) -> Dict[str, int]:
        """并行采集板块成分股，建立双向映射"""
        self.logger.info("Collecting sector members (parallel)...")
        
        db = mongo_manager.db
        
        # 获取所有板块
        sectors = await db["ths_sectors"].find(
            {}, {"ts_code": 1, "name": 1}
        ).to_list(None)
        
        self.logger.info(f"Processing {len(sectors)} sectors...")
        
        # 用于构建双向映射（线程安全需要锁）
        stock_to_sectors: Dict[str, List[Dict[str, str]]] = {}
        sector_to_stocks: Dict[str, List[Dict[str, str]]] = {}
        lock = asyncio.Lock()
        
        async def collect_single_sector(sector: Dict) -> int:
            """采集单个板块的成分股"""
            sector_code = sector["ts_code"]
            sector_name = sector["name"]
            
            members, _ = await data_source_manager.get_ths_member(ts_code=sector_code)
            
            if not members:
                return 0
            
            stocks_list = []
            
            async with lock:
                sector_to_stocks[sector_code] = []
                
                for member in members:
                    stock_code = member.get("code", "")
                    stock_name = member.get("name", "")
                    
                    if not stock_code:
                        continue
                    
                    # 板块 -> 成分股
                    sector_to_stocks[sector_code].append({
                        "code": stock_code,
                        "name": stock_name,
                        "weight": member.get("weight"),
                        "in_date": member.get("in_date"),
                    })
                    
                    # 个股 -> 板块
                    if stock_code not in stock_to_sectors:
                        stock_to_sectors[stock_code] = []
                    
                    stock_to_sectors[stock_code].append({
                        "ts_code": sector_code,
                        "name": sector_name,
                    })
            
            await asyncio.sleep(0.2)  # API 限流
            return len(members)
        
        # 使用基类并行采集方法
        result = await self._parallel_collect(
            items=sectors,
            collect_func=collect_single_sector,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
            item_id_func=lambda s: s["ts_code"],
        )
        
        # 写入 stock_sector_map
        self.logger.info("Writing stock_sector_map...")
        stock_docs = [
            {
                "code": stock_code,
                "sectors": sectors_list,
                "sector_count": len(sectors_list),
                "updated_at": datetime.utcnow(),
            }
            for stock_code, sectors_list in stock_to_sectors.items()
        ]
        
        if stock_docs:
            await self._write_buffer(
                buffer=stock_docs,
                collection="stock_sector_map",
                key_fields=["code"],
            )
            await db["stock_sector_map"].create_index("sectors.ts_code", background=True)
        
        # 写入 sector_stocks
        self.logger.info("Writing sector_stocks...")
        sector_docs = []
        for sector_code, stocks_list in sector_to_stocks.items():
            sector_doc = await db["ths_sectors"].find_one({"ts_code": sector_code})
            sector_docs.append({
                "ts_code": sector_code,
                "name": sector_doc["name"] if sector_doc else sector_code,
                "stocks": stocks_list,
                "stock_count": len(stocks_list),
                "updated_at": datetime.utcnow(),
            })
        
        if sector_docs:
            await self._write_buffer(
                buffer=sector_docs,
                collection="sector_stocks",
                key_fields=["ts_code"],
            )
            await db["sector_stocks"].create_index("stocks.code", background=True)
        
        stats = {
            "sectors_processed": result["success"],
            "sectors_failed": result["failed"],
            "stocks_mapped": len(stock_docs),
        }
        
        self.logger.info(f"Mapping complete: sectors={result['success']}, stocks={len(stock_docs)}")
        
        return stats
