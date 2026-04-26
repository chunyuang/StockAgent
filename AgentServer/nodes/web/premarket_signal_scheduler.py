#!/usr/bin/env python3
"""
每日盘前信号生成调度器

基于 generate_daily_signals.py 已有代码，完善以下功能：
1. 每日盘前自动执行超短策略信号扫描
2. 生成预选池并存入 MongoDB
3. APScheduler 定时调度（支持盘前/盘后两个时间点）
4. 信号结果存入 MongoDB（daily_premarket_signals 集合）
5. 与已有 SignalGenerator / RealTradingSignalGenerator 整合

架构：
  APScheduler
    ├── 08:50 盘前调度 → generate_premarket_signals()
    │   ├── 1. 计算情绪周期 → 判断仓位上限
    │   ├── 2. 强制空仓检查
    │   ├── 3. 获取预选池（全A股，排除ST/次新股/涨停/跌停）
    │   ├── 4. 竞价阶段过滤
    │   ├── 5. 多因子计算 + 排序
    │   ├── 6. 策略过滤（仅保留情绪周期允许的策略）
    │   ├── 7. 选出 TOP N 标的
    │   ├── 8. 生成交易计划
    │   └── 9. 存入 MongoDB + 推送通知
    │
    └── 15:30 盘后调度 → generate_postmarket_review()
        ├── 1. 回顾当日信号执行情况
        ├── 2. 更新信号状态（expired）
        └── 3. 生成盘后复盘报告

  MongoDB Collections:
    ├── daily_premarket_signals  — 每日盘前信号（主集合）
    ├── premarket_pool           — 预选池记录
    └── trading_signals          — 交易信号（已有，兼容）
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from core.managers import mongo_manager

try:
    from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    from backtest_module.backtest_engine.factor_selection.universe import (
        UniverseManager, UniverseType, ExcludeRule,
    )
    _HAS_BACKTEST_MODULE = True
except ImportError:
    _HAS_BACKTEST_MODULE = False
    # 类型占位，允许模块导入和单测
    class PortfolioBacktester:  # type: ignore
        def __init__(self, *a, **kw): pass
    class UniverseManager:  # type: ignore
        async def get_universe(self, *a, **kw): return []
    class UniverseType:  # type: ignore
        ALL_A = "all_a"
    class ExcludeRule:  # type: ignore
        ST = "st"
        NEW_STOCK = "new_stock"
        LIMIT_UP = "limit_up"
        LIMIT_DOWN = "limit_down"

logger = logging.getLogger("premarket_scheduler")


# ==================== 常量 ====================

COLLECTION_SIGNALS = "daily_premarket_signals"
COLLECTION_POOL = "premarket_pool"
COLLECTION_TRADING_SIGNALS = "trading_signals"  # 已有集合，兼容写入

# 调度时间配置
SCHEDULE_PREMARKET = {"hour": 8, "minute": 50}   # 盘前08:50
SCHEDULE_POSTMARKET = {"hour": 15, "minute": 30}  # 盘后15:30


# ==================== 盘前信号生成器 ====================


class PremarketSignalScheduler:
    """
    盘前信号生成调度器

    核心职责：
    1. 每日盘前自动执行信号扫描流水线
    2. 生成预选池并存入 MongoDB
    3. 管理定时调度（APScheduler）
    4. 提供手动触发接口

    与已有代码的关系：
    - 复用 RealTradingSignalGenerator 的核心逻辑（情绪周期、竞价过滤、因子计算等）
    - 复用 SignalGenerator 的 MongoDB 写入格式（兼容 trading_signals 集合）
    - 新增：预选池持久化、定时调度、信号生命周期管理
    """

    def __init__(self, config: Dict = None):
        self.config = {
            "initial_cash": 1_000_000,
            "max_position": 0.7,
            "max_position_per_stock": 0.2,
            "max_hold_days": 3,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.07,
            "liquidity_threshold": 5_000_000,
            "volume_threshold": 1.5,
            "slippage": 0.002,
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": True,
            "top_n": 5,
            # 新增：预选池配置
            "pool_exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK, ExcludeRule.LIMIT_UP, ExcludeRule.LIMIT_DOWN],
            # 新增：调度配置
            "premarket_time": SCHEDULE_PREMARKET,
            "postmarket_time": SCHEDULE_POSTMARKET,
            # 新增：推送配置
            "push_on_generate": True,
        }
        self.config.update(config or {})

        self.backtester = PortfolioBacktester(
            source="ak",
            slippage=self.config["slippage"],
            max_position=self.config["max_position"],
        )
        self.backtester.enable_sentiment_cycle = self.config["enable_sentiment_cycle"]
        self.backtester.enable_force_empty = self.config["enable_force_empty"]
        self.universe_mgr = UniverseManager()

        self._scheduler = None
        self._running = False

    # ==================== 核心流水线 ====================

    async def generate_premarket_signals(self, trade_date: str = None) -> Dict:
        """
        盘前信号生成主流水线

        Args:
            trade_date: 交易日期（YYYYMMDD），默认自动获取

        Returns:
            Dict: {
                signal_id, date, force_empty, sentiment, pool_size,
                auction_filtered_size, signals, trading_plan,
                generated_at, status
            }
        """
        if not trade_date:
            trade_date = self._get_latest_trade_date()

        signal_id = f"pre_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        logger.info(f"[{signal_id}] ========== 盘前信号生成 {trade_date} ==========")

        # ---- Step 1: 情绪周期 ----
        sentiment_info = await self._safe_get_sentiment(trade_date)
        logger.info(f"[{signal_id}] 情绪评分：{sentiment_info.get('score', 'N/A')}，"
                     f"等级：{sentiment_info.get('level', 'N/A')}，"
                     f"仓位上限：{sentiment_info.get('position_limit', 0):.0%}")

        # ---- Step 2: 强制空仓检查 ----
        force_empty = await self._safe_check_force_empty(trade_date)
        if force_empty:
            logger.info(f"[{signal_id}] 触发强制空仓，今日无交易信号")
            result = self._build_signal_doc(
                signal_id=signal_id, trade_date=trade_date, now=now,
                force_empty=True, sentiment=sentiment_info,
                pool_size=0, auction_filtered_size=0, signals=[],
                trading_plan="触发强制空仓条件，今日空仓观望",
            )
            await self._save_signal(result)
            await self._notify(result)
            return result

        # ---- Step 3: 预选池 ----
        pool = await self._safe_get_universe(trade_date)
        pool_size = len(pool)
        logger.info(f"[{signal_id}] 预选池数量：{pool_size}只")

        # ---- Step 4: 竞价阶段过滤 ----
        auction_filtered = pool
        if self.config["enable_auction_filter"] and pool:
            auction_filtered = await self._auction_filter(pool, trade_date)
        auction_size = len(auction_filtered)
        logger.info(f"[{signal_id}] 竞价过滤后剩余：{auction_size}只")

        if not auction_filtered:
            logger.info(f"[{signal_id}] 预选池为空，今日无交易信号")
            result = self._build_signal_doc(
                signal_id=signal_id, trade_date=trade_date, now=now,
                force_empty=False, sentiment=sentiment_info,
                pool_size=pool_size, auction_filtered_size=0, signals=[],
                trading_plan="无符合条件标的，空仓观望",
            )
            await self._save_signal(result)
            await self._notify(result)
            return result

        # ---- Step 5: 多因子计算 + 排序 ----
        factor_df = await self._safe_compute_factors(auction_filtered, trade_date)

        # ---- Step 6: 情绪周期策略过滤 ----
        if factor_df is not None and not factor_df.empty:
            allowed_strategies = set(sentiment_info.get("allowed_strategies", []))
            if allowed_strategies and "strategy" in factor_df.columns:
                factor_df = factor_df[factor_df["strategy"].isin(allowed_strategies)]

        # ---- Step 7: 选出 TOP N ----
        target_stocks = []
        if factor_df is not None and not factor_df.empty:
            target_stocks = self.backtester.factor_engine.select_top_stocks(
                factor_df, self.config["top_n"],
                liquidity_threshold=self.config["liquidity_threshold"],
            )

        # ---- Step 8: 获取详细信息 + 生成交易计划 ----
        stock_details = await self._get_stock_details(target_stocks, trade_date)
        trading_plan = self._generate_trading_plan(stock_details, sentiment_info)

        logger.info(f"[{signal_id}] 最终选中标的：{len(stock_details)}只")
        for i, s in enumerate(stock_details, 1):
            logger.info(f"  {i}. {s['ts_code']} {s['name']} | {s['strategy']} | "
                        f"收盘{s['close']:.2f} | 涨跌{s['pct_chg']:.2f}%")

        # ---- Step 9: 存入 MongoDB + 推送 ----
        result = self._build_signal_doc(
            signal_id=signal_id, trade_date=trade_date, now=now,
            force_empty=False, sentiment=sentiment_info,
            pool_size=pool_size, auction_filtered_size=auction_size,
            signals=stock_details, trading_plan=trading_plan,
        )
        await self._save_signal(result)
        await self._notify(result)

        logger.info(f"[{signal_id}] 盘前信号生成完成，已存入MongoDB")
        return result

    # ==================== 盘后回顾 ====================

    async def generate_postmarket_review(self, trade_date: str = None) -> Dict:
        """
        盘后回顾：更新信号状态 + 生成复盘报告

        Args:
            trade_date: 交易日期

        Returns:
            Dict: 复盘报告
        """
        if not trade_date:
            trade_date = self._get_latest_trade_date()

        now = datetime.utcnow()

        # 1. 将当日所有 pending 信号标记为 expired
        expired_count = await self._expire_pending_signals(trade_date, now)
        logger.info(f"已将 {expired_count} 个 pending 信号标记为 expired")

        # 2. 获取当日盘前信号记录
        premarket_signal = await mongo_manager.find_one(
            COLLECTION_SIGNALS,
            {"date": trade_date},
        )

        # 3. 获取当日实际交易记录
        trade_records = await mongo_manager.find_many(
            "trade_records",
            {"trade_time": {
                "$gte": datetime.strptime(f"{trade_date} 09:30:00", "%Y%m%d %H:%M:%S"),
                "$lte": datetime.strptime(f"{trade_date} 15:00:00", "%Y%m%d %H:%M:%S"),
            }},
        ) if premarket_signal else []

        # 4. 构建复盘报告
        review = {
            "review_id": f"rev_{uuid.uuid4().hex[:12]}",
            "date": trade_date,
            "signal_count": len(premarket_signal.get("signals", [])) if premarket_signal else 0,
            "executed_count": len(trade_records),
            "expired_count": expired_count,
            "trades": [
                {
                    "ts_code": t.get("ts_code"),
                    "direction": t.get("direction"),
                    "quantity": t.get("quantity"),
                    "price": t.get("price"),
                    "strategy": t.get("strategy"),
                }
                for t in trade_records
            ] if trade_records else [],
            "reviewed_at": now,
        }

        # 5. 保存复盘报告
        await mongo_manager.insert_one("daily_postmarket_review", review)

        logger.info(f"盘后复盘完成：{trade_date}，信号{review['signal_count']}个，"
                     f"执行{review['executed_count']}笔，过期{expired_count}个")
        return review

    # ==================== 定时调度 ====================

    async def start_scheduler(self) -> None:
        """
        启动 APScheduler 定时调度

        注册两个定时任务：
        - 盘前08:50: generate_premarket_signals
        - 盘后15:30: generate_postmarket_review
        """
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.error("APScheduler not installed. Run: pip install apscheduler")
            raise

        if self._running:
            logger.warning("Scheduler already running")
            return

        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        # 盘前信号生成：周一至周五 08:50
        premarket_cfg = self.config["premarket_time"]
        self._scheduler.add_job(
            self._scheduled_premarket,
            CronTrigger(
                day_of_week="mon-fri",
                hour=premarket_cfg["hour"],
                minute=premarket_cfg["minute"],
            ),
            id="premarket_signals",
            name="盘前信号生成",
            replace_existing=True,
        )

        # 盘后回顾：周一至周五 15:30
        postmarket_cfg = self.config["postmarket_time"]
        self._scheduler.add_job(
            self._scheduled_postmarket,
            CronTrigger(
                day_of_week="mon-fri",
                hour=postmarket_cfg["hour"],
                minute=postmarket_cfg["minute"],
            ),
            id="postmarket_review",
            name="盘后回顾",
            replace_existing=True,
        )

        self._scheduler.start()
        self._running = True
        logger.info(f"定时调度已启动：盘前{premarket_cfg['hour']:02d}:{premarket_cfg['minute']:02d}，"
                     f"盘后{postmarket_cfg['hour']:02d}:{postmarket_cfg['minute']:02d}")

    async def stop_scheduler(self) -> None:
        """停止定时调度"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._running = False
        logger.info("定时调度已停止")

    async def _scheduled_premarket(self) -> None:
        """定时触发盘前信号生成"""
        try:
            logger.info("⏰ 定时触发：盘前信号生成")
            await self.generate_premarket_signals()
        except Exception as e:
            logger.exception(f"盘前信号生成异常: {e}")

    async def _scheduled_postmarket(self) -> None:
        """定时触发盘后回顾"""
        try:
            logger.info("⏰ 定时触发：盘后回顾")
            await self.generate_postmarket_review()
        except Exception as e:
            logger.exception(f"盘后回顾异常: {e}")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_scheduler_info(self) -> Dict:
        """获取调度器状态"""
        if not self._scheduler:
            return {"running": False, "jobs": []}
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            })
        return {"running": self._running, "jobs": jobs}

    # ==================== MongoDB 持久化 ====================

    async def _save_signal(self, signal_doc: Dict) -> None:
        """
        存入 MongoDB

        写入两个集合：
        1. daily_premarket_signals — 完整信号文档（含预选池大小、情绪、交易计划等）
        2. trading_signals — 兼容已有集合，每只股票一条记录（供 /trading/signals API 查询）
        """
        try:
            # 1. 写入主集合
            await mongo_manager.insert_one(COLLECTION_SIGNALS, signal_doc)
            logger.info(f"信号已存入 {COLLECTION_SIGNALS}: {signal_doc['signal_id']}")
        except Exception as e:
            logger.error(f"写入 {COLLECTION_SIGNALS} 失败: {e}")

        # 2. 兼容写入 trading_signals 集合（每只股票一条记录）
        try:
            signals = signal_doc.get("signals", [])
            if signals:
                trade_date = signal_doc["date"]
                expired_at = datetime.strptime(f"{trade_date} 15:00:00", "%Y%m%d %H:%M:%S")
                now = datetime.utcnow()

                trading_signal_docs = []
                for stock in signals:
                    doc = {
                        "signal_id": f"sig_{uuid.uuid4().hex[:12]}",
                        "ts_code": stock.get("ts_code", ""),
                        "stock_name": stock.get("name", ""),
                        "strategy": stock.get("strategy", ""),
                        "strategy_name": stock.get("strategy", ""),  # 中文名已在 stock 中
                        "signal_type": "buy",
                        "price": stock.get("close", 0) * 1.01,  # 建议买入价（+1%滑点）
                        "suggest_quantity": self._calc_suggest_quantity(stock),
                        "confidence": stock.get("confidence", 0.7),
                        "reason": self._build_signal_reason(stock, signal_doc.get("sentiment", {})),
                        "generated_at": now,
                        "expired_at": expired_at,
                        "status": "pending",
                        "premarket_signal_id": signal_doc["signal_id"],
                        "created_at": now,
                        "updated_at": now,
                    }
                    trading_signal_docs.append(doc)

                await mongo_manager.insert_many(COLLECTION_TRADING_SIGNALS, trading_signal_docs)
                logger.info(f"兼容写入 {COLLECTION_TRADING_SIGNALS}: {len(trading_signal_docs)} 条")
        except Exception as e:
            logger.error(f"兼容写入 {COLLECTION_TRADING_SIGNALS} 失败: {e}")

    async def _expire_pending_signals(self, trade_date: str, now: datetime) -> int:
        """将当日所有 pending 信号标记为 expired"""
        try:
            result = await mongo_manager.update_many(
                COLLECTION_TRADING_SIGNALS,
                {
                    "status": "pending",
                    "generated_at": {
                        "$gte": datetime.strptime(f"{trade_date} 00:00:00", "%Y%m%d %H:%M:%S"),
                        "$lte": datetime.strptime(f"{trade_date} 23:59:59", "%Y%m%d %H:%M:%S"),
                    },
                },
                {"$set": {"status": "expired", "updated_at": now}},
            )
            return result if isinstance(result, int) else result.get("modified_count", 0)
        except Exception as e:
            logger.error(f"过期信号更新失败: {e}")
            return 0

    # ==================== 通知推送 ====================

    async def _notify(self, signal_doc: Dict) -> None:
        """推送信号通知（飞书/企业微信等）"""
        if not self.config.get("push_on_generate"):
            return

        try:
            from real_trading.signal_pusher import SignalPusher
            pusher = SignalPusher()
            pusher.push(signal_doc)
        except ImportError:
            logger.debug("SignalPusher not available, skip push")
        except Exception as e:
            logger.warning(f"信号推送失败: {e}")

    # ==================== 安全包装方法（异常不中断流水线） ====================

    async def _safe_get_sentiment(self, trade_date: str) -> Dict:
        """安全获取情绪周期"""
        try:
            return await self.backtester._get_sentiment_cycle(trade_date)
        except Exception as e:
            logger.warning(f"情绪周期获取失败: {e}，使用默认值")
            return {
                "score": 50,
                "level": "中性",
                "position_limit": self.config["max_position"],
                "allowed_strategies": ["半路追涨", "首板打板", "龙头低吸"],
                "stop_loss_adjust": 1.0,
                "take_profit_adjust": 1.0,
            }

    async def _safe_check_force_empty(self, trade_date: str) -> bool:
        """安全检查强制空仓"""
        try:
            return await self.backtester._check_force_empty(trade_date)
        except Exception as e:
            logger.warning(f"强制空仓检查失败: {e}，默认不空仓")
            return False

    async def _safe_get_universe(self, trade_date: str) -> List[str]:
        """安全获取预选池"""
        try:
            rules = self.config.get("pool_exclude_rules", [ExcludeRule.ST, ExcludeRule.NEW_STOCK])
            return await self.universe_mgr.get_universe(UniverseType.ALL_A, trade_date, rules)
        except Exception as e:
            logger.warning(f"预选池获取失败: {e}，返回空列表")
            return []

    async def _safe_compute_factors(self, universe: List[str], trade_date: str):
        """安全计算因子"""
        try:
            return await self.backtester.factor_engine.compute_factors(
                universe, trade_date, self._get_factors_config(),
                liquidity_threshold=self.config["liquidity_threshold"],
            )
        except Exception as e:
            logger.warning(f"因子计算失败: {e}")
            return None

    # ==================== 辅助方法（复用自 generate_daily_signals.py） ====================

    async def _auction_filter(self, universe: List[str], trade_date: str) -> List[str]:
        """竞价阶段过滤（复用 RealTradingSignalGenerator 逻辑）"""
        try:
            auction_data = await mongo_manager.find_many(
                "stock_bid_auction",
                {"trade_date": int(trade_date)},
                projection={
                    "ts_code": 1, "auction_pct_chg": 1,
                    "auction_volume": 1, "unmatched_volume": 1,
                },
            )
        except Exception as e:
            logger.warning(f"竞价数据获取失败: {e}，跳过竞价过滤")
            return universe

        if not auction_data:
            return universe

        auction_map = {x.get("ts_code", ""): x for x in auction_data if x.get("ts_code")}
        filtered = []

        for ts_code in universe:
            auction = auction_map.get(ts_code)
            if not auction:
                continue
            pct = auction.get("auction_pct_chg", 0)
            vol = auction.get("auction_volume", 0)
            unmatched = auction.get("unmatched_volume", 0)
            if 0.5 <= pct <= 7 and vol > 0 and unmatched > 0:
                filtered.append(ts_code)

        return filtered

    async def _get_stock_details(self, ts_codes: List[str], trade_date: str) -> List[Dict]:
        """获取股票详细信息"""
        if not ts_codes:
            return []

        # 并行查询三张表
        daily_map, basic_map, lhb_map = {}, {}, {}

        try:
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "close": 1, "pct_chg": 1, "amount": 1, "up_limit": 1, "down_limit": 1},
            )
            daily_map = {d.get("ts_code", ""): d for d in (daily_data or []) if d.get("ts_code")}
        except Exception as e:
            logger.warning(f"日线数据获取失败: {e}")

        try:
            basic_data = await mongo_manager.find_many(
                "stock_basic",
                {"ts_code": {"$in": ts_codes}},
                projection={"ts_code": 1, "name": 1, "industry": 1},
            )
            basic_map = {b.get("ts_code", ""): b for b in (basic_data or []) if b.get("ts_code")}
        except Exception as e:
            logger.warning(f"基础数据获取失败: {e}")

        try:
            lhb_data = await mongo_manager.find_many(
                "stock_lhb",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "net_buy_amount": 1, "reason": 1},
            )
            lhb_map = {l.get("ts_code", ""): l for l in (lhb_data or []) if l.get("ts_code")}
        except Exception as e:
            logger.warning(f"龙虎榜数据获取失败: {e}")

        details = []
        for ts_code in ts_codes:
            daily = daily_map.get(ts_code, {})
            basic = basic_map.get(ts_code, {})
            lhb = lhb_map.get(ts_code, {})

            details.append({
                "ts_code": ts_code,
                "name": basic.get("name", ts_code),
                "industry": basic.get("industry", "未知"),
                "close": daily.get("close", 0),
                "pct_chg": daily.get("pct_chg", 0),
                "amount": daily.get("amount", 0),
                "up_limit": daily.get("up_limit", 0),
                "down_limit": daily.get("down_limit", 0),
                "has_lhb": ts_code in lhb_map,
                "lhb_net_buy": lhb.get("net_buy_amount", 0),
                "lhb_reason": lhb.get("reason", ""),
                "strategy": self._get_strategy_for_stock(ts_code, daily),
            })

        return details

    def _get_strategy_for_stock(self, ts_code: str, daily_data: Dict) -> str:
        """根据行情判断策略类型"""
        pct_chg = daily_data.get("pct_chg", 0) if isinstance(daily_data, dict) else 0
        limit_up = daily_data.get("up_limit", 0) if isinstance(daily_data, dict) else 0
        close = daily_data.get("close", 0) if isinstance(daily_data, dict) else 0

        if abs(pct_chg - 10) < 0.5 and limit_up > 0 and abs(close - limit_up) < 0.01:
            return "首板打板"
        elif pct_chg >= 5:
            return "半路追涨"
        else:
            return "龙头低吸"

    def _get_factors_config(self) -> List[Dict]:
        """因子权重配置"""
        return [
            {"name": "momentum_5d", "weight": 0.2},
            {"name": "volume_increase", "weight": 0.2},
            {"name": "limit_up_count", "weight": 0.2},
            {"name": "turnover_rate", "weight": 0.15},
            {"name": "volatility_20d", "weight": 0.15},
            {"name": "has_lhb", "weight": 0.05},
            {"name": "north_hold_ratio", "weight": 0.05},
        ]

    def _generate_trading_plan(self, signals: List[Dict], sentiment_info: Dict) -> str:
        """生成 Markdown 格式交易计划"""
        if not signals:
            return "无符合条件标的，建议空仓观望"

        plan = [
            f"### 今日交易计划（{sentiment_info.get('level', 'N/A')}，"
            f"仓位上限{sentiment_info.get('position_limit', 0):.0%}）",
            "",
            "#### 可选标的（按优先级排序）：",
        ]

        total_value = self.config["initial_cash"] * sentiment_info.get("position_limit", 0.7)
        per_stock_value = total_value / min(len(signals), self.config["top_n"])
        stop_adj = sentiment_info.get("stop_loss_adjust", 1.0)
        take_adj = sentiment_info.get("take_profit_adjust", 1.0)

        for idx, stock in enumerate(signals, 1):
            buy_price = stock.get("close", 0) * 1.01
            buy_shares = int(per_stock_value / max(buy_price, 0.01) / 100) * 100
            stop_price = buy_price * (1 - self.config["stop_loss_pct"] * stop_adj)
            take_price = buy_price * (1 + self.config["take_profit_pct"] * take_adj)

            plan.append(f"{idx}. **{stock.get('name', '?')}({stock.get('ts_code', '?')})**")
            plan.append(f"   策略：{stock.get('strategy', '?')} | 行业：{stock.get('industry', '?')}")
            plan.append(f"   建议买入价：≤{buy_price:.2f} | 仓位：{buy_shares}股（约{per_stock_value:.0f}元）")
            plan.append(f"   止损价：{stop_price:.2f}（{self.config['stop_loss_pct'] * stop_adj * 100:.1f}%）")
            plan.append(f"   止盈价：{take_price:.2f}（{self.config['take_profit_pct'] * take_adj * 100:.1f}%）")
            if stock.get("has_lhb"):
                plan.append(f"   🎉 龙虎榜净买入{stock.get('lhb_net_buy', 0) / 10000:.1f}万，原因：{stock.get('lhb_reason', '')}")
            plan.append("")

        plan.extend([
            "#### 交易纪律：",
            "1. 严格执行止损，触及止损价立即卖出",
            f"2. 单票仓位不超过{self.config['max_position_per_stock'] * 100:.0f}%，总仓位不超过上限",
            f"3. 所有持仓最多持有{self.config['max_hold_days']}天，到期强制卖出",
            "4. 优先买排名靠前的标的，开盘不及预期直接放弃",
        ])

        return "\n".join(plan)

    # ==================== 构建信号文档 ====================

    def _build_signal_doc(
        self,
        signal_id: str,
        trade_date: str,
        now: datetime,
        force_empty: bool,
        sentiment: Dict,
        pool_size: int,
        auction_filtered_size: int,
        signals: List[Dict],
        trading_plan: str,
    ) -> Dict:
        """构建信号文档（存入 daily_premarket_signals 集合）"""
        return {
            "signal_id": signal_id,
            "date": trade_date,
            "force_empty": force_empty,
            "sentiment": sentiment,
            "pool_size": pool_size,
            "auction_filtered_size": auction_filtered_size,
            "signals": signals,
            "signal_count": len(signals),
            "trading_plan": trading_plan,
            "generated_at": now,
            "status": "active",  # active → executed | expired
            "config_snapshot": {
                "top_n": self.config["top_n"],
                "max_position": self.config["max_position"],
                "liquidity_threshold": self.config["liquidity_threshold"],
                "volume_threshold": self.config["volume_threshold"],
            },
        }

    def _calc_suggest_quantity(self, stock: Dict) -> int:
        """计算建议买入数量"""
        price = stock.get("close", 0) * 1.01
        if price <= 0:
            return 100
        per_stock = self.config["initial_cash"] * self.config["max_position"] / self.config["top_n"]
        return int(per_stock / price / 100) * 100

    def _build_signal_reason(self, stock: Dict, sentiment: Dict) -> str:
        """构建信号原因"""
        parts = [f"策略:{stock.get('strategy', '?')}"]
        if stock.get("has_lhb"):
            parts.append("龙虎榜")
        parts.append(f"情绪:{sentiment.get('level', '?')}")
        return " | ".join(parts)

    def _get_latest_trade_date(self) -> str:
        """获取最近交易日"""
        now = datetime.now()
        if now.weekday() >= 5:
            offset = now.weekday() - 4
            latest = now - timedelta(days=offset)
        else:
            latest = now if now.hour >= 15 else now - timedelta(days=1)
        return latest.strftime("%Y%m%d")


# ==================== 全局单例 ====================

_scheduler: Optional[PremarketSignalScheduler] = None


def get_premarket_scheduler(config: Dict = None) -> PremarketSignalScheduler:
    """获取全局调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = PremarketSignalScheduler(config)
    return _scheduler


# ==================== CLI 入口 ====================

async def main():
    """CLI 入口：手动触发信号生成"""
    import argparse

    parser = argparse.ArgumentParser(description="盘前信号生成调度器")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度模式")
    parser.add_argument("--review", action="store_true", help="执行盘后回顾")
    parser.add_argument("--output", help="输出文件路径")

    args = parser.parse_args()

    await mongo_manager.initialize()

    scheduler = PremarketSignalScheduler()

    try:
        if args.schedule:
            # 启动定时调度模式
            await scheduler.start_scheduler()
            logger.info("定时调度已启动，按 Ctrl+C 退出...")
            try:
                while True:
                    await asyncio.sleep(3600)
            except (KeyboardInterrupt, asyncio.CancelledError):
                await scheduler.stop_scheduler()
        elif args.review:
            result = await scheduler.generate_postmarket_review(args.date)
            print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
        else:
            # 手动触发一次
            result = await scheduler.generate_premarket_signals(args.date)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2, default=str)
                print(f"✅ 信号已保存到：{args.output}")
            else:
                print("\n" + "=" * 50)
                print(result.get("trading_plan", "无交易计划"))
                print("=" * 50)
    finally:
        await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
