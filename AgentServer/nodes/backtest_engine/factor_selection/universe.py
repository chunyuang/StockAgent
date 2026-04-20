"""
股票池管理器

管理回测的股票池范围，支持:
- 全市场 A 股
- 排除规则（ST、次新股、涨跌停）
- 获取调仓日期列表
"""

import logging
from datetime import datetime, timedelta
from enum import StrEnum

from core.managers import mongo_manager

logger = logging.getLogger(__name__)


class UniverseType(StrEnum):
    """股票池类型"""
    ALL_A = "all_a"          # 全A股


class ExcludeRule(StrEnum):
    """排除规则"""
    ST = "st"                # ST股票
    NEW_STOCK = "new_stock"  # 次新股 (上市不满1年)
    LIMIT_UP = "limit_up"    # 涨停股 (一字板)
    LIMIT_DOWN = "limit_down" # 跌停股


class UniverseManager:
    """
    股票池管理器

    职责:
    1. 获取指定日期的有效股票池
    2. 应用排除规则
    3. 生成调仓日期列表

    数据来源:
    - stock_daily_ak_full: 获取当日有交易的股票
    - stock_basic: 获取 ST 状态、上市日期
    - limit_list: 获取涨跌停信息
    """

    # 次新股定义：上市不满多少个交易日
    NEW_STOCK_DAYS = 250

    async def get_universe(
        self,
        universe_type: UniverseType,
        trade_date: str,
        exclude_rules: list[ExcludeRule] | None = None,
    ) -> set[str]:
        """
        获取指定日期的股票池

        Args:
            universe_type: 股票池类型 (目前只支持全市场)
            trade_date: 交易日期 (YYYYMMDD)
            exclude_rules: 排除规则列表

        Returns:
            股票代码集合
        """
        # 1. 获取基础股票池（当日有交易的股票）
        logger.debug(f"[{trade_date}] Getting tradable stocks...")
        stocks = await self._get_tradable_stocks(trade_date)

        if not stocks:
            logger.warn('UNIVERSE', f"No tradable stocks found for {trade_date}")
            return set()

        logger.info('UNIVERSE', f"[{trade_date}] Base universe: {len(stocks)} stocks")

        # 2. 应用排除规则
        if exclude_rules:
            excluded = await self._apply_exclude_rules(stocks, trade_date, exclude_rules)
            stocks = stocks - excluded
            logger.debug(f"[{trade_date}] After exclusion: {len(stocks)} stocks")

        return stocks

    async def _get_tradable_stocks(self, trade_date: str) -> set[str]:
        """获取当日有交易的股票"""
        # 从 stock_daily_ak_full 获取当日有数据的股票
        # 注意：停牌股票也会有一条记录（保留历史字段），但 close 是 None 或 0，需要剔除
        result = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"trade_date": int(trade_date)},
            projection={"ts_code": 1, "close": 1},
        )
        # 过滤掉停牌股票：close must be > 0
        return {doc["ts_code"] for doc in result if doc.get("close") and doc.get("close", 0) > 0}

    async def _apply_exclude_rules(
        self,
        stocks: set[str],
        trade_date: str,
        rules: list[ExcludeRule],
    ) -> set[str]:
        """应用排除规则，返回需要排除的股票集合"""
        excluded = set()

        for rule in rules:
            if rule == ExcludeRule.ST:
                st_stocks = await self._get_st_stocks()
                excluded.update(st_stocks & stocks)

            elif rule == ExcludeRule.NEW_STOCK:
                new_stocks = await self._get_new_stocks(trade_date)
                excluded.update(new_stocks & stocks)

            elif rule == ExcludeRule.LIMIT_UP:
                limit_up = await self._get_limit_up_stocks(trade_date)
                excluded.update(limit_up & stocks)

            elif rule == ExcludeRule.LIMIT_DOWN:
                limit_down = await self._get_limit_down_stocks(trade_date)
                excluded.update(limit_down & stocks)

        return excluded

    async def _get_st_stocks(self) -> set[str]:
        """获取 ST 股票（从 stock_basic 表）"""
        # ST 股票名称包含 ST
        result = await mongo_manager.find_many(
            "stock_basic",
            {"name": {"$regex": "ST", "$options": "i"}},
            projection={"ts_code": 1},
        )
        return {doc["ts_code"] for doc in result}

    async def _get_new_stocks(self, trade_date: str) -> set[str]:
        """获取次新股（上市不满 250 个交易日）"""
        # 计算截止日期（大约 1 年前）
        trade_dt = datetime.strptime(trade_date, "%Y%m%d")
        cutoff_date = (trade_dt - timedelta(days=365)).strftime("%Y%m%d")

        # 上市日期晚于截止日期的都是次新股
        result = await mongo_manager.find_many(
            "stock_basic",
            {"list_date": {"$gt": cutoff_date}},
            projection={"ts_code": 1},
        )
        return {doc["ts_code"] for doc in result}

    async def _get_limit_up_stocks(self, trade_date: str) -> set[str]:
        """获取涨停股（一字板：开盘=最低=涨停价）"""
        # 从 stock_daily_ak_full 直接根据涨跌幅判断涨停
        result = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"trade_date": int(trade_date), "pct_chg": {"$gte": 9.8}},
            projection={"ts_code": 1, "open": 1, "low": 1, "close": 1},
        )

        # 筛选一字板：open == low == close (涨停价)
        limit_up = set()
        for doc in result:
            # 简化判断：如果在涨停榜且开盘=最低，认为是一字板
            if doc.get("open") and doc.get("low"):
                if abs(doc["open"] - doc["low"]) < 0.001:
                    limit_up.add(doc["ts_code"])

        return limit_up

    async def _get_limit_down_stocks(self, trade_date: str) -> set[str]:
        """获取跌停股"""
        # 从 stock_daily_ak_full 直接根据涨跌幅判断跌停
        result = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"trade_date": int(trade_date), "pct_chg": {"$lte": -9.8}},
            projection={"ts_code": 1},
        )
        return {doc["ts_code"] for doc in result}

    async def get_rebalance_dates(
        self,
        start_date: str,
        end_date: str,
        freq: str = "monthly",
    ) -> list[str]:
        """
        获取调仓日期列表

        Args:
            start_date: 开始日期
            end_date: 结束日期
            freq: 调仓频率 "daily" | "weekly" | "monthly" | "quarterly"

        Returns:
            调仓日期列表
        """
        # 获取交易日历
        logger.info('UNIVERSE', f"Getting rebalance dates: {start_date} -> {end_date}, freq={freq}")
        # 优先从本地MongoDB获取交易日历，完全不依赖Tushare
        trade_dates = await self._get_trade_dates_from_mongo(start_date, end_date)
        if not trade_dates:
            # 本地没有数据时 fallback 到Baostock
            try:
                from core.managers import baostock_manager
                await baostock_manager.initialize()
                trade_dates = await baostock_manager.get_trade_dates(start_date, end_date)
                await baostock_manager.shutdown()

                if trade_dates:
                    # 转换为YYYYMMDD整数格式
                    trade_dates = [d.replace("-", "") for d in trade_dates]
                    logger.info('UNIVERSE', f"从Baostock获取到{len(trade_dates)}个交易日")
                else:
                    logger.error("No trade dates found in both MongoDB and Baostock")
                    return []
            except Exception as e:
                logger.error(f"获取交易日历失败: {e}")
                return []
        trade_dates = sorted(trade_dates)

        if not trade_dates:
            return []

        logger.info('UNIVERSE', f"Total trade dates: {len(trade_dates)}")

        if freq == "daily":
            result = trade_dates
        elif freq == "weekly":
            result = self._filter_by_week(trade_dates)
        elif freq == "monthly":
            result = self._filter_by_month(trade_dates)
        elif freq == "quarterly":
            result = self._filter_by_quarter(trade_dates)
        else:
            logger.warn('UNIVERSE', f"Unknown freq '{freq}', using all trade dates")
            result = trade_dates

        logger.info('UNIVERSE', f"Filtered rebalance dates: {len(result)} (freq={freq})")
        return result

    def _filter_by_week(self, dates: list[str]) -> list[str]:
        """筛选每周第一个交易日"""
        result = []
        last_week = None

        for d in dates:
            dt = datetime.strptime(str(d), "%Y%m%d")
            week = dt.isocalendar()[:2]  # (year, week)
            if week != last_week:
                result.append(d)
                last_week = week

        return result

    def _filter_by_month(self, dates: list[str]) -> list[str]:
        """筛选每月第一个交易日"""
        result = []
        last_month = None

        for d in dates:
            d_str = str(d)
            month = d_str[:6]  # YYYYMM
            if month != last_month:
                result.append(d)
                last_month = month

        return result

    def _filter_by_quarter(self, dates: list[str]) -> list[str]:
        """筛选每季度第一个交易日"""
        result = []
        last_quarter = None

        for d in dates:
            d_str = str(d)
            year = d_str[:4]
            month = int(d_str[4:6])
            quarter = (month - 1) // 3 + 1
            q = f"{year}Q{quarter}"
            if q != last_quarter:
                result.append(d)
                last_quarter = q

        return result

    async def _get_trade_dates_from_mongo(self, start_date: str, end_date: str) -> list[str]:
        """从本地MongoDB stock_daily_ak_full表中获取日期范围内的所有交易日"""
        try:
            # 查询日期范围内的所有不同trade_date
            pipeline = [
                {"$match": {"trade_date": {"$gte": int(start_date), "$lte": int(end_date)}}},
                {"$group": {"_id": "$trade_date"}},
                {"$sort": {"_id": 1}}
            ]
            result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
            # 统一转换成字符串格式，避免类型错误
            return [str(doc["_id"]) for doc in result]
        except Exception as e:
            logger.warn('UNIVERSE', f"Failed to get trade dates from MongoDB: {e}")
            return []

    async def get_all_trade_dates(
        self,
        start_date: str,
        end_date: str,
    ) -> list[str]:
        """获取日期范围内的所有交易日，完全不依赖Tushare"""
        # 优先从本地MongoDB获取交易日历
        trade_dates = await self._get_trade_dates_from_mongo(start_date, end_date)
        if not trade_dates:
            # 本地没有数据时 fallback 到Baostock
            try:
                from core.managers import baostock_manager
                await baostock_manager.initialize()
                trade_dates = await baostock_manager.get_trade_dates(start_date, end_date)
                await baostock_manager.shutdown()

                if trade_dates:
                    # 转换为YYYYMMDD整数格式
                    trade_dates = [d.replace("-", "") for d in trade_dates]
                    logger.info('UNIVERSE', f"从Baostock获取到{len(trade_dates)}个交易日")
                else:
                    logger.error("No trade dates found in both MongoDB and Baostock")
                    return []
            except Exception as e:
                logger.error(f"获取交易日历失败: {e}")
                return []
        return sorted(trade_dates)
