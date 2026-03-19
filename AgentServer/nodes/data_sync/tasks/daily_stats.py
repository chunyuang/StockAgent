"""
每日统计任务

统计功能：
1. 板块/行业涨跌幅排名 (前20名)
2. 今日连板统计 (一板~六板及以上)
3. 今日涨跌个股数量
4. 今日涨停/跌停/炸板个股数量
5. 新增: 涨跌幅中位数、涨跌5%统计、封板率、晋级率等

数据来源: 基于已同步的 moneyflow_industry, moneyflow_concept, limit_list, stock_daily 进行统计
支持历史数据回补。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import time
import statistics

from core.base import BaseTask
from core.settings import settings
from core.managers import data_source_manager, mongo_manager, analysis_manager


class DailyStatsTask(BaseTask):
    """
    每日统计任务
    
    统计内容:
    - 板块/行业涨跌幅排名 (前20名) -> sector_ranking 表
    - 连板统计 + 涨跌统计 + 涨跌停统计 -> daily_stats 表
    - 情绪周期分析 -> market_analysis 表
    
    支持:
    - 增量更新: 只计算未统计的交易日
    - 历史回补: 首次运行时自动回补历史数据
    
    调度时间:
    - 可通过 SYNC_DAILY_STATS_SCHEDULE 环境变量配置
    - 默认: 每个交易日 18:10 (确保其他数据已同步完成)
    """
    
    name = "daily_stats"
    description = "计算每日统计数据"
    default_schedule = "10 18 * * 1-5"
    
    INITIAL_SYNC_DAYS = 30  # 首次回补天数
    
    @property
    def schedule(self) -> str:
        return settings.data_sync.daily_stats_schedule or self.default_schedule
    
    async def execute(self) -> Dict[str, Any]:
        """执行统计"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        if not latest_trade_date:
            self.logger.warning("Failed to get latest trade date")
            return {"count": 0, "message": "Failed to get trade date", "skipped": True}
        
        # 检查并回补缺失的历史数据（最近 N 天）
        backfill_result = await self._check_and_backfill()
        
        # 检查是否已统计当天
        if await mongo_manager.is_synced(self.name, latest_trade_date):
            if backfill_result.get("backfilled", 0) > 0:
                return {
                    "count": backfill_result["backfilled"],
                    "trade_date": latest_trade_date,
                    "message": f"Backfilled {backfill_result['backfilled']} missing dates, {latest_trade_date} already computed",
                }
            self.logger.info(f"Daily stats {latest_trade_date} already computed, skipping")
            return {"count": 0, "message": f"Already computed {latest_trade_date}", "skipped": True}
        
        # 计算当天数据
        result = await self._compute_single_day(latest_trade_date)
        
        # 记录同步完成
        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=latest_trade_date,
            count=1,
        )
        
        total_computed = 1 + backfill_result.get("backfilled", 0)
        
        return {
            "count": total_computed,
            "trade_date": latest_trade_date,
            "backfilled": backfill_result.get("backfilled", 0),
            **result,
            "message": f"Computed daily stats for {latest_trade_date}" + 
                       (f" (+ {backfill_result['backfilled']} backfilled)" if backfill_result.get("backfilled") else ""),
        }
    
    async def _check_and_backfill(self) -> Dict[str, Any]:
        """
        检查最近 N 天是否有缺失的数据，如有则回补
        
        Returns:
            {"backfilled": 回补的天数, "missing": 缺失的日期列表}
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.INITIAL_SYNC_DAYS)
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        
        # 获取交易日列表
        trade_dates, _ = await data_source_manager.get_trade_calendar(start_str, end_str)
        
        if not trade_dates:
            return {"backfilled": 0, "missing": []}
        
        # 获取已计算的日期
        existing = await mongo_manager.db["daily_stats"].distinct("trade_date")
        existing_set = set(existing)
        
        # 找出缺失的日期
        missing_dates = [d for d in trade_dates if d not in existing_set]
        
        if not missing_dates:
            return {"backfilled": 0, "missing": []}
        
        self.logger.info(f"Found {len(missing_dates)} missing dates, backfilling...")
        
        # 按日期顺序处理（情绪分析需要前一天的数据）
        missing_dates.sort()
        success_count = 0
        
        for trade_date in missing_dates:
            try:
                await self._compute_single_day(trade_date)
                success_count += 1
                if success_count % 10 == 0:
                    self.logger.info(f"Backfill progress: {success_count}/{len(missing_dates)}")
            except Exception as e:
                self.logger.warning(f"Failed to compute {trade_date}: {e}")
        
        if success_count > 0:
            self.logger.info(f"Backfill complete: {success_count}/{len(missing_dates)} days")
        
        return {"backfilled": success_count, "missing": missing_dates}
    
    async def backfill(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        手动回补指定日期范围的数据
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
        """
        self.logger.info(f"Manual backfill: {start_date} ~ {end_date}")
        
        trade_dates, _ = await data_source_manager.get_trade_calendar(start_date, end_date)
        
        if not trade_dates:
            return {"error": "No trade dates found"}
        
        trade_dates.sort()
        success_count = 0
        
        for trade_date in trade_dates:
            try:
                await self._compute_single_day(trade_date, force=True)
                success_count += 1
                self.logger.info(f"Computed {trade_date} ({success_count}/{len(trade_dates)})")
            except Exception as e:
                self.logger.warning(f"Failed to compute {trade_date}: {e}")
        
        return {"success": success_count, "total": len(trade_dates)}
    
    async def _compute_single_day(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """计算单个交易日的所有统计数据"""
        self.logger.info(f"Computing daily stats for {trade_date}")
        
        results = {}
        
        # 1. 统计板块/行业涨跌幅排名
        t1 = time.time()
        ranking_result = await self._compute_sector_ranking(trade_date)
        results["sector_ranking"] = ranking_result
        self.logger.debug(f"Sector ranking: {ranking_result['count']} records, {time.time()-t1:.2f}s")
        
        # 2-4. 统计每日综合数据
        t2 = time.time()
        stats_result = await self._compute_daily_stats(trade_date)
        results["daily_stats"] = stats_result
        self.logger.debug(f"Daily stats computed: {time.time()-t2:.2f}s")
        
        # 5. 情绪周期分析
        t3 = time.time()
        prev_stats = await mongo_manager.find_one(
            "daily_stats",
            {"trade_date": {"$lt": trade_date}},
            sort=[("trade_date", -1)],
        )
        analysis_result = await analysis_manager.analyze_and_store(
            stats=stats_result,
            prev_stats=prev_stats,
            mongo_manager=mongo_manager,
        )
        results["market_analysis"] = analysis_result
        self.logger.info(
            f"[{trade_date}] 情绪={analysis_result['sentiment_score']:.0f}, "
            f"强度={analysis_result['strength_score']:.0f}, "
            f"周期={analysis_result['cycle']}"
        )
        
        return results
    
    async def _compute_sector_ranking(self, trade_date: str) -> Dict[str, Any]:
        """
        统计板块/行业涨跌幅排名 (前20名)
        
        从 moneyflow_industry 和 moneyflow_concept 表获取数据
        预排序后存入 sector_ranking 表，供 API 直接查询
        """
        ranking_records = []
        
        # 1. 行业排名 (前20)
        industry_data = await mongo_manager.find_many(
            "moneyflow_industry",
            {"trade_date": trade_date},
        )
        
        if industry_data:
            sorted_industry = sorted(industry_data, key=lambda x: float(x.get("pct_change") or 0), reverse=True)
            
            # 涨幅前20
            for i, item in enumerate(sorted_industry[:20]):
                name = item.get("industry") or item.get("name") or ""
                ranking_records.append({
                    "trade_date": trade_date,
                    "ranking_type": "industry_top",
                    "rank": i + 1,
                    "ts_code": item.get("ts_code"),
                    "name": name,
                    "pct_change": float(item.get("pct_change") or 0),
                    "net_amount": float(item.get("net_amount") or 0),
                    "lead_stock": item.get("lead_stock", ""),
                })
            
            # 跌幅前20
            for i, item in enumerate(sorted_industry[-20:][::-1]):
                name = item.get("industry") or item.get("name") or ""
                ranking_records.append({
                    "trade_date": trade_date,
                    "ranking_type": "industry_bottom",
                    "rank": i + 1,
                    "ts_code": item.get("ts_code"),
                    "name": name,
                    "pct_change": float(item.get("pct_change") or 0),
                    "net_amount": float(item.get("net_amount") or 0),
                    "lead_stock": item.get("lead_stock", ""),
                })
        
        # 2. 概念板块排名 (前20)
        concept_data = await mongo_manager.find_many(
            "moneyflow_concept",
            {"trade_date": trade_date},
        )
        
        if concept_data:
            sorted_concept = sorted(concept_data, key=lambda x: float(x.get("pct_change") or 0), reverse=True)
            
            # 涨幅前20
            for i, item in enumerate(sorted_concept[:20]):
                name = item.get("name") or item.get("concept") or ""
                ranking_records.append({
                    "trade_date": trade_date,
                    "ranking_type": "concept_top",
                    "rank": i + 1,
                    "ts_code": item.get("ts_code"),
                    "name": name,
                    "pct_change": float(item.get("pct_change") or 0),
                    "net_amount": float(item.get("net_amount") or 0),
                    "lead_stock": item.get("lead_stock", ""),
                })
            
            # 跌幅前20
            for i, item in enumerate(sorted_concept[-20:][::-1]):
                name = item.get("name") or item.get("concept") or ""
                ranking_records.append({
                    "trade_date": trade_date,
                    "ranking_type": "concept_bottom",
                    "rank": i + 1,
                    "ts_code": item.get("ts_code"),
                    "name": name,
                    "pct_change": float(item.get("pct_change") or 0),
                    "net_amount": float(item.get("net_amount") or 0),
                    "lead_stock": item.get("lead_stock", ""),
                })
        
        # 写入数据库
        if ranking_records:
            await mongo_manager.delete_many(
                "sector_ranking",
                {"trade_date": trade_date},
            )
            
            result = await mongo_manager.insert_many(
                "sector_ranking",
                ranking_records,
            )
            
            return {"count": len(ranking_records), "inserted": result}
        
        return {"count": 0}
    
    async def _compute_daily_stats(self, trade_date: str) -> Dict[str, Any]:
        """统计每日综合数据"""
        stats = {
            "trade_date": trade_date,
            "created_at": datetime.utcnow(),
            
            # 连板统计
            "limit_1": 0,
            "limit_2": 0,
            "limit_3": 0,
            "limit_4": 0,
            "limit_5": 0,
            "limit_6_plus": 0,
            
            # 涨跌统计
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            
            # 涨跌停统计
            "limit_up_count": 0,
            "limit_down_count": 0,
            "broken_limit_count": 0,
            "max_limit_height": 0,
            
            # 沪深港通资金流向 (百万元)
            "hgt": None,
            "sgt": None,
            "north_money": None,
            "ggt_ss": None,
            "ggt_sz": None,
            "south_money": None,
            
            # 市场成交额 (千元)
            "sh_amount": None,
            "sz_amount": None,
            "total_amount": None,
            
            # === 新增字段 (双评分系统) ===
            # 个股涨跌幅统计
            "pct_chg_median": None,      # 涨跌幅中位数
            "up_5pct_count": 0,          # 涨超5%家数
            "down_5pct_count": 0,        # 跌超5%家数
            
            # 大盘指数涨跌幅 (沪深300)
            "index_pct_chg": None,
            
            # 封板率 (涨停封板 / (涨停+炸板))
            "seal_rate": None,
            
            # 连板家数 (2板及以上)
            "cont_board_count": 0,
            
            # 昨日连板晋级率
            "promotion_rate": None,
        }
        
        # 1. 从 limit_list 获取涨跌停数据
        limit_data = await mongo_manager.find_many(
            "limit_list",
            {"trade_date": trade_date},
            projection={"ts_code": 1, "limit": 1, "limit_times": 1, "open_times": 1, "_id": 0},
        )
        
        if limit_data:
            for item in limit_data:
                limit_type = item.get("limit")
                limit_times = item.get("limit_times", 1) or 1
                open_times = item.get("open_times", 0) or 0
                
                if limit_type == "U":
                    stats["limit_up_count"] += 1
                    
                    if limit_times > stats["max_limit_height"]:
                        stats["max_limit_height"] = limit_times
                    
                    if limit_times == 1:
                        stats["limit_1"] += 1
                    elif limit_times == 2:
                        stats["limit_2"] += 1
                    elif limit_times == 3:
                        stats["limit_3"] += 1
                    elif limit_times == 4:
                        stats["limit_4"] += 1
                    elif limit_times == 5:
                        stats["limit_5"] += 1
                    else:
                        stats["limit_6_plus"] += 1
                    
                    if open_times > 0:
                        stats["broken_limit_count"] += 1
                        
                elif limit_type == "D":
                    stats["limit_down_count"] += 1
        
        # 2. 从 stock_daily 获取涨跌统计
        daily_data = await mongo_manager.find_many(
            "stock_daily",
            {"trade_date": trade_date},
            projection={"ts_code": 1, "pct_chg": 1, "_id": 0},
        )
        
        pct_chg_list = []  # 收集所有涨跌幅用于计算中位数
        
        if daily_data:
            for item in daily_data:
                pct_chg = item.get("pct_chg", 0) or 0
                pct_chg_list.append(pct_chg)
                
                if pct_chg > 0:
                    stats["up_count"] += 1
                elif pct_chg < 0:
                    stats["down_count"] += 1
                else:
                    stats["flat_count"] += 1
                
                # 涨跌5%统计
                if pct_chg >= 5:
                    stats["up_5pct_count"] += 1
                elif pct_chg <= -5:
                    stats["down_5pct_count"] += 1
        
        # 计算涨跌幅中位数
        if pct_chg_list:
            stats["pct_chg_median"] = round(statistics.median(pct_chg_list), 4)
        
        # 3. 获取沪深港通资金流向
        try:
            # 注意：data_source_manager 返回 (data, source) 元组
            hsgt_data, _ = await data_source_manager.get_moneyflow_hsgt(trade_date=trade_date)
            if hsgt_data and len(hsgt_data) > 0:
                hsgt = hsgt_data[0]
                stats["hgt"] = hsgt.get("hgt")
                stats["sgt"] = hsgt.get("sgt")
                stats["north_money"] = hsgt.get("north_money")
                stats["ggt_ss"] = hsgt.get("ggt_ss")
                stats["ggt_sz"] = hsgt.get("ggt_sz")
                stats["south_money"] = hsgt.get("south_money")
                self.logger.debug(
                    f"HSGT data: north_money={stats['north_money']}M, "
                    f"south_money={stats['south_money']}M"
                )
        except Exception as e:
            self.logger.warning(f"Failed to get HSGT data: {e}")
        
        # 4. 获取两市成交额
        try:
            sh_index = await mongo_manager.find_one(
                "index_daily",
                {"ts_code": "000001.SH", "trade_date": trade_date},
                projection={"amount": 1, "_id": 0},
            )
            if sh_index:
                stats["sh_amount"] = sh_index.get("amount")
            
            sz_index = await mongo_manager.find_one(
                "index_daily",
                {"ts_code": "399001.SZ", "trade_date": trade_date},
                projection={"amount": 1, "_id": 0},
            )
            if sz_index:
                stats["sz_amount"] = sz_index.get("amount")
            
            if stats["sh_amount"] is not None and stats["sz_amount"] is not None:
                stats["total_amount"] = stats["sh_amount"] + stats["sz_amount"]
                self.logger.debug(
                    f"Market turnover: Total={stats['total_amount']/1e8:.2f}亿"
                )
        except Exception as e:
            self.logger.warning(f"Failed to get market turnover: {e}")
        
        # 5. 获取大盘指数涨跌幅 (沪深300)
        try:
            hs300_index = await mongo_manager.find_one(
                "index_daily",
                {"ts_code": "000300.SH", "trade_date": trade_date},
                projection={"pct_chg": 1, "_id": 0},
            )
            if hs300_index:
                stats["index_pct_chg"] = hs300_index.get("pct_chg")
        except Exception as e:
            self.logger.warning(f"Failed to get index pct_chg: {e}")
        
        # 计算衍生指标
        total_stocks = stats["up_count"] + stats["down_count"] + stats["flat_count"]
        stats["total_stocks"] = total_stocks
        stats["up_ratio"] = round(stats["up_count"] / total_stocks * 100, 2) if total_stocks > 0 else 0
        stats["down_ratio"] = round(stats["down_count"] / total_stocks * 100, 2) if total_stocks > 0 else 0
        
        stats["total_limit_up"] = (
            stats["limit_1"] + stats["limit_2"] + stats["limit_3"] + 
            stats["limit_4"] + stats["limit_5"] + stats["limit_6_plus"]
        )
        
        # 封板率: 涨停封板 / (涨停+炸板)
        limit_up = stats["limit_up_count"]
        broken = stats["broken_limit_count"]
        if limit_up + broken > 0:
            stats["seal_rate"] = round(limit_up / (limit_up + broken) * 100, 2)
        else:
            stats["seal_rate"] = 0
        
        # 连板家数 (2板及以上)
        stats["cont_board_count"] = (
            stats["limit_2"] + stats["limit_3"] + stats["limit_4"] + 
            stats["limit_5"] + stats["limit_6_plus"]
        )
        
        # 6. 计算昨日连板晋级率
        stats["promotion_rate"] = await self._compute_promotion_rate(trade_date)
        
        # 写入数据库
        await mongo_manager.update_one(
            "daily_stats",
            {"trade_date": trade_date},
            {"$set": stats},
            upsert=True,
        )
        
        return stats
    
    async def _compute_promotion_rate(self, trade_date: str) -> Optional[float]:
        """
        计算昨日连板晋级率
        
        逻辑: 昨日涨停股中，今日仍涨停的比例
        
        Args:
            trade_date: 当前交易日
        
        Returns:
            晋级率 (0-100)，无法计算时返回 None
        """
        # 获取前一个交易日
        prev_stats = await mongo_manager.find_one(
            "daily_stats",
            {"trade_date": {"$lt": trade_date}},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1, "_id": 0},
        )
        
        if not prev_stats:
            return None
        
        prev_date = prev_stats["trade_date"]
        
        # 获取昨日涨停股
        prev_limit_ups = await mongo_manager.find_many(
            "limit_list",
            {"trade_date": prev_date, "limit": "U"},
            projection={"ts_code": 1, "_id": 0},
        )
        
        if not prev_limit_ups:
            return None
        
        prev_codes = {item["ts_code"] for item in prev_limit_ups}
        
        # 获取今日涨停股
        today_limit_ups = await mongo_manager.find_many(
            "limit_list",
            {"trade_date": trade_date, "limit": "U"},
            projection={"ts_code": 1, "_id": 0},
        )
        
        today_codes = {item["ts_code"] for item in today_limit_ups} if today_limit_ups else set()
        
        # 计算晋级率
        promoted_count = len(prev_codes & today_codes)
        promotion_rate = round(promoted_count / len(prev_codes) * 100, 2)
        
        return promotion_rate
