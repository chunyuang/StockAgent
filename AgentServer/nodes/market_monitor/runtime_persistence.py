"""
RuntimePersistence — 运行时状态持久化

从MarketScanner拆分出来(Phase3.1)。
负责:
- 运行时快照保存/加载(MongoDB scanner_runtime_snapshot)
- 时间线保存/加载(MongoDB scanner_timeline)
- 扫描链路追踪保存(MongoDB scan_traces)
- 盘前竞价处理
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

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
    def broker(self):
        return self._scanner._broker
    
    @property
    def account_id(self) -> str:
        return self._scanner.account_id
    
    # ==================== 运行时快照 ====================
    
    async def load_runtime_snapshot(self):
        """从MongoDB加载运行时快照(启动时恢复)
        
        优先MongoDB, 失败时回退本地文件
        """
        doc = None
        
        # 尝试MongoDB
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is not None:
                doc = await mongo_manager.db["scanner_runtime_snapshot"].find_one(
                    {"account_id": self.account_id}
                )
        except Exception as e:
            logger.warning(f"[SNAPSHOT] MongoDB加载失败: {e}")
        
        # MongoDB失败→回退本地文件
        if not doc:
            try:
                local_path = self._get_local_fallback_path()
                if os.path.exists(local_path):
                    with open(local_path, 'r') as f:
                        doc = json.load(f)
                    logger.info(f"[SNAPSHOT] 从本地降级文件恢复: {local_path}")
            except Exception as e:
                logger.debug(f"[SNAPSHOT] 本地文件加载失败: {e}")
        
        if not doc:
            return
        
        # 【v2.9:跨日检查—如果是昨天的快照,只恢复非日期相关的持久状态】
        snapshot_date = doc.get("trade_date", "")
        today = datetime.now().strftime("%Y%m%d")
        is_same_day = (snapshot_date == today)
        if not is_same_day and snapshot_date:
            logger.info(f"[SNAPSHOT] 快照日期={snapshot_date}, 今日={today}, 跳过日期相关状态恢复")
        
        scanner = self._scanner
        
        # 恢复追踪止损(线程安全) — 仅恢复同日数据
        if is_same_day:
            with scanner._state_lock:
                if "trailing_stops" in doc:
                    scanner._trailing_stops = doc["trailing_stops"]
                    logger.info(f"[SNAPSHOT] 恢复追踪止损: {len(scanner._trailing_stops)}只")
                
                # 恢复风险等级
                if "position_risk_levels" in doc:
                    scanner._position_risk_levels = doc["position_risk_levels"]
                
                # 恢复pending_sells — 已在外层state_lock内, 不再加锁
                if "pending_sells" in doc:
                    scanner._pending_sells = doc["pending_sells"]
                    logger.info(f"[SNAPSHOT] 恢复待卖: {len(scanner._pending_sells)}只")
        
        # 恢复风控状态
        if "circuit_breaker" in doc:
            cb = doc["circuit_breaker"]
            # 只恢复连续亏损, 不恢复trading_paused(重启后应该重新评估)
            scanner._circuit_breaker["consecutive_losses"] = cb.get("consecutive_losses", 0)
            scanner._circuit_breaker["today_trades"] = cb.get("today_trades", 0)
            scanner._circuit_breaker["today_losses"] = cb.get("today_losses", 0)
        
        # 恢复统计
        if "stats" in doc:
            scanner._stats.update(doc["stats"])
        
        # 【v2.9:恢复行情降级状态】
        if "quote_degrade_level" in doc and scanner._quote_manager:
            scanner._quote_degrade_level = doc["quote_degrade_level"]
            scanner._quote_manager._quote_degrade_level = doc["quote_degrade_level"]
            if doc["quote_degrade_level"] > 0:
                scanner._quote_manager._degrade_since = time.monotonic()
                scanner._quote_manager._last_recover_attempt = time.monotonic()
                logger.info(f"[SNAPSHOT] 恢复行情降级: level={doc['quote_degrade_level']}")
        
        logger.info(f"[SNAPSHOT] 加载运行时快照成功")
    
    async def save_runtime_snapshot(self, force: bool = False):
        """保存运行时快照到MongoDB
        
        节流: 默认5秒保存一次, force=True跳过节流
        MongoDB不可用时降级写本地文件
        """
        scanner = self._scanner
        
        now = time.time()
        if not force:
            last_save = getattr(scanner, '_last_snapshot_save', 0)
            if now - last_save < 5:  # v2.1: 5秒节流(原30秒太长, 崩溃后丢失多)
                return
        
        doc = {
            "account_id": self.account_id,
            "updated_at": datetime.now().isoformat(),
        }
        
        # 线程安全读取共享状态
        with scanner._state_lock:
            doc["trailing_stops"] = dict(scanner._trailing_stops)
            doc["position_risk_levels"] = dict(getattr(scanner, '_position_risk_levels', {}))
            doc["pending_sells"] = dict(getattr(scanner, '_pending_sells', {}))
        
        doc["circuit_breaker"] = scanner._circuit_breaker
        doc["stats"] = dict(scanner._stats)
        doc["active_signals_count"] = len(scanner._active_signals)
        doc["dry_run"] = scanner._dry_run
        doc["trade_date"] = getattr(scanner, '_trade_date', '')  # 【v2.9:快照中保存trade_date,重启后恢复】
        doc["quote_degrade_level"] = getattr(scanner, '_quote_degrade_level', 0)  # 【v2.9:恢复行情降级状态】
        
        saved = False
        
        # 尝试MongoDB
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is not None:
                await mongo_manager.db["scanner_runtime_snapshot"].update_one(
                    {"account_id": self.account_id},
                    {"$set": doc},
                    upsert=True,
                )
                scanner._last_snapshot_save = now
                saved = True
                # MongoDB成功后清理本地降级文件
                self._cleanup_local_fallback()
        except Exception as e:
            logger.debug(f"[SNAPSHOT] MongoDB保存失败: {e}")
        
        # MongoDB失败→降级写本地文件
        if not saved:
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
    
    def _cleanup_local_fallback(self):
        """MongoDB恢复后清理本地降级文件"""
        try:
            path = self._get_local_fallback_path()
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"[SNAPSHOT] 清理本地降级文件: {path}")
        except Exception:
            pass
    
    # ==================== 盘前竞价 ====================
    
    async def premarket_auction(self):
        """盘前竞价: 从持仓中筛选竞价异常股
        
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
    
    async def save_timeline(self):
        """保存时间线到MongoDB(追加模式, 不删除历史)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = datetime.now().strftime("%Y%m%d")
            scanner = self._scanner
            if not scanner._timeline:
                return
            
            docs = []
            for item in scanner._timeline:
                doc = dict(item)
                doc["account_id"] = self.broker.account.account_id if self.broker else "default"
                doc["trade_date"] = today
                docs.append(doc)
            
            # 去重
            existing_keys = set()
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": docs[0]["account_id"], "trade_date": today},
                {"time": 1, "ts_code": 1, "action": 1, "_id": 0}
            ):
                existing_keys.add(f"{doc.get('time','')}|{doc.get('ts_code','')}|{doc.get('action','')}")
            
            new_docs = [d for d in docs if f"{d.get('time','')}|{d.get('ts_code','')}|{d.get('action','')}" not in existing_keys]
            if new_docs:
                await mongo_manager.db["scanner_timeline"].insert_many(new_docs)
                logger.info(f"[SCAN] 保存时间线: {len(new_docs)}条新增")
        except Exception as e:
            logger.info(f"[SCAN] 保存时间线失败(非关键): {e}")
    
    async def save_scan_traces(self, filter_result):
        """保存扫描链路追踪到MongoDB
        
        优化：rejected候选只保存摘要(不含layer_results)，减少文档体积
        每次扫描3000+候选×layer_results会导致文档>1MB，列表查询返回20MB+
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            if not filter_result or not filter_result.trace_candidates:
                return
            
            today = datetime.now().strftime("%Y%m%d")
            
            # 分离passed和rejected候选
            passed_candidates = []
            rejected_summary = []  # rejected只保留摘要信息，不保存layer_results
            
            for t in filter_result.trace_candidates:
                if t.final_status == "passed":
                    # passed候选保留完整layer_results（数量少，且是关注重点）
                    passed_candidates.append({
                        "ts_code": t.ts_code,
                        "stock_name": t.stock_name,
                        "strategy": t.strategy,
                        "strategy_name": t.strategy_name,
                        "price": t.price,
                        "pct_chg": t.pct_chg,
                        "final_status": t.final_status,
                        "rejection_layer": t.final_rejection_layer,
                        "rejection_reason": t.final_rejection_reason,
                        "layer_results": t.layer_results,
                    })
                else:
                    # rejected候选只保存摘要（数量巨大，layer_results占空间）
                    rejected_summary.append({
                        "ts_code": t.ts_code,
                        "stock_name": t.stock_name,
                        "strategy": t.strategy,
                        "strategy_name": t.strategy_name,
                        "price": t.price,
                        "pct_chg": t.pct_chg,
                        "final_status": t.final_status,
                        "rejection_layer": t.final_rejection_layer,
                        "rejection_reason": t.final_rejection_reason,
                        # 不保存 layer_results — 这是体积大头
                    })
            
            trace_doc = {
                "trade_date": today,
                "scan_time": datetime.now().isoformat(),
                "account_id": self.broker.account.account_id if self.broker else "default",
                "summary": {},
                "candidates": passed_candidates,
                "rejected_summary": rejected_summary,
            }
            
            for layer, stats in filter_result.trace_summary.items():
                trace_doc["summary"][layer] = dict(stats)
            trace_doc["summary"]["total_candidates"] = len(filter_result.trace_candidates)
            trace_doc["summary"]["passed"] = len(passed_candidates)
            trace_doc["summary"]["rejected"] = len(rejected_summary)
            # 【v2.9.17:保存layer_details(每层的决策描述)】
            trace_doc["layer_details"] = dict(filter_result.layer_details)
            
            await mongo_manager.db["scan_traces"].insert_one(trace_doc)
            logger.info(f"[SCAN] 保存链路追踪: {len(passed_candidates)} passed + {len(rejected_summary)} rejected (节省layer_results)")
        except Exception as e:
            logger.warning(f"[SCAN] 保存链路追踪失败(非关键): {e}")
    
    async def load_timeline(self):
        """从MongoDB加载时间线(启动时恢复)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = datetime.now().strftime("%Y%m%d")
            account_id = self.broker.account.account_id if self.broker else "default"
            scanner = self._scanner
            
            cursor = mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id, "trade_date": today}
            ).sort("_id", 1)
            
            async for doc in cursor:
                doc.pop("_id", None)
                doc.pop("account_id", None)
                doc.pop("trade_date", None)
                scanner._timeline.append(doc)
            
            if scanner._timeline:
                logger.info(f"[SCAN] 恢复时间线: {len(scanner._timeline)}条")
        except Exception as e:
            logger.debug(f"[SCAN] 加载时间线失败(非关键): {e}")

    # ==================== 绩效快照+飞书日报(v2.9.6提取) ====================
    
    async def save_performance_snapshot(self, trade_date: str):
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
            "position_ratio": sum(p.current_price * p.total_qty for p in positions) / acct.total_assets * 100 if acct.total_assets > 0 else 0,
        }
        await mongo_manager.db["performance_snapshots"].insert_one(doc)
        logger.info(f"[SNAPSHOT] 绩效快照已保存: 净值={net_value:.4f} 回撤={drawdown_pct:.1f}%")
    
    async def push_daily_summary(self, trade_date: str):
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
        pos_value = sum(p.current_price * p.total_qty for p in positions)
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
            from core.managers.signal_dispatcher import SignalDispatcher
            dispatcher = SignalDispatcher.get_instance()
            if dispatcher:
                await dispatcher.push_message(summary, channel="feishu")
        except Exception:
            pass
        logger.info(f"[DAILY] {summary}")
    
    async def load_timeline(self):
        """从MongoDB加载时间线(启动时恢复)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = datetime.now().strftime("%Y%m%d")
            account_id = self.broker.account.account_id if self.broker else "default"
            scanner = self._scanner
            
            cursor = mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id, "trade_date": today}
            ).sort("_id", 1)
            
            async for doc in cursor:
                doc.pop("_id", None)
                doc.pop("account_id", None)
                doc.pop("trade_date", None)
                scanner._timeline.append(doc)
            
            if scanner._timeline:
                logger.info(f"[SCAN] 恢复时间线: {len(scanner._timeline)}条")
        except Exception as e:
            logger.debug(f"[SCAN] 加载时间线失败(非关键): {e}")
