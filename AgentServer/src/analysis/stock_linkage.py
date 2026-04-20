"""
个股联动分析器

识别板块内个股的角色：龙一、龙二、中军、补涨、跟风。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from src.config import config_manager


logger = logging.getLogger(__name__)


class StockRole(Enum):
    """个股角色"""
    DRAGON_ONE = "龙一"
    DRAGON_TWO = "龙二"
    CENTRAL_ARMY = "中军"
    CATCH_UP = "补涨"
    FOLLOWER = "跟风"
    UNKNOWN = "未知"


@dataclass
class StockLinkageResult:
    """联动分析结果"""
    ts_code: str
    name: str
    role: StockRole
    sector: str
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "ts_code": self.ts_code,
            "name": self.name,
            "role": self.role.value,
            "sector": self.sector,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }


class StockLinkageAnalyzer:
    """
    个股联动分析器
    
    识别规则：
    1. 龙一：板块最先涨停，辨识度最高
    2. 龙二：板块第二涨停，龙一替补
    3. 中军：大市值（>200亿），走势稳健
    4. 补涨：滞后启动，低位补涨
    5. 跟风：无实质关联，纯蹭热点
    
    Example:
        analyzer = StockLinkageAnalyzer()
        results = await analyzer.analyze_sector(
            sector="人工智能",
            trade_date="20260305",
        )
    """
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # 从配置读取参数
        linkage_config = config_manager.get("review.linkage", {})
        
        self.central_army_min_cap = linkage_config.get(
            "roles", {}
        ).get("central_army", {}).get("min_market_cap", 200)
        
        self.catch_up_lag_days = linkage_config.get(
            "roles", {}
        ).get("catch_up", {}).get("lag_days", 2)
        
        self.rule_weights = linkage_config.get("rule_weights", {
            "time_first": 0.3,
            "market_cap": 0.2,
            "limit_times": 0.2,
            "sector_match": 0.3,
        })
    
    async def _get_db(self) -> AsyncIOMotorDatabase:
        """获取数据库连接"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def analyze_sector(
        self,
        sector: str,
        trade_date: str,
    ) -> List[StockLinkageResult]:
        """
        分析板块内个股联动关系
        
        Args:
            sector: 板块名称
            trade_date: 交易日期
        
        Returns:
            联动分析结果列表
        """
        self.logger.info(f"Analyzing sector linkage: {sector} on {trade_date}")
        
        db = await self._get_db()
        
        # 1. 获取板块成分股
        sector_doc = await db["sector_stocks"].find_one({
            "name": {"$regex": sector, "$options": "i"},
        })
        
        if not sector_doc:
            self.logger.warning(f"Sector not found: {sector}")
            return []
        
        component_codes = [s["code"] for s in sector_doc.get("stocks", [])]
        
        # 2. 获取当日涨停的成分股
        limit_stocks = await db["review_limit"].find({
            "trade_date": trade_date,
            "limit": "U",
        }).to_list(None)
        
        # 过滤出板块内涨停股
        sector_limit_stocks = [
            s for s in limit_stocks
            if s.get("ts_code", "")[:6] in component_codes
        ]
        
        if not sector_limit_stocks:
            self.logger.info(f"No limit-up stocks in {sector}")
            return []
        
        # 3. 按封板时间排序
        sector_limit_stocks.sort(key=lambda x: x.get("first_time", "15:00"))
        
        results = []
        
        # 4. 识别龙一龙二
        if len(sector_limit_stocks) >= 1:
            first = sector_limit_stocks[0]
            results.append(StockLinkageResult(
                ts_code=first.get("ts_code"),
                name=first.get("name"),
                role=StockRole.DRAGON_ONE,
                sector=sector,
                confidence=0.9,
                reasons=[
                    f"最早封板: {first.get('first_time')}",
                    f"连板数: {first.get('limit_times', 1)}",
                ],
            ))
        
        if len(sector_limit_stocks) >= 2:
            second = sector_limit_stocks[1]
            results.append(StockLinkageResult(
                ts_code=second.get("ts_code"),
                name=second.get("name"),
                role=StockRole.DRAGON_TWO,
                sector=sector,
                confidence=0.85,
                reasons=[
                    f"第二封板: {second.get('first_time')}",
                    f"连板数: {second.get('limit_times', 1)}",
                ],
            ))
        
        # 5. 分析其余涨停股
        for stock in sector_limit_stocks[2:]:
            role, confidence, reasons = await self._classify_stock(
                stock,
                sector,
                trade_date,
            )
            
            results.append(StockLinkageResult(
                ts_code=stock.get("ts_code"),
                name=stock.get("name"),
                role=role,
                sector=sector,
                confidence=confidence,
                reasons=reasons,
            ))
        
        return results
    
    async def _classify_stock(
        self,
        stock: Dict[str, Any],
        sector: str,
        trade_date: str,
    ) -> tuple:
        """
        分类单只股票的角色
        
        Returns:
            (role, confidence, reasons)
        """
        db = await self._get_db()
        ts_code = stock.get("ts_code")
        reasons = []
        
        # 检查市值（中军判断）
        total_mv = stock.get("total_mv", 0)
        if total_mv and total_mv / 10000 > self.central_army_min_cap:
            reasons.append(f"市值: {total_mv/10000:.1f}亿（大票）")
            return StockRole.CENTRAL_ARMY, 0.8, reasons
        
        # 检查连板数（实力判断）
        limit_times = stock.get("limit_times", 1)
        if limit_times >= 3:
            reasons.append(f"连板数: {limit_times}")
            return StockRole.DRAGON_TWO, 0.7, reasons
        
        # 检查板块匹配度
        stock_code = ts_code[:6]
        stock_map = await db["stock_sector_map"].find_one({"code": stock_code})
        
        if stock_map:
            sectors = [s["name"] for s in stock_map.get("sectors", [])]
            # 检查是否有多个热门板块
            if len(sectors) > 5:
                reasons.append("题材较多，可能跟风")
                return StockRole.FOLLOWER, 0.6, reasons
            
            # 检查是否主营业务相关
            sector_match = any(sector in s for s in sectors)
            if not sector_match:
                reasons.append("与板块关联度低")
                return StockRole.FOLLOWER, 0.5, reasons
        
        # 检查是否滞后启动（补涨）
        first_time = stock.get("first_time", "15:00")
        if first_time > "14:00":
            reasons.append(f"尾盘封板: {first_time}")
            return StockRole.CATCH_UP, 0.65, reasons
        
        # 默认跟风
        reasons.append("普通涨停")
        return StockRole.FOLLOWER, 0.5, reasons
    
    async def analyze_all_sectors(
        self,
        trade_date: str,
        min_limit_count: int = 2,
    ) -> Dict[str, List[StockLinkageResult]]:
        """
        分析所有热门板块的联动关系
        
        Args:
            trade_date: 交易日期
            min_limit_count: 最小涨停家数
        
        Returns:
            {sector_name: [StockLinkageResult, ...]}
        """
        db = await self._get_db()
        
        # 获取涨停家数较多的板块
        sector_limit = await db["review_sector_limit"].find({
            "trade_date": trade_date,
            "up_num": {"$gte": min_limit_count},
        }).sort("up_num", -1).to_list(20)
        
        results = {}
        
        for sector_doc in sector_limit:
            sector_name = sector_doc.get("name", "")
            if not sector_name:
                continue
            
            try:
                sector_results = await self.analyze_sector(sector_name, trade_date)
                if sector_results:
                    results[sector_name] = sector_results
            except Exception as e:
                self.logger.error(f"Failed to analyze {sector_name}: {e}")
        
        return results
    
    async def get_dragons_summary(
        self,
        trade_date: str,
    ) -> Dict[str, Any]:
        """
        获取龙头汇总
        
        Args:
            trade_date: 交易日期
        
        Returns:
            龙头汇总数据
        """
        all_results = await self.analyze_all_sectors(trade_date)
        
        summary = {
            "trade_date": trade_date,
            "total_sectors": len(all_results),
            "dragon_one_list": [],
            "dragon_two_list": [],
            "central_army_list": [],
            "sectors": {},
        }
        
        for sector, results in all_results.items():
            sector_summary = {
                "龙一": None,
                "龙二": None,
                "中军": [],
                "补涨": [],
                "跟风": [],
            }
            
            for r in results:
                if r.role == StockRole.DRAGON_ONE:
                    sector_summary["龙一"] = r.to_dict()
                    summary["dragon_one_list"].append({
                        "sector": sector,
                        **r.to_dict(),
                    })
                elif r.role == StockRole.DRAGON_TWO:
                    sector_summary["龙二"] = r.to_dict()
                    summary["dragon_two_list"].append({
                        "sector": sector,
                        **r.to_dict(),
                    })
                elif r.role == StockRole.CENTRAL_ARMY:
                    sector_summary["中军"].append(r.to_dict())
                    summary["central_army_list"].append({
                        "sector": sector,
                        **r.to_dict(),
                    })
                elif r.role == StockRole.CATCH_UP:
                    sector_summary["补涨"].append(r.to_dict())
                else:
                    sector_summary["跟风"].append(r.to_dict())
            
            summary["sectors"][sector] = sector_summary
        
        return summary
