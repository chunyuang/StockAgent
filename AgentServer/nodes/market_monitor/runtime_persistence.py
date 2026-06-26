"""
RuntimePersistence — 运行时状态持久化

从MarketScanner拆分出来(Phase3.1)。
负责:
- 运行时快照保存/加载(MongoDB scanner_runtime_snapshot)
- 时间线保存/加载(MongoDB scanner_timeline)
- 扫描链路追踪保存(MongoDB scan_traces)
- 盘前竞价处理
- 数据加载(股票列表/日级因子/名称映射/周末缓存)【v2.9.32提取】
- 停止时状态持久化【v2.9.32提取】
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

logger = logging.getLogger("runtime_persistence")

# 本地快照降级路径
LOCAL_SNAPSHOT_DIR = "/tmp"
LOCAL_SNAPSHOT_PREFIX = "scanner_snapshot_"


class RuntimePersistence:
    """
    运行时状态持久化管理器
    
    用法:
        rp = RuntimePersistence(scanner)
        await rp.save_runtime_snapshot(force=True)
        await rp.load_runtime_snapshot()
        await rp.save_timeline()
        await rp.save_scan_traces(filter_result)
    """
    
    def __init__(self, scanner):
        """
        Args:
            scanner: MarketScanner实例
        """
        self._scanner = scanner
    
    @property
    def broker(self) -> Any:
        return self._scanner._broker
    
    @property
    def account_id(self) -> str:
        return self._scanner.account_id
    
    # ==================== 运行时快照 ====================
    
    async def load_runtime_snapshot(self) -> None:
        """从MongoDB加载运行时快照(启动时恢复)
        
        优先MongoDB, 失败时回退本地文件
        """
        doc = await self._load_snapshot_doc()
        if not doc:
            return
        
        # 跨日检查
        snapshot_date = str(doc.get("trade_date", ""))
        today = datetime.now().strftime("%Y%m%d")
        is_same_day = (snapshot_date == today)
        if not is_same_day and snapshot_date:
            logger.info(f"[SNAPSHOT] 快照日期={snapshot_date}, 今日={today}, 跳过日期相关状态恢复")
        
        self._restore_snapshot_data(doc, is_same_day)
        logger.info(f"[SNAPSHOT] 加载运行时快照成功")
    
    async def _load_snapshot_doc(self) -> Optional[dict]:
        """从MongoDB或本地文件加载快照文档【v2.9.45提取】"""
        # 尝试MongoDB
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is not None:
                doc = await mongo_manager.db["scanner_runtime_snapshot"].find_one(
                    {"account_id": self.account_id}
                )
                if doc:
                    return doc
        except Exception as e:
            logger.warning(f"[SNAPSHOT] MongoDB加载失败: {e}")
        
        # MongoDB失败→回退本地文件
        try:
            local_path = self._get_local_fallback_path()
            if os.path.exists(local_path):
                with open(local_path, 'r') as f:
                    doc = json.load(f)
                logger.info(f"[SNAPSHOT] 从本地降级文件恢复: {local_path}")
                return doc
        except Exception as e:
            logger.debug(f"[SNAPSHOT] 本地文件加载失败: {e}")
        
        return None
    
    def _restore_snapshot_data(self, doc: dict, is_same_day: bool) -> None:
        """从快照文档恢复运行时状态【v2.9.45提取】
        
        Args:
            doc: 快照文档
            is_same_day: 快照是否为当日(同日恢复追踪止损等日内状态)
        """
        scanner = self._scanner
        
        # 恢复同日状态(线程安全) — 追踪止损/风险等级/pending_sells仅同日有效
        if is_same_day:
            with scanner._state_lock:
                if "trailing_stops" in doc:
                    scanner._trailing_stops = doc["trailing_stops"]
                    logger.info(f"[SNAPSHOT] 恢复追踪止损: {len(scanner._trailing_stops)}只")
                if "position_risk_levels" in doc:
                    scanner._position_risk_levels = doc["position_risk_levels"]
                if "pending_sells" in doc:
                    scanner._pending_sells = doc["pending_sells"]
                    logger.info(f"[SNAPSHOT] 恢复待卖: {len(scanner._pending_sells)}只")
        
        # 恢复风控状态(跨日也恢复,不恢复trading_paused)
        if "circuit_breaker" in doc:
            cb = doc["circuit_breaker"]
            if scanner._circuit_breaker is None:
                scanner._circuit_breaker = {}
            scanner._circuit_breaker["consecutive_losses"] = cb.get("consecutive_losses", 0)
            scanner._circuit_breaker["today_trades"] = cb.get("today_trades", 0)
            scanner._circuit_breaker["today_losses"] = cb.get("today_losses", 0)
        
        # 恢复统计
        if "stats" in doc:
            scanner._stats.update(doc["stats"])
        
        # 恢复行情降级状态
        if "quote_degrade_level" in doc and scanner._quote_manager:
            scanner._quote_degrade_level = doc["quote_degrade_level"]
            scanner._quote_manager._quote_degrade_level = doc["quote_degrade_level"]
            if doc["quote_degrade_level"] > 0:
                scanner._quote_manager._degrade_since = time.monotonic()
                scanner._quote_manager._last_recover_attempt = time.monotonic()
                logger.info(f"[SNAPSHOT] 恢复行情降级: level={doc['quote_degrade_level']}")
    
    async def save_runtime_snapshot(self, force: bool = False) -> None:
        """保存运行时快照到MongoDB【v2.9.56:提取_snapshot_doc构建+_save_snapshot_local降级】
        
        节流: 默认5秒保存一次, force=True跳过节流
        MongoDB不可用时降级写本地文件
        """
        scanner = self._scanner
        
        now = time.time()
        if not force:
            last_save = scanner._last_snapshot_save
            if now - last_save < 5:  # v2.1: 5秒节流
                return
        
        doc = self._build_snapshot_doc(scanner)
        saved = await self._save_snapshot_mongo(scanner, doc, now)
        
        # MongoDB失败→降级写本地文件
        if not saved:
            self._save_snapshot_local(scanner, doc, now)

    def _build_snapshot_doc(self, scanner) -> Dict:
        """构建运行时快照文档【v2.9.56从save_runtime_snapshot提取】"""
        doc = {
            "account_id": self.account_id,
            "updated_at": datetime.now().isoformat(),
        }
        # 线程安全读取共享状态
        with scanner._state_lock:
            doc["trailing_stops"] = dict(scanner._trailing_stops)
            doc["position_risk_levels"] = dict(scanner._position_risk_levels)
            doc["pending_sells"] = dict(scanner._pending_sells)
        doc["circuit_breaker"] = scanner._circuit_breaker or {}
        doc["stats"] = dict(scanner._stats)
        doc["active_signals_count"] = len(scanner._active_signals)
        doc["dry_run"] = scanner._dry_run
        doc["trade_date"] = scanner._trade_date
        doc["quote_degrade_level"] = scanner._quote_degrade_level
        return doc

    async def _save_snapshot_mongo(self, scanner, doc: Dict, now: float) -> bool:
        """尝试保存快照到MongoDB【v2.9.56从save_runtime_snapshot提取】
        
        Returns: True=保存成功
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is not None:
                await mongo_manager.db["scanner_runtime_snapshot"].update_one(
                    {"account_id": self.account_id},
                    {"$set": doc},
                    upsert=True,
                )
                scanner._last_snapshot_save = now
                self._cleanup_local_fallback()
                return True
        except Exception as e:
            logger.debug(f"[SNAPSHOT] MongoDB保存失败: {e}")
        return False

    def _save_snapshot_local(self, scanner, doc: Dict, now: float) -> None:
        """降级保存快照到本地文件【v2.9.56从save_runtime_snapshot提取】"""
        try:
            local_path = self._get_local_fallback_path()
            with open(local_path, 'w') as f:
                json.dump(doc, f, ensure_ascii=False, default=str)
            scanner._last_snapshot_save = now
            logger.info(f"[SNAPSHOT] 降级保存到本地: {local_path}")
        except Exception as e2:
            logger.warning(f"[SNAPSHOT] 本地保存也失败: {e2}")
    
    def _get_local_fallback_path(self) -> str:
        """获取本地降级文件路径"""
        return os.path.join(LOCAL_SNAPSHOT_DIR, f"{LOCAL_SNAPSHOT_PREFIX}{self.account_id}.json")
    
    def _cleanup_local_fallback(self) -> None:
        """MongoDB恢复后清理本地降级文件"""
        try:
            path = self._get_local_fallback_path()
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"[SNAPSHOT] 清理本地降级文件: {path}")
        except Exception as _e:
            logger.warning(f"[SNAPSHOT] 本地降级文件清理失败: {_e}")
    
    # ==================== 盘前竞价 ====================
    
    async def premarket_auction(self, trade_date: str = None) -> None:
        """盘前竞价: 从持仓中筛选竞价异常股
        
        Args:
            trade_date: 交易日期(兼容scan_loop调用, 暂未使用)
        
        集合竞价9:15-9:25, 价格可能跳空:
        - 跳空高开(>3%): 标记为强势, 可以继续持有
        - 跳空低开(<-2%): 标记为风险, 需要关注是否低开低走
        """
        scanner = self._scanner
        if not self.broker:
            return
        
        positions = self.broker.get_positions()
        if not positions:
            return
        
        # 获取竞价数据(从缓存)
        for pos in positions:
            rt = scanner._realtime_cache.get(pos.ts_code, {})
            auction_price = rt.get("auction_price", 0)
            if auction_price <= 0:
                continue
            
            gap_pct = (auction_price - pos.current_price) / pos.current_price * 100
            
            if gap_pct > 3:
                logger.info(f"[AUCTION] {pos.ts_code} {pos.stock_name} 竞价高开+{gap_pct:.1f}%")
                with scanner._state_lock:
                    scanner._position_risk_levels[pos.ts_code] = "strong_open"
            elif gap_pct < -2:
                logger.warning(f"[AUCTION] {pos.ts_code} {pos.stock_name} 竞价低开{gap_pct:.1f}%")
                with scanner._state_lock:
                    scanner._position_risk_levels[pos.ts_code] = "weak_open"
    
    # ==================== 时间线持久化 ====================
    
    async def save_timeline(self) -> None:
        """保存时间线到MongoDB(追加模式, 不删除历史)
        【v2.9.96e】 buy/sell 事件需与 broker_orders 对账, 避免保存幽灵记录
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = self._scanner._trade_date or datetime.now().strftime("%Y%m%d")  # 【v2.9.92f修复】用scanner._trade_date避免跨天写入
            scanner = self._scanner
            if not scanner._timeline:
                return
            
            account_id = self.broker.account.account_id if self.broker else "default"
            
            # 【v2.9.96e】收集当日真实订单key, 过滤幽灵 buy/sell
            real_keys = set()
            try:
                today_int = int(today) if today.isdigit() else today
                async for o in mongo_manager.db["broker_orders"].find(
                    {"account_id": account_id, "trade_date": {"$in": [today, today_int]}},
                    {"ts_code": 1, "fill_time": 1, "create_time": 1, "side": 1, "_id": 0}
                ):
                    t = o.get("fill_time") or o.get("create_time", "")
                    real_keys.add((o.get("ts_code", ""), t, o.get("side", "")))
            except Exception as _e:
                logger.debug(f"[SCAN] 取real_keys失败(不阻断保存): {_e}")
            
            docs = []
            ghosts_skipped = 0
            for item in scanner._timeline:
                action = item.get("action", "")
                # 【v2.9.97c】buy/sell 不再写入 scanner_timeline (broker_orders 是唯一真相源)
                # 只保留 blocked/其他决策日志
                if action in ("buy", "sell"):
                    continue
                doc = dict(item)
                doc["account_id"] = account_id
                doc["trade_date"] = int(today) if today.isdigit() else today
                docs.append(doc)
            
            if ghosts_skipped > 0:
                logger.info(f"[SCAN] save_timeline过滤幽灵交易: {ghosts_skipped}条")
            
            if not docs:
                return
            
            # 去重
            existing_keys = set()
            today_td = int(today) if today.isdigit() else today
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id, "trade_date": {"$in": [today, today_td]}},
                {"time": 1, "ts_code": 1, "action": 1, "_id": 0}
            ):
                existing_keys.add(f"{doc.get('time','')}|{doc.get('ts_code','')}|{doc.get('action','')}")
            
            new_docs = [d for d in docs if f"{d.get('time','')}|{d.get('ts_code','')}|{d.get('action','')}" not in existing_keys]
            if new_docs:
                await mongo_manager.db["scanner_timeline"].insert_many(new_docs)
                logger.info(f"[SCAN] 保存时间线: {len(new_docs)}条新增")
        except Exception as e:
            logger.info(f"[SCAN] 保存时间线失败(非关键): {e}")
    
    async def save_scan_traces(self, filter_result) -> None:
        """保存扫描链路追踪到MongoDB
        
        优化：rejected候选只保存摘要(不含layer_results)，减少文档体积
        每次扫描3000+候选×layer_results会导致文档>1MB，列表查询返回20MB+
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            if not filter_result:
                return
            # 【v2.9.104】即使 trace_candidates 为空 (0 信号) 也要写入, 用于历史可追性
            # 之前 'not filter_result.trace_candidates' 直接 return 导致前端看不到无信号的扫描
            
            # 分离passed和rejected候选
            passed_candidates, rejected_summary = self._split_trace_candidates(filter_result.trace_candidates or [])
            
            # 构建追踪文档
            trace_doc = self._build_trace_doc(filter_result, passed_candidates, rejected_summary)
            
            await mongo_manager.db["scan_traces"].insert_one(trace_doc)
            # 【v2.9.89优化】同步更新scan_date_cache缓存(供scan-dates API秒级查询)
            try:
                trade_date = trace_doc.get("trade_date")
                is_debug = trace_doc.get("is_debug", False)
                if trade_date:
                    await mongo_manager.db["scan_date_cache"].update_one(
                        {"date": trade_date},
                        {"$inc": {"count": 1}, "$set": {"is_debug": is_debug}},
                        upsert=True
                    )
            except Exception:
                pass  # 非关键, 不影响主流程
            logger.info(f"[SCAN] 保存链路追踪: {len(passed_candidates)} passed + {len(rejected_summary)} rejected (节省layer_results)")
        except Exception as e:
            logger.warning(f"[SCAN] 保存链路追踪失败(非关键): {e}")

    def _split_trace_candidates(self, trace_candidates) -> Tuple[List, List]:
        """分离passed/rejected候选【v2.9.56从save_scan_traces提取】
        
        passed候选保留完整layer_results(关注重点), rejected只保留摘要(省空间)。
        """
        passed = []
        rejected = []
        for t in trace_candidates:
            base = {
                "ts_code": t.ts_code,
                "stock_name": t.stock_name,
                "strategy": t.strategy,
                "strategy_name": t.strategy_name,
                "price": t.price,
                "pct_chg": t.pct_chg,
                "final_status": t.final_status,
                "rejection_layer": t.final_rejection_layer,
                "rejection_reason": t.final_rejection_reason,
            }
            if t.final_status == "passed":
                base["layer_results"] = t.layer_results
                passed.append(base)
            else:
                rejected.append(base)
        return passed, rejected

    def _build_trace_doc(self, filter_result, passed_candidates: List, rejected_summary: List) -> Dict:
        """构建链路追踪文档【v2.9.56从save_scan_traces提取】"""
        today = self._scanner._trade_date or datetime.now().strftime("%Y%m%d")  # 【v2.9.92f修复】用scanner._trade_date避免跨天写入
        # 【v2.9.94】统一 trade_date 为 int，与API查询划一致(避免出现string混入)
        try:
            today_int = int(today)
        except (ValueError, TypeError):
            today_int = today
        now = datetime.now()
        ct = now.strftime("%H:%M:%S")
        is_trading_day = now.weekday() < 5
        is_trading_session = is_trading_day and (("09:15:00" <= ct <= "11:30:00") or ("13:00:00" <= ct <= "15:00:00"))
        # 【v2.9.104】记录全量扫描股票数 (5529 只)
        try:
            total_stocks = len(getattr(self._scanner, "_realtime_cache", {}) or {})
        except Exception:
            total_stocks = 0
        trace_doc = {
            "trade_date": today_int,
            "scan_time": now.isoformat(),
            "session": "trading" if is_trading_session else "off_session",
            "scan_type": getattr(self._scanner, "_current_trace_source", "full"),  # 【v2.9.105】full=全市场主扫, anomaly=异动扫
            "account_id": self.broker.account.account_id if self.broker else "default",
            "is_debug": not is_trading_session,
            "summary": {},
            "candidates": passed_candidates,
            "rejected_summary": rejected_summary,
        }
        for layer, stats in filter_result.trace_summary.items():
            trace_doc["summary"][layer] = dict(stats)
        trace_doc["summary"]["total_stocks"] = total_stocks  # 【v2.9.104】全量股票数
        trace_doc["summary"]["total_candidates"] = len(filter_result.trace_candidates or [])
        trace_doc["summary"]["passed"] = len(passed_candidates)
        trace_doc["summary"]["rejected"] = len(rejected_summary)
        # 【v2.9.105】策略漏斗: 每个策略的候选数/通过数/缺失字段
        scorer = getattr(self._scanner, "_strategy_scorer", None)
        if scorer and hasattr(scorer, "_last_strategy_funnel"):
            trace_doc["summary"]["strategy_funnel"] = scorer._last_strategy_funnel
        trace_doc["layer_details"] = dict(filter_result.layer_details)
        return trace_doc
    
    async def load_timeline(self) -> None:
        """从MongoDB加载时间线(启动时恢复)
        【v2.9.92f修复】只加载当天的数据，不回退到历史日期。
        之前回退到“数据最多”的历史日期会导致:
        1. 历史timeline被加载到内存
        2. save_timeline时用新trade_date写入 → 产生假数据重复
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = self._scanner._trade_date or datetime.now().strftime("%Y%m%d")
            account_id = self.broker.account.account_id if self.broker else "default"
            scanner = self._scanner
            
            # 只加载当天的数据(不回退到历史日期)
            query = {"account_id": account_id, "trade_date": {"$in": [today, int(today)] if today.isdigit() else today}}
            count = await mongo_manager.db["scanner_timeline"].count_documents(query)
            logger.info(f"[SCAN] 当天({today})时间线: {count}条")
            
            cursor = mongo_manager.db["scanner_timeline"].find(query).sort("time", 1)
            
            # 【v2.9.97c】只加载blocked等决策日志, buy/sell从broker_orders恢复
            blocked_count = 0
            async for doc in cursor:
                action = doc.get("action", "")
                if action in ("buy", "sell"):
                    continue  # buy/sell 不再从 scanner_timeline 加载
                doc.pop("_id", None)
                doc.pop("account_id", None)
                doc.pop("trade_date", None)
                scanner._timeline.append(doc)
                blocked_count += 1
            
            # 【v2.9.97c】从broker_orders恢复buy/sell时间线(唯一真相源)
            buy_sell_count = 0
            try:
                today_int = int(today) if today.isdigit() else today
                async for doc in mongo_manager.db["broker_orders"].find(
                    {"account_id": account_id, "status": "filled", "trade_date": {"$in": [today, today_int]}}
                ).sort("fill_time", 1):
                    side = doc.get("side", "")
                    if side not in ("buy", "sell"):
                        continue
                    scanner._timeline.append({
                        "time": doc.get("fill_time", "") or doc.get("create_time", ""),
                        "action": side,
                        "ts_code": doc.get("ts_code", ""),
                        "stock_name": doc.get("stock_name", ""),
                        "strategy": doc.get("strategy", ""),
                        "shares": doc.get("filled_qty", 0) or doc.get("quantity", 0),
                        "price": doc.get("filled_price", 0) or doc.get("price", 0),
                        "reason": doc.get("reason", ""),
                        "profit_pct": doc.get("profit_pct"),
                        "profit_amount": doc.get("profit_amount"),
                        "decision_detail": doc.get("decision_detail", {}),
                        "source": doc.get("source", "auto"),
                    })
                    buy_sell_count += 1
            except Exception as _e:
                logger.debug(f"[SCAN] 从broker_orders恢复时间线失败: {_e}")
            
            if scanner._timeline:
                logger.info(f"[SCAN] 恢复时间线: {len(scanner._timeline)}条 (blocked={blocked_count}, buy/sell={buy_sell_count})")
        except Exception as e:
            logger.debug(f"[SCAN] 加载时间线失败(非关键): {e}")

    @staticmethod
    def build_timeline_entry(
        pos, reason: str, order, quantity: int,
        profit_pct: float, profit_amount: float, *, source: str = "sell",
        trace_id: str = "",
    ) -> Dict:
        """构建卖出timeline记录【v2.9.22提取, v2.9.27:从scanner移入RuntimePersistence, v2.9.71:trace_id】"""
        import uuid
        entry: Dict[str, Any] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": "sell",
            "ts_code": pos.ts_code,
            "stock_name": pos.stock_name,
            "strategy": pos.strategy,
            "shares": quantity,
            "price": order.filled_price,
            "reason": reason,
            "profit_pct": round(profit_pct, 2),
            "profit_amount": round(profit_amount, 2),
            # 【v2.9.71: 卖出链路trace_id — 贯穿timeline/EventBus/MongoDB】
            "trace_id": trace_id or f"sell-{pos.ts_code}-{uuid.uuid4().hex[:8]}",
            "decision_detail": {
                "sell_reason": reason,
                "profit_pct": round(profit_pct, 2),
                "profit_amount": round(profit_amount, 2),
                "cost_price": pos.avg_cost,
                "sell_price": order.filled_price,
                "current_price": pos.current_price,
                "source": source,
            },
        }
        return entry

    async def post_sell_cleanup(
        self, pos, reason: str, order, quantity: int,
        profit_pct: float, profit_amount: float, *, source: str = "sell",
        trace_id: str = "",
    ) -> None:
        """卖出成功后统一清理(编排方法)【v2.9.71: trace_id贯穿】"""
        scanner = self._scanner
        if not trace_id:
            import uuid
            trace_id = f"sell-{pos.ts_code}-{uuid.uuid4().hex[:8]}"

        # Timeline记录
        entry = self.build_timeline_entry(
            pos, reason, order, quantity, profit_pct, profit_amount,
            source=source, trace_id=trace_id)
        scanner._timeline.append(entry)

        self._classify_sell_stats(scanner, reason)
        scanner._record_trade_result(profit_pct / 100.0)

        with scanner._state_lock:
            scanner._trailing_stops.pop(pos.ts_code, None)
            scanner._position_risk_levels.pop(pos.ts_code, None)

        await self._emit_sell_events(scanner, pos, reason, order, entry, profit_pct, trace_id=trace_id)
        logger.info(f"[{source.upper()}] {reason}: {pos.ts_code} {quantity}股@{order.filled_price:.2f} trace={trace_id}")

        await self._persist_sell_state(scanner)

    @staticmethod
    def _classify_sell_stats(scanner, reason: str) -> None:
        """按卖出原因分类统计"""
        reason_lower = reason.lower() if isinstance(reason, str) else ""
        if reason_lower in ("stop_loss", "gap_stop_loss", "trailing_stop") or "止损" in reason:
            scanner._stats["stop_losses"] += 1
        elif reason_lower in ("take_profit", "profit_lock", "profit_protect") or "止盈" in reason:
            scanner._stats["take_profits"] += 1
        else:
            scanner._stats["trades_executed"] += 1

    @staticmethod
    async def _emit_sell_events(scanner, pos, reason, order, entry, profit_pct, *, trace_id: str = "") -> None:
        """发射卖出事件(timeline + EventBus)【v2.9.71: trace_id贯穿EventBus】"""
        try:
            await scanner._publish_scanner_event("timeline", {"item": entry})
        except Exception as _e:
            logger.debug(f"[SCANNER] timeline事件发射失败: {_e}")
        try:
            from nodes.market_monitor.scanner_event_bus import ScannerEvents
            event_data = {
                "ts_code": pos.ts_code, "reason": reason,
                "price": order.filled_price, "profit_pct": profit_pct,
                "trace_id": trace_id,
            }
            await scanner._event_bus.emit(ScannerEvents.RISK_SELL_EXECUTED, event_data)
            await scanner._event_bus.emit(ScannerEvents.POSITION_CHANGED, {
                "ts_code": pos.ts_code, "action": "sell", "reason": reason,
                "trace_id": trace_id,
            })
        except Exception as _e:
            logger.debug(f"[SCANNER] 卖出事件发射失败: {_e}")

    @staticmethod
    async def _persist_sell_state(scanner) -> None:
        """持久化broker状态+运行时快照"""
        is_virtual = getattr(scanner, '_trade_mode', '') in ('replay', 'dry_run')
        try:
            await scanner._broker.save_state(force=True, skip_if_virtual=is_virtual)
        except Exception as _e:
            logger.warning(f"[SCANNER] 卖出后broker状态持久化失败: {_e}")
        try:
            await scanner._save_runtime_snapshot(force=True)
        except Exception as _e:
            logger.warning(f"[SCANNER] 卖出后运行时快照失败: {_e}")
        # 【v2.9.94修复】卖出后立即保存timeline到MongoDB，防止进程崩溃时丢失
        # P0事故2026-06-15: 5笔卖出后scanner重启，timeline只在内存中未持久化，导致前端无当日交易明细
        try:
            await scanner._runtime_persistence.save_timeline()
        except Exception as _e:
            logger.warning(f"[SCANNER] 卖出后Timeline保存失败: {_e}")

    # ==================== 绩效快照+飞书日报(v2.9.6提取) ====================
    
    async def save_performance_snapshot(self, trade_date: str) -> None:
        """保存绩效快照到MongoDB(供净值曲线使用)
        
        从scanner._save_performance_snapshot提取【v2.9.6】
        """
        from core.managers import mongo_manager
        if not mongo_manager.db:
            return
        scanner = self._scanner
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        total_profit = acct.total_profit
        net_value = acct.total_assets / 1_000_000  # 初始100万
        peak = max(scanner._nav_peak, net_value)
        scanner._nav_peak = peak
        drawdown_pct = (net_value / peak - 1) * 100 if peak > 0 else 0

        doc = {
            "timestamp": datetime.now().isoformat(),
            "date": trade_date,
            "total_assets": acct.total_assets,
            "available_cash": acct.available_cash,
            "market_value": acct.market_value,
            "total_profit": total_profit,
            "net_value": net_value,
            "drawdown_pct": drawdown_pct,
            "position_count": len(positions),
            "position_ratio": sum((p.current_price or 0) * p.total_qty for p in positions) / acct.total_assets * 100 if acct.total_assets > 0 else 0,
        }
        await mongo_manager.db["performance_snapshots"].insert_one(doc)
        logger.info(f"[SNAPSHOT] 绩效快照已保存: 净值={net_value:.4f} 回撤={drawdown_pct:.1f}%")
    
    async def push_daily_summary(self, trade_date: str) -> None:
        """推送每日结算摘要(飞书/webhook)
        
        从scanner._push_daily_summary提取【v2.9.6】
        """
        scanner = self._scanner
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        # 今日买卖统计
        buys = [t for t in scanner._timeline if t.get("action") == "buy"]
        sells = [t for t in scanner._timeline if t.get("action") == "sell"]
        wins = [t for t in sells if t.get("profit_pct", 0) > 0]
        losses = [t for t in sells if t.get("profit_pct", 0) <= 0]
        profit_sign = '+' if acct.total_profit >= 0 else ''
        win_rate = f"{len(wins)/len(sells)*100:.0f}%" if sells else "-"
        pos_value = sum((p.current_price or 0) * p.total_qty for p in positions)
        pos_ratio = pos_value / acct.total_assets * 100 if acct.total_assets > 0 else 0

        summary = (
            f"📊 每日结算 {trade_date}\n"
            f"💰 总资产: ¥{acct.total_assets:,.0f} | 盈亏: {profit_sign}¥{acct.total_profit:,.0f}\n"
            f"📈 买入: {len(buys)}笔 | 卖出: {len(sells)}笔\n"
            f"✅ 盈利: {len(wins)}笔 | ❌ 亏损: {len(losses)}笔\n"
            f"📊 胜率: {win_rate}\n"
            f"📂 持仓: {len(positions)}只 | 仓位: {pos_ratio:.0f}%"
        )

        # 推送到飞书(如果有webhook)
        try:
            from nodes.market_monitor.signal_dispatcher import SignalDispatcher
            dispatcher = SignalDispatcher.get_instance()
            if dispatcher:
                await dispatcher.push_message(summary, channel="feishu")
        except ImportError:
            pass  # signal_dispatcher模块不存在时静默跳过
        except Exception as _e:
            logger.warning(f"[DAILY] 飞书日报推送失败: {_e}")
        logger.info(f"[DAILY] {summary}")
    
    # 【v2.9.93】删除：原此处定义的旧版 load_timeline 会覆盖 L389 的 v2.9.92f 修复版本，
    # 导致回退逻辑（fallback到"数据最多"的历史日）重新生效，把6/9旧timeline以今天的trade_date回写到数据库。
    # 真正生效的版本在 L389："只加载今天的数据，不回退到历史日期"。
    # P0事故记录：2026-06-15 08:30 启动时回退到6/9，污染scanner_timeline 1218条。

    # ==================== 数据加载方法【v2.9.32从scanner提取】 ====================

    async def load_stock_list(self) -> List[str]:
        """加载全市场代码(从stock_daily_ak_full)"""
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()

            today = datetime.now().strftime("%Y%m%d")
            cursor = mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": int(today)},
                {"ts_code": 1, "_id": 0}
            )
            docs = await cursor.to_list(length=6000)
            if not docs:
                latest = await mongo_manager.db["stock_daily_ak_full"].find_one(
                    sort=[("trade_date", -1)],
                    projection={"trade_date": 1, "_id": 0}
                )
                if latest:
                    cursor = mongo_manager.db["stock_daily_ak_full"].find(
                        {"trade_date": latest["trade_date"]},
                        {"ts_code": 1, "_id": 0}
                    )
                    docs = await cursor.to_list(length=6000)

            codes = [d["ts_code"] for d in docs if d.get("ts_code")]
            logger.info(f"[SCANNER] 加载{len(codes)}只股票代码")
            return codes
        except Exception as e:
            logger.error(f"[SCANNER] 加载股票列表失败: {e}")
            return []

    async def load_daily_factors(self, trade_date: str) -> Optional[pd.DataFrame]:
        """预加载日级因子(从MongoDB读取)"""
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()

            latest_doc = await mongo_manager.db["stock_daily_ak_full"].find_one(
                {"trade_date": {"$lte": int(trade_date)}},
                sort=[("trade_date", -1)],
                projection={"trade_date": 1, "_id": 0}
            )
            if not latest_doc:
                return None

            factor_date = latest_doc["trade_date"]
            factor_fields = [
                "ts_code", "pct_chg", "pre_close", "close", "open", "high", "low",
                "ma5", "macd", "rsi_6", "boll_upper", "atr",
                "turnover_rate", "volume_ratio", "circ_mv",
                "is_limit_up", "is_limit_down", "first_limit_up", "limit_up_count",
                "fear_greed_index"
            ]
            projection = {"_id": 0}
            for f in factor_fields:
                projection[f] = 1

            cursor = mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": factor_date},
                projection
            )
            docs = await cursor.to_list(length=6000)
            if docs:
                df = pd.DataFrame(docs)
                logger.info(f"[SCANNER] 加载{len(docs)}只股票日级因子(date={factor_date})")
                return df
        except Exception as e:
            logger.error(f"[SCANNER] 加载日级因子失败: {e}")
        return None

    async def load_stock_name_map(self) -> Dict[str, str]:
        """从MongoDB stock_basic加载ts_code→名称映射"""
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return {}
            docs = await mongo_manager.db["stock_basic"].find(
                {}, {"ts_code": 1, "name": 1, "_id": 0}
            ).to_list(length=None)
            name_map = {}
            for doc in docs:
                if doc.get("ts_code") and doc.get("name"):
                    name_map[doc["ts_code"]] = doc["name"]
            logger.info(f"[SCANNER] 加载{len(name_map)}只股票名称映射")
            return name_map
        except Exception as e:
            logger.warning(f"[SCANNER] 加载名称映射失败: {e}")
            return {}

    def warm_weekend_cache(self, daily_factors_df, stock_name_map: Dict[str, str],
                           quote_manager=None) -> Dict[str, Dict]:
        """周末调试: 用日级因子(上一交易日收盘)填充行情缓存
        
        Returns:
            realtime dict (由scanner写入_realtime_cache)
        """
        warmed = 0
        realtime = {}
        df = daily_factors_df
        if df is None or df.empty:
            return realtime

        for _, row in df.iterrows():
            ts_code = row.get("ts_code")
            if not ts_code:
                continue
            close = row.get("close")
            pre_close = row.get("pre_close")
            pct_chg = row.get("pct_chg")
            if close and close > 0:
                realtime[ts_code] = {
                    "price": close,
                    "pct_chg": pct_chg if pct_chg else 0,
                    "pre_close": pre_close if pre_close else close,
                    "open": row.get("open", close),
                    "high": row.get("high", close),
                    "low": row.get("low", close),
                    "vol": row.get("vol", 0),
                    "amount": row.get("amount", 0),
                    "turnover_rate": row.get("turnover_rate", 0),
                    "volume_ratio": row.get("volume_ratio", 0),
                    "name": stock_name_map.get(ts_code, ""),
                }
                warmed += 1

        if quote_manager:
            quote_manager.warm_sources_cache(realtime)

        logger.info(f"[SCANNER] 周末缓存预热: {warmed}只(上一交易日收盘价)")
        return realtime

    async def persist_stop_state(self) -> None:
        """停止时持久化状态: broker+timeline+runtime snapshot+pending_sells【v2.9.32从scanner提取】"""
        scanner = self._scanner
        broker = scanner._broker

        # 强制保存当前状态(跳过节流)
        # 【v2.9.92s】replay/dry_run模式不应把虚拟数据覆盖到MongoDB实盘数据
        is_virtual = getattr(scanner, '_trade_mode', '') in ('replay', 'dry_run')
        if broker:
            try:
                await broker.save_state(force=True, skip_if_virtual=is_virtual)
            except Exception as _e:
                logger.warning(f"[SCANNER] 停止时broker状态持久化失败: {_e}")
            await self.save_runtime_snapshot(force=True)

        # 保存时间线到MongoDB
        try:
            await self.save_timeline()
        except Exception as _e:
            logger.warning(f"[SCANNER] 停止时Timeline保存失败: {_e}")

        # 保存pending_sells状态到MongoDB(防止重启丢失)
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                from nodes.market_monitor.risk_watchdog import RiskWatchdog
                pending = RiskWatchdog._with_state_lock(
                    scanner, lambda: dict(scanner._pending_sells),
                    fallback=lambda: dict(scanner._pending_sells),
                )
                if pending:
                    await mongo_manager.db["scanner_state"].update_one(
                        {"_id": "pending_sells"},
                        {"$set": {"items": pending, "saved_at": datetime.now().isoformat()}},
                        upsert=True,
                    )
                    logger.info(f"[STOP] 保存{len(pending)}个pending_sells到MongoDB")
        except Exception as e:
            logger.debug(f"[STOP] pending_sells保存失败(非关键): {e}")

    async def restore_start_state(self) -> None:
        """启动时恢复状态(审计索引+pending_sells)【v2.9.32从scanner提取】"""
        scanner = self._scanner

        # 审计日志TTL索引(90天自动过期)
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                await mongo_manager.db["audit_log"].create_index(
                    "timestamp", expireAfterSeconds=7776000  # 90天
                )
                # 【v2.9.80】迁移旧数据: ISO字符串/float → datetime对象(TTL索引要求)
                try:
                    from datetime import datetime as _dt
                    migrated = 0
                    async for doc in mongo_manager.db["audit_log"].find(
                        {"timestamp": {"$type": "string"}}, {"_id": 1, "timestamp": 1}
                    ).limit(200):
                        try:
                            new_ts = _dt.fromisoformat(doc["timestamp"])
                            await mongo_manager.db["audit_log"].update_one(
                                {"_id": doc["_id"]}, {"$set": {"timestamp": new_ts}}
                            )
                            migrated += 1
                        except (ValueError, TypeError):
                            pass
                    if migrated:
                        logger.info(f"[START] 审计日志timestamp迁移: {migrated}条")
                    # 【v2.9.83修复】旧数据time字段→timestamp迁移(TTL覆盖)
                    try:
                        time_migrated = 0
                        async for doc in mongo_manager.db["audit_log"].find(
                            {"timestamp": {"$exists": False}, "time": {"$exists": True}},
                            {"_id": 1, "time": 1}
                        ).limit(200):
                            try:
                                old_time = doc.get("time", "")
                                if isinstance(old_time, str) and old_time:
                                    new_ts = _dt.fromisoformat(old_time)
                                elif isinstance(old_time, (int, float)):
                                    new_ts = _dt.fromtimestamp(old_time)
                                else:
                                    continue
                                await mongo_manager.db["audit_log"].update_one(
                                    {"_id": doc["_id"]}, {"$set": {"timestamp": new_ts}}
                                )
                                time_migrated += 1
                            except (ValueError, TypeError):
                                pass
                        if time_migrated:
                            logger.info(f"[START] 审计日志time→timestamp迁移: {time_migrated}条")
                    except Exception as _tme:
                        logger.debug(f"[START] 审计日志time迁移失败(非关键): {_tme}")
                except Exception as _me:
                    logger.debug(f"[START] 审计日志迁移失败(非关键): {_me}")
        except Exception as _e:
            logger.debug(f"[START] 审计日志TTL索引创建失败: {_e}")

        # 从MongoDB恢复pending_sells(上次停机时保存的跌停挂起)
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                doc = await mongo_manager.db["scanner_state"].find_one({"_id": "pending_sells"})
                if doc and doc.get("items"):
                    with scanner._state_lock:
                        scanner._pending_sells.update(doc["items"])
                    logger.info(f"[START] 恢复{len(doc['items'])}个pending_sells")
        except Exception as e:
            logger.debug(f"[START] pending_sells恢复失败(非关键): {e}")

    async def load_positions(self) -> None:
        """加载当前持仓(优先从MongoDB恢复, 否则从broker获取)
        
        【Phase1.1增强】恢复后同时恢复Scanner运行时状态(追踪止损/风险等级/跌停挂起等)
        Broker是持仓唯一权威来源, Scanner快照只存Scanner独有状态。
        【v2.9.32从scanner提取】
        """
        scanner = self._scanner
        if scanner._broker:
            try:
                restored = await scanner._broker.load_state()
                if restored and scanner._broker.positions:
                    logger.info(f"[SCANNER] 持仓已从MongoDB恢复: {len(scanner._broker.positions)}个")
            except Exception as e:
                logger.warning(f"[SCANNER] 持仓恢复失败(使用空持仓): {e}")

        # Scanner运行时状态恢复
        await self.load_runtime_snapshot()

        _pos_count = len(scanner._broker.get_positions()) if scanner._broker else 0
        _ts_count = len(scanner._safe_copy_trailing_stops())
        
        # 【v2.9.92n】持仓丢失检测：如果MongoDB恢复0持仓但broker_orders有未平仓买入，说明持仓丢失
        if _pos_count == 0 and scanner._broker:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    # 从broker_orders重建持仓 【v2.9.96i】排除 rolled_back 【v2.9.96j】用移动加权平均成本(避免清仓后重买成本叠加)
                    from collections import defaultdict
                    holdings = defaultdict(lambda: {"qty": 0, "total_cost": 0.0, "name": "", "strategy": "", "buy_date": ""})
                    async for doc in mongo_manager.db["broker_orders"].find(
                        {"account_id": scanner._broker.account.account_id,
                         "status": {"$in": ["filled", "partial"]}}
                    ).sort([("trade_date", 1), ("create_time", 1)]):
                        tc = doc.get("ts_code", "")
                        side = doc.get("side", "")
                        qty = doc.get("filled_qty", doc.get("quantity", 0))
                        price = doc.get("filled_price", doc.get("price", 0))
                        if not tc or not qty: continue
                        h = holdings[tc]
                        if side == "buy":
                            h["qty"] += qty
                            h["total_cost"] += qty * price
                            h["name"] = doc.get("stock_name") or h["name"]
                            h["strategy"] = doc.get("strategy") or h["strategy"]
                            h["buy_date"] = str(doc.get("trade_date", ""))
                        elif side == "sell" and h["qty"] > 0:
                            avg_cost = h["total_cost"] / h["qty"]
                            h["qty"] -= qty
                            h["total_cost"] -= avg_cost * qty
                            if h["qty"] == 0:
                                h["total_cost"] = 0.0
                    
                    restored_count = 0
                    for tc, h in holdings.items():
                        if h["qty"] <= 0:
                            continue
                        avg_cost = h["total_cost"] / h["qty"] if h["qty"] > 0 else 0
                        # 写入broker_positions
                        await mongo_manager.db["broker_positions"].update_one(
                            {"account_id": scanner._broker.account.account_id, "ts_code": tc},
                            {"$set": {
                                "account_id": scanner._broker.account.account_id,
                                "ts_code": tc,
                                "stock_name": h["name"],
                                "total_qty": h["qty"],
                                "available_qty": h["qty"],
                                "avg_cost": avg_cost,
                                "current_price": 0,
                                "profit_pct": 0,
                                "today_buy_qty": 0,
                                "strategy": h["strategy"],
                                "restored_from_orders": True,
                                "restored_at": datetime.now().isoformat(),
                            }},
                            upsert=True,
                        )
                        # 也加到内存
                        from nodes.market_monitor.broker import Position
                        scanner._broker.positions[tc] = Position(
                            ts_code=tc,
                            stock_name=h["name"],
                            total_qty=h["qty"],
                            available_qty=h["qty"],
                            avg_cost=avg_cost,
                            current_price=0,
                            profit_pct=0,
                            strategy=h["strategy"],
                        )
                        restored_count += 1
                    
                    if restored_count > 0:
                        _pos_count = restored_count
                        logger.warning(f"[SCANNER] ⚠️ 持仓丢失检测：从broker_orders恢复了{restored_count}只持仓！")
                        logger.warning(f"[SCANNER] 原因：进程崩溃时save_state()未执行，导致broker_positions为空")
            except Exception as e:
                logger.warning(f"[SCANNER] 持仓丢失检测失败: {e}")
        
        logger.info(f"[SCANNER] 持仓: {_pos_count}个, 追踪止损: {_ts_count}个")

    async def sync_close_data_to_mongo(self, trade_date: str) -> None:
        """收盘后同步内存数据到MongoDB(limit_list + daily_basic)
        
        【v2.9.34从scanner提取, v2.9.56:提取_build_limit_ops】
        将scanner内存中的涨跌停/行情数据
        批量写入MongoDB, 供情绪计算和历史回测使用。
        """
        from pymongo.operations import UpdateOne
        try:
            from core.managers import mongo_manager
        except ImportError:
            logger.warning("[SCANNER] mongo_manager不可用, 跳过数据同步")
            return
        if not mongo_manager.is_initialized:
            return
        db = mongo_manager.db
        td_int = int(trade_date)
        scanner = self._scanner
        
        # 1. 同步limit_pools → limit_list
        limit_pools = getattr(scanner, '_limit_pools', None) or {}
        ops = self._build_limit_ops(limit_pools, td_int)
        if ops:
            result = await db["limit_list"].bulk_write(ops)
            logger.info(f"[SCANNER] limit_list同步: {result.upserted_count}新增 {result.modified_count}更新")
        
        # 2. 同步realtime_cache的pct_chg → daily_basic(补pct_chg字段)
        await self._sync_pct_chg_to_daily_basic(scanner._realtime_cache, td_int, db)

    def _build_limit_ops(self, limit_pools: Dict, td_int: int) -> List:
        """构建limit_list的bulk_write操作【v2.9.56从sync_close_data_to_mongo提取】"""
        from pymongo.operations import UpdateOne
        lu_list = limit_pools.get("limit_up", [])
        ld_list = limit_pools.get("limit_down", [])
        broken_list = limit_pools.get("broken", [])
        if not (lu_list or ld_list):
            return []
        ops = []
        for item in lu_list:
            ops.append(UpdateOne(
                {"trade_date": td_int, "ts_code": item.get("ts_code", "")},
                {"$set": {"trade_date": td_int, "ts_code": item.get("ts_code", ""), "name": item.get("name", ""), "limit": "U",
                 "close": item.get("close", 0), "limit_times": item.get("limit_times", 1),
                 "first_time": item.get("first_time", ""), "last_time": item.get("last_time", ""),
                 "data_source": "scanner_realtime"}},
                upsert=True
            ))
        for item in ld_list:
            ops.append(UpdateOne(
                {"trade_date": td_int, "ts_code": item.get("ts_code", "")},
                {"$set": {"trade_date": td_int, "ts_code": item.get("ts_code", ""), "name": item.get("name", ""), "limit": "D",
                 "close": item.get("close", 0), "limit_times": item.get("limit_times", 1),
                 "first_time": item.get("first_time", ""), "last_time": item.get("last_time", ""),
                 "data_source": "scanner_realtime"}},
                upsert=True
            ))
        for item in broken_list:
            ops.append(UpdateOne(
                {"trade_date": td_int, "ts_code": item.get("ts_code", "")},
                {"$set": {"trade_date": td_int, "ts_code": item.get("ts_code", ""), "name": item.get("name", ""), "limit": "U",
                 "close": item.get("close", 0), "limit_times": item.get("limit_times", 1),
                 "amp": item.get("amp", 0), "data_source": "scanner_realtime"}},
                upsert=True
            ))
        return ops

    async def _sync_pct_chg_to_daily_basic(self, realtime_cache: Dict, td_int: int, db) -> None:
        """同步pct_chg字段到daily_basic【v2.9.56从sync_close_data_to_mongo提取, v2.9.76修复】
        
        优先级:
        1. realtime_cache中的pct_chg(scanner实时行情)
        2. stock_daily_ak_full中的pct_chg(东财日线, 始终有值)
        
        注意: daily_basic原始数据源(东财daily_basic接口)不含pct_chg字段,
        必须从stock_daily_ak_full回填!
        """
        from pymongo.operations import UpdateOne
        pct_ops = []
        synced = 0
        
        # 1. 先从realtime_cache写pct_chg(scanner实时行情)
        if realtime_cache:
            for ts_code, quote in realtime_cache.items():
                pct_chg = quote.get("pct_chg")
                if pct_chg is not None:
                    pct_ops.append(UpdateOne(
                        {"trade_date": td_int, "ts_code": ts_code, "pct_chg": None},
                        {"$set": {"pct_chg": pct_chg, "data_source": "scanner_realtime"}}
                    ))
                    synced += 1
                    if len(pct_ops) >= 500:
                        await db["daily_basic"].bulk_write(pct_ops)
                        pct_ops = []
        
        # 2. 批量从stock_daily_ak_full回填pct_chg(填补实时行情未覆盖的)
        # daily_basic原始数据不含pct_chg,必须从stock_daily_ak_full补
        # 【v2.9.99修复】扩大回填范围: 不仅填null，也填pct_chg=0但stock_daily有非零值的
        # (eastmoney_daily_basic.py可能写入pct_chg=0.0当f3字段不可用时)
        try:
            pipeline = [
                {"$match": {"trade_date": td_int, "pct_chg": {"$ne": None}}},
                {"$project": {"ts_code": 1, "pct_chg": 1, "_id": 0}},
            ]
            fill_ops = []
            filled = 0
            async for doc in db["stock_daily_ak_full"].aggregate(pipeline):
                src_pct = doc.get("pct_chg")
                # 回填条件: daily_basic中pct_chg为null/不存在，或为0但source有非零值
                # 【v2.9.100修复】$expr+普通条件混用导致MongoDB查询不匹配
                # 改为Python侧判断src_pct是否非零，简化MongoDB查询条件
                if src_pct and src_pct != 0:
                    # source非零 → 回填null/不存在/pct_chg=0的记录
                    filter_q = {
                        "trade_date": td_int,
                        "ts_code": doc["ts_code"],
                        "$or": [
                            {"pct_chg": None},
                            {"pct_chg": {"$exists": False}},
                            {"pct_chg": 0},
                        ],
                    }
                else:
                    # source也是0 → 只回填null/不存在的记录(不覆盖已有的0)
                    filter_q = {
                        "trade_date": td_int,
                        "ts_code": doc["ts_code"],
                        "$or": [
                            {"pct_chg": None},
                            {"pct_chg": {"$exists": False}},
                        ],
                    }
                fill_ops.append(UpdateOne(
                    filter_q,
                    {"$set": {"pct_chg": src_pct, "data_source": "stock_daily_ak_full"}}
                ))
                filled += 1
                if len(fill_ops) >= 500:
                    result = await db["daily_basic"].bulk_write(fill_ops)
                    synced += result.modified_count
                    fill_ops = []
            if fill_ops:
                result = await db["daily_basic"].bulk_write(fill_ops)
                synced += result.modified_count
            if filled > 0:
                logger.info(f"[SCANNER] daily_basic pct_chg从stock_daily_ak_full回填: {filled}只")
        except Exception as e:
            logger.warning(f"[SCANNER] daily_basic pct_chg回填失败: {e}")
        
        if pct_ops:
            await db["daily_basic"].bulk_write(pct_ops)
        if synced > 0:
            logger.info(f"[SCANNER] daily_basic pct_chg同步: {synced}只")

    # ==================== 盘后结算 ====================

    async def daily_settlement(self, trade_date: str) -> None:
        """盘后结算处理(Broker结算+持久化+EventBus+Timeline+情绪预计算+数据同步)

        从scanner._scan_loop_settlement提取【v2.9.39】
        职责: Broker日终结算+状态持久化+EventBus事件+Timeline保存+收盘数据同步
        """
        # 1. Broker日终结算+状态持久化
        if self.broker:
            self.broker.daily_settlement(trade_date)
        _tm = self._scanner._trade_mode if hasattr(self._scanner, '_trade_mode') else ''
        is_virtual = _tm in ('replay', 'dry_run')
        try:
            await self.broker.save_state(skip_if_virtual=is_virtual)
        except Exception as _e:
            logger.warning(f"[SCANNER] 盘后结算broker状态持久化失败: {_e}")
        logger.info("[SCANNER] 收盘自动结算+持久化完成")

        # 2. EventBus盘后结算事件(驱动绩效快照+飞书日报)
        try:
            account = self.broker.account if self.broker else None
            from nodes.market_monitor.scanner_event_bus import ScannerEvents
            await self._scanner._event_bus.emit(ScannerEvents.DAILY_SETTLED, {
                "trade_date": trade_date,
                "total_profit": account.today_profit if account else 0,
                "total_assets": account.total_assets if account else 0,
            })
        except Exception as _e:
            logger.warning(f"[SCANNER] 盘后结算事件发射失败: {_e}")

        # 3. 保存Timeline到MongoDB
        try:
            await self._scanner._save_timeline()
        except Exception as _e:
            logger.warning(f"[SCANNER] 盘后Timeline保存失败: {_e}")

        # 4. 收盘后更新情绪预计算
        try:
            await self._scanner._update_sentiment_score(trade_date)
        except Exception as _e:
            logger.warning(f"[SCANNER] 盘后情绪预计算失败: {_e}")

        # 5. 收盘后同步内存数据到MongoDB
        try:
            await self._scanner._sync_close_data_to_mongo(trade_date)
        except Exception as _e:
            logger.warning(f"[SCANNER] 盘后数据同步失败: {_e}")

    async def persist_scan_result(self) -> None:
        """扫描结果持久化: broker状态+时间线+运行时快照【v2.9.41:从scanner._persist_scan_result提取】"""
        _tm = self._scanner._trade_mode if hasattr(self._scanner, '_trade_mode') else ''
        is_virtual = _tm in ('replay', 'dry_run')
        try:
            if self.broker:
                saved = await self.broker.save_state(skip_if_virtual=is_virtual)
                logger.info(f"[SCAN] save_state={saved} positions={len(self.broker.positions)} orders={len(self.broker.orders)}")
            await self._scanner._save_timeline()
            await self._scanner._save_runtime_snapshot(force=False)
        except Exception as _e:
            logger.warning(f"[SCAN] save_state失败: {_e}")

    async def persist_compare_diff(self, trade_date: str, only_legacy: set, only_checker: set,
                                   both: set, legacy_sell: list, checker_results: list,
                                   realtime_data: Dict) -> None:
        """compare差异持久化到MongoDB【v2.9.45提取, v2.9.56:提取_diff_details构建】
        
        将legacy/checker卖出差异记录到sell_compare_diff集合,
        用于事后审计和分析, 评估checker模式何时可以替代legacy。
        TTL: 30天自动过期
        """
        try:
            from core.managers import mongo_manager
            if not mongo_manager or not mongo_manager._client:
                return
            
            db = mongo_manager.db
            diff_details = self._build_compare_diff_details(
                only_legacy, only_checker, legacy_sell, checker_results, realtime_data
            )
            
            doc = {
                "trade_date": trade_date,
                "time": datetime.now().strftime("%H:%M:%S"),
                "only_legacy": list(only_legacy),
                "only_checker": list(only_checker),
                "both": list(both),
                "diff_details": diff_details,
                "summary": {
                    "total_legacy": len(only_legacy) + len(both),
                    "total_checker": len(only_checker) + len(both),
                    "agreement_rate": round(len(both) / max(len(only_legacy | only_checker | both), 1) * 100, 1),
                },
            }
            
            await db["sell_compare_diff"].insert_one(doc)
            
            # 创建TTL索引(30天, 幂等)
            try:
                await db["sell_compare_diff"].create_index(
                    "time", name="ttl_30d_compare", expireAfterSeconds=30 * 86400
                )
            except Exception as _e:
                pass  # 索引已存在
            
            logger.info(f"[COMPARE] 差异已持久化: "
                        f"一致率={doc['summary']['agreement_rate']}% "
                        f"仅legacy={len(only_legacy)} 仅checker={len(only_checker)}")
            
        except Exception as e:
            logger.debug(f"[COMPARE] 差异持久化失败: {e}")

    def _build_compare_diff_details(self, only_legacy: set, only_checker: set,
                                    legacy_sell: list, checker_results: list,
                                    realtime_data: Dict) -> Dict:
        """构建compare差异详情【v2.9.56从persist_compare_diff提取】"""
        diff_details = {}
        for code in only_legacy | only_checker:
            detail = {"code": code}
            for pos, reason, _, _ in legacy_sell:
                if pos.ts_code == code:
                    detail["legacy_reason"] = reason
                    detail["legacy_profit_pct"] = round(pos.profit_pct, 2)
                    detail["strategy"] = pos.strategy
                    break
            for pos, reason, _, _, _ in checker_results:
                if pos.ts_code == code:
                    detail["checker_reason"] = reason
                    detail["checker_profit_pct"] = round(pos.profit_pct, 2)
                    break
            rt = realtime_data.get(code, {})
            detail["price"] = rt.get("price", 0)
            detail["pct_chg"] = rt.get("pct_chg", 0)
            diff_details[code] = detail
        return diff_details

    async def save_param_snapshot(self, trade_date: str) -> None:
        """启动时保存参数快照(供月复盘参数漂移检测)【v2.9.42:从scanner._save_param_snapshot提取】
        
        修复: 优先从strategy_overrides读取覆盖后的参数, 而非原始strategies配置
        【V75-审计修复】同时读取strategy-config API的覆盖(scanner_config.strategy_config_overrides),
        确保前端API修改的参数不遗漏
        """
        try:
            from core.managers import mongo_manager as mm
            if mm.is_initialized:
                scanner_config = self._scanner.config
                today = trade_date or datetime.now().strftime("%Y%m%d")
                
                # 读取策略参数: 优先从strategy_overrides(覆盖后), 否则从strategies(原始)
                strategies = scanner_config.get("strategies", {})
                strategy_overrides = scanner_config.get("strategy_overrides", {})
                global_risk = scanner_config.get("global_risk", {})
                
                # 【V75-审计修复】同时读取strategy-config API的运行时覆盖
                # 问题: 前端通过strategy-config API修改的参数存在scanner_config.strategy_config_overrides中,
                # 与strategy_overrides(scanner内部持久化)是两套独立存储,之前只读了后者导致遗漏
                api_overrides = {}
                api_risk_overrides = {}
                api_enabled_overrides = {}
                api_global_risk = {}
                try:
                    override_doc = await mm.db["scanner_config"].find_one(
                        {"_id": "strategy_config_overrides"}
                    )
                    if override_doc and "data" in override_doc:
                        api_overrides = override_doc["data"].get("params", {})
                        api_risk_overrides = override_doc["data"].get("risk", {})
                        api_enabled_overrides = override_doc["data"].get("enabled", {})
                        api_global_risk = override_doc["data"].get("global_risk", {})
                except Exception as _e:
                    logger.debug(f"[GUARD] runtime_persistence: {_e}")
                
                # 构建快照: 合并strategies + strategy_overrides + api_overrides
                merged_strategies = {}
                for sid, cfg in strategies.items():
                    merged_cfg = {
                        "enabled": cfg.get("enabled", True),
                        "params": dict(cfg.get("params", {})),
                        "riskParams": dict(cfg.get("riskParams", {})),
                    }
                    # 应用strategy_overrides覆盖
                    if sid in strategy_overrides:
                        override = strategy_overrides[sid]
                        if "params" in override:
                            merged_cfg["params"].update(override["params"])
                        if "riskParams" in override:
                            merged_cfg["riskParams"].update(override["riskParams"])
                        if "enabled" in override:
                            merged_cfg["enabled"] = override["enabled"]
                    # 应用strategy-config API覆盖(最高优先级)
                    if sid in api_overrides:
                        merged_cfg["params"].update(api_overrides[sid])
                    if sid in api_risk_overrides:
                        merged_cfg["riskParams"].update(api_risk_overrides[sid])
                    if sid in api_enabled_overrides:
                        merged_cfg["enabled"] = api_enabled_overrides[sid]
                    merged_strategies[sid] = merged_cfg
                
                # 也加入overrides中存在但strategies中没有的策略
                for sid, override in strategy_overrides.items():
                    if sid not in merged_strategies:
                        merged_strategies[sid] = {
                            "enabled": override.get("enabled", True),
                            "params": dict(override.get("params", {})),
                            "riskParams": dict(override.get("riskParams", {})),
                        }
                # 也加入API覆盖中存在但以上都未覆盖的策略
                for sid in set(list(api_overrides.keys()) + list(api_risk_overrides.keys()) + list(api_enabled_overrides.keys())):
                    if sid not in merged_strategies:
                        # 不引用回测模块, 从已遍历的strategies或空白配置回退
                        base_cfg = strategies.get(sid, {})
                        merged_strategies[sid] = {
                            "enabled": api_enabled_overrides.get(sid, base_cfg.get("enabled", True)),
                            "params": {**base_cfg.get("params", {}), **api_overrides.get(sid, {})},
                            "riskParams": {**base_cfg.get("riskParams", {}), **api_risk_overrides.get(sid, {})},
                        }
                
                # 合并全局风控: scanner.config.global_risk + API覆盖(深层合并, 避免嵌套dict被整体替换)
                merged_global_risk = {k: v for k, v in global_risk.items() if not k.startswith("__")} if global_risk else {}
                for k, v in api_global_risk.items():
                    if k in merged_global_risk and isinstance(merged_global_risk[k], dict) and isinstance(v, dict):
                        merged_dict = dict(merged_global_risk[k])
                        merged_dict.update(v)
                        merged_global_risk[k] = merged_dict
                    else:
                        merged_global_risk[k] = v
                
                snapshot = {
                    "date": today,
                    "global_risk": merged_global_risk,
                    "strategies": merged_strategies,
                }
                await mm.db["param_snapshots"].update_one(
                    {"date": today}, {"$set": snapshot}, upsert=True
                )
                logger.info(f"[SCANNER] 参数快照已保存({today}), {len(merged_strategies)}个策略")
        except Exception as e:
            logger.warning(f"[SCANNER] 参数快照保存失败: {e}")
