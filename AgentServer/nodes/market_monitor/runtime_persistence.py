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
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("runtime_persistence")


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
        """从MongoDB加载运行时快照(启动时恢复)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            
            doc = await mongo_manager.db["scanner_runtime_snapshot"].find_one(
                {"account_id": self.account_id}
            )
            if not doc:
                return
            
            scanner = self._scanner
            
            # 恢复追踪止损
            if "trailing_stops" in doc:
                scanner._trailing_stops = doc["trailing_stops"]
                logger.info(f"[SNAPSHOT] 恢复追踪止损: {len(scanner._trailing_stops)}只")
            
            # 恢复风险等级
            if "position_risk_levels" in doc:
                scanner._position_risk_levels = doc["position_risk_levels"]
            
            # 恢复风控状态
            if "circuit_breaker" in doc:
                cb = doc["circuit_breaker"]
                # 只恢复连续亏损, 不恢复trading_paused(重启后应该重新评估)
                scanner._circuit_breaker["consecutive_losses"] = cb.get("consecutive_losses", 0)
                scanner._circuit_breaker["today_trades"] = cb.get("today_trades", 0)
                scanner._circuit_breaker["today_losses"] = cb.get("today_losses", 0)
            
            # 恢复pending_sells
            if "pending_sells" in doc:
                scanner._pending_sells = doc["pending_sells"]
                logger.info(f"[SNAPSHOT] 恢复待卖: {len(scanner._pending_sells)}只")
            
            # 恢复统计
            if "stats" in doc:
                scanner._stats.update(doc["stats"])
            
            logger.info(f"[SNAPSHOT] 加载运行时快照成功")
        except Exception as e:
            logger.warning(f"[SNAPSHOT] 加载运行时快照失败: {e}")
    
    async def save_runtime_snapshot(self, force: bool = False):
        """保存运行时快照到MongoDB
        
        节流: 默认30秒保存一次, force=True跳过节流
        """
        scanner = self._scanner
        
        now = time.time()
        if not force:
            last_save = getattr(scanner, '_last_snapshot_save', 0)
            if now - last_save < 30:
                return
        
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            
            doc = {
                "account_id": self.account_id,
                "updated_at": datetime.now().isoformat(),
                "trailing_stops": scanner._trailing_stops,
                "position_risk_levels": getattr(scanner, '_position_risk_levels', {}),
                "circuit_breaker": scanner._circuit_breaker,
                "pending_sells": getattr(scanner, '_pending_sells', {}),
                "stats": dict(scanner._stats),
                "active_signals_count": len(scanner._active_signals),
                "dry_run": scanner._dry_run,
            }
            
            await mongo_manager.db["scanner_runtime_snapshot"].update_one(
                {"account_id": self.account_id},
                {"$set": doc},
                upsert=True,
            )
            scanner._last_snapshot_save = now
        except Exception as e:
            logger.debug(f"[SNAPSHOT] 保存运行时快照失败(非关键): {e}")
    
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
                scanner._position_risk_levels[pos.ts_code] = "strong_open"
            elif gap_pct < -2:
                logger.warning(f"[AUCTION] {pos.ts_code} {pos.stock_name} 竞价低开{gap_pct:.1f}%")
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
        """保存扫描链路追踪到MongoDB"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            if not filter_result or not filter_result.trace_candidates:
                return
            
            today = datetime.now().strftime("%Y%m%d")
            trace_doc = {
                "trade_date": today,
                "scan_time": datetime.now().isoformat(),
                "account_id": self.broker.account.account_id if self.broker else "default",
                "summary": {},
                "candidates": [],
            }
            
            for layer, stats in filter_result.trace_summary.items():
                trace_doc["summary"][layer] = dict(stats)
            trace_doc["summary"]["total_candidates"] = len(filter_result.trace_candidates)
            trace_doc["summary"]["passed"] = len([t for t in filter_result.trace_candidates if t.final_status == "passed"])
            trace_doc["summary"]["rejected"] = len([t for t in filter_result.trace_candidates if t.final_status == "rejected"])
            
            for t in filter_result.trace_candidates:
                trace_doc["candidates"].append({
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
            
            await mongo_manager.db["scan_traces"].insert_one(trace_doc)
            logger.info(f"[SCAN] 保存链路追踪: {trace_doc['summary']['total_candidates']}候选")
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
