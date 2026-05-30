"""
SignalManager — 信号管理与执行管理器

从MarketScanner拆分出来(Phase3.1)。
负责:
- 信号增量更新+过期清理
- 信号推送(飞书/Redis)
- 信号执行(SimulatedBroker撮合)
- 时间线日志+审计日志

设计原则:
1. 信号执行依赖Broker/熔断/仓位等,通过scanner引用访问
2. 审计日志失败不影响主流程
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from nodes.market_monitor.scanner import ScanSignal

logger = logging.getLogger("signal_manager")


class SignalManager:
    """
    信号管理与执行管理器
    
    用法:
        sm = SignalManager(scanner)
        await sm.update_signals(new_signals, scan_time)
        await sm.execute_signals(signals)
    """
    
    def __init__(self, scanner):
        """
        Args:
            scanner: MarketScanner实例
        """
        self._scanner = scanner
    
    # ==================== 属性代理 ====================
    
    @property
    def broker(self):
        return self._scanner._broker
    
    @property
    def config(self) -> Dict:
        return self._scanner.config
    
    @property
    def active_signals(self) -> List[ScanSignal]:
        return self._scanner._active_signals
    
    @active_signals.setter
    def active_signals(self, value):
        self._scanner._active_signals = value
    
    @property
    def timeline(self) -> List[Dict]:
        return self._scanner._timeline
    
    @property
    def stats(self) -> Dict:
        return self._scanner._stats
    
    @property
    def circuit_breaker(self) -> Dict:
        return self._scanner._circuit_breaker
    
    @property
    def dry_run(self) -> bool:
        return self._scanner._dry_run
    
    @property
    def current_sentiment(self) -> Dict:
        return getattr(self._scanner, '_current_sentiment', {})
    
    @property
    def realtime_cache(self) -> Dict:
        return self._scanner._realtime_cache or {}
    
    @property
    def pre_trade_checker(self):
        return self._scanner._pre_trade_checker
    
    @property
    def slippage_model(self):
        return self._scanner._slippage_model
    
    # ==================== 信号更新 ====================
    
    async def update_signals(self, new_signals: List[ScanSignal], scan_time: str):
        """增量更新信号 + 过期清理"""
        scanner = self._scanner
        SIGNAL_EXPIRE_SECONDS = getattr(scanner, 'SIGNAL_EXPIRE_SECONDS', 600)
        
        # === 1. 过期清理 ===
        now = time.time()
        expired_keys = set()
        for s in self.active_signals:
            if s.created_at > 0 and (now - s.created_at) > SIGNAL_EXPIRE_SECONDS:
                if s.signal_status == "new":
                    s.signal_status = "expired"
                    expired_keys.add(s.ts_code + "|" + s.strategy)
                    logger.debug(f"[SIGNAL] 过期: {s.ts_code} {s.strategy_name} ({now - s.created_at:.0f}s)")
                    try:
                        await scanner._publish_scanner_event("signal_expired", {
                            "ts_code": s.ts_code,
                            "strategy": s.strategy,
                            "expired_after": round(now - s.created_at, 0),
                        })
                    except Exception as _e:
                        pass
        
        # 移除已过期且已执行的信号
        self.active_signals = [s for s in self.active_signals
                                if s.signal_status not in ("expired",) or s.created_at == 0]

        # === 2. 增量更新 ===
        existing_keys = {s.ts_code + "|" + s.strategy for s in self.active_signals}
        added = []

        for sig in new_signals:
            key = sig.ts_code + "|" + sig.strategy
            sig.created_at = now
            if key not in existing_keys:
                self.active_signals.append(sig)
                existing_keys.add(key)
                added.append(sig)
            else:
                for s in self.active_signals:
                    if s.ts_code + "|" + s.strategy == key:
                        s.price = sig.price
                        s.pct_chg = sig.pct_chg
                        s.volume_ratio = sig.volume_ratio
                        s.turnover_rate = sig.turnover_rate
                        s.scan_time = sig.scan_time
                        break

        if added:
            self.stats["signals_found"] += len(added)
            logger.info(f"[SIGNAL] 新增{len(added)}个信号: "
                         f"{', '.join(s.ts_code for s in added[:5])}")

            # 推送新信号
            await self._push_signals(added)

            # 【v2.8:EventBus信号生成事件】
            try:
                scanner_ref = self._scanner
                if hasattr(scanner_ref, 'event_bus') and scanner_ref.event_bus:
                    from nodes.market_monitor.scanner_event_bus import ScannerEvents
                    await scanner_ref.event_bus.emit(ScannerEvents.SIGNAL_GENERATED, {
                        "signal_count": len(added),
                        "signals": [{
                            "ts_code": s.ts_code,
                            "strategy": s.strategy_name,
                            "pct_chg": round(s.pct_chg, 1) if s.pct_chg else 0,
                        } for s in added[:5]],
                    })
            except Exception as _e:
                pass

            # 执行新信号
            await self.execute_signals(added)
            
            # 执行后立即持久化
            if self.broker:
                try:
                    await self.broker.save_state()
                except Exception as _e:
                    pass
            
            try:
                await scanner._publish_scanner_event("signal", {
                    "signals": [{
                        "ts_code": s.ts_code,
                        "name": s.stock_name,
                        "strategy": s.strategy_name,
                        "pct_chg": round(s.pct_chg, 1),
                        "reason": s.reason,
                    } for s in added[:10]],
                    "count": len(added),
                    "time": scan_time,
                })
            except Exception as _e:
                pass

    async def _push_signals(self, signals: List[ScanSignal]):
        """推送信号到飞书等渠道"""
        try:
            from core.managers.live.signal_pusher import SignalPusher
            pusher = SignalPusher(self.config.get("push", {}))
            lines = [f"🎯 **实时信号** ({datetime.now().strftime('%H:%M:%S')})"]
            for sig in signals[:10]:
                pct = f"+{sig.pct_chg:.1f}%" if sig.pct_chg and sig.pct_chg > 0 else f"{sig.pct_chg or 0:.1f}%"
                lines.append(f"- {sig.ts_code} {sig.stock_name} | {sig.strategy_name} | {pct}")
            if len(signals) > 10:
                lines.append(f"... 共{len(signals)}个")
            await asyncio.to_thread(pusher.push_signal, "\n".join(lines))
        except Exception as e:
            logger.debug(f"[PUSH] 推送失败(可忽略): {e}")

    # ==================== 信号执行 ====================
    
    async def execute_signals(self, signals: List[ScanSignal]):
        """执行信号(SimulatedBroker撮合)"""
        scanner = self._scanner
        
        if self.dry_run:
            for sig in signals:
                sig.signal_status = "skipped"
                sig.layer_trace["execution"] = {
                    "mode": "dry_run",
                    "reason": "调试模式, 不执行交易",
                    "would_buy_shares": scanner._position_manager.calc_would_buy_shares(sig) if scanner._position_manager else 0,
                    "would_buy_amount": round(sig.price * (scanner._position_manager.calc_would_buy_shares(sig) if scanner._position_manager else 0), 2),
                }
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "调试模式, 未实际下单", sig)
                logger.info(f"[DRY-RUN] 跳过买入 {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")
            return

        for sig in signals:
            # 异动信号只观察不自动买入
            if "anomaly" in sig.strategy:
                sig.signal_status = "skipped"
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "异动信号, 仅观察不自动交易", sig)
                logger.info(f"[EXEC] 异动信号仅观察: {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")
                continue

            # 去重: 已有持仓跳过
            existing = self.broker.get_positions()
            if any(p.ts_code == sig.ts_code for p in existing):
                sig.signal_status = "skipped"
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "已有持仓, 跳过", sig)
                logger.info(f"[EXEC] {sig.ts_code} 已有持仓, 跳过")
                continue

            # 熔断检查
            if not await scanner._check_circuit_breaker():
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "风控熔断中, 暂停买入", sig)
                logger.info(f"[EXEC] 风控熔断, 跳过买入")
                break
                
            MAX_POSITIONS = getattr(scanner, 'MAX_POSITIONS', 10)
            if len(self.broker.get_positions()) >= MAX_POSITIONS:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"已达最大持仓{MAX_POSITIONS}只", sig)
                logger.info(f"[EXEC] 已达最大持仓{MAX_POSITIONS}, 跳过")
                break

            if sig.price <= 0:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"价格异常(price={sig.price})", sig)
                continue

            # PositionSizer
            acct = self.broker.get_account()
            position_ratio = scanner._position_manager.calc_position_ratio(sig) if scanner._position_manager else 0.2
            max_amount = acct.available_cash * position_ratio
            shares = int(max_amount / sig.price / 100) * 100
            
            # 科创板最小200股
            if sig.ts_code.startswith('688'):
                shares = int(max_amount / sig.price / 200) * 200
                if shares <= 0 and max_amount > 0:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        sig.strategy_name, f"科创板资金不足200股(需≥{sig.price*200:.0f}元)", sig)
                    continue
                
            if shares <= 0:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"资金不足({max_amount:.0f}元<{sig.price*100:.0f}元)", sig)
                continue

            # 更新实时价格
            self.broker.update_realtime(sig.ts_code, sig.price)

            # 执行质量检查
            if self.pre_trade_checker:
                self.pre_trade_checker._broker = self.broker
                ok_pre, pre_reason = self.pre_trade_checker.check_buy(
                    ts_code=sig.ts_code, price=sig.price, quantity=shares,
                    stock_name=sig.stock_name, strategy=sig.strategy,
                )
                if not ok_pre:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        sig.strategy_name, f"执行质量检查拒绝: {pre_reason}", sig)
                    logger.info(f"[EXEC] 买入被拒: {sig.ts_code} {pre_reason}")
                    continue

            # 滑点估算
            daily_vol = self.realtime_cache.get(sig.ts_code, {}).get("volume", 0)
            slippage = self.slippage_model.estimate(
                price=sig.price, quantity=shares,
                daily_volume=daily_vol * 100 if daily_vol else 0,
                side="buy", reason=sig.reason,
            )
            adjusted_price = self.slippage_model.apply_slippage(sig.price, slippage)
            if abs(slippage) > 0.001:
                logger.info(f"[EXEC] 滑点调整: {sig.ts_code} {sig.price:.2f}→{adjusted_price:.2f} ({slippage*100:.3f}%)")

            ok, msg, order = self.broker.place_order(
                ts_code=sig.ts_code, stock_name=sig.stock_name,
                side="buy", quantity=shares, price=sig.price,
                order_type="market", strategy=sig.strategy, reason=sig.reason,
            )

            if ok:
                self.timeline.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "action": "buy",
                    "ts_code": sig.ts_code,
                    "stock_name": sig.stock_name,
                    "strategy": sig.strategy_name,
                    "shares": shares,
                    "price": order.filled_price,
                    "reason": sig.reason,
                    "decision_detail": {
                        **sig.decision_detail,
                        "execution": {
                            "position_ratio": position_ratio,
                            "available_cash": round(acct.available_cash, 2),
                            "max_amount": round(max_amount, 2),
                            "shares": shares,
                            "filled_price": order.filled_price,
                            "total_cost": round(order.filled_price * shares, 2),
                            "circuit_breaker": {
                                "paused": self.circuit_breaker.get("trading_paused", False),
                                "consecutive_losses": self.circuit_breaker.get("consecutive_losses", 0),
                            },
                            "sentiment": self.current_sentiment,
                            "position_count_before": len(self.broker.get_positions()),
                        },
                    },
                })
                sig.signal_status = "executed"
                self.stats["trades_executed"] += 1
                # 推送
                await scanner._publish_scanner_event("signal", {
                    "signals": [scanner._signal_to_dict(sig)],
                })
                await scanner._publish_scanner_event("timeline", {
                    "item": self.timeline[-1],
                })
                # 【v2.9:买入成功也发射EventBus持仓变更事件(与卖出对齐)】
                try:
                    from nodes.market_monitor.scanner_event_bus import ScannerEvents
                    if hasattr(scanner, '_event_bus') and scanner._event_bus:
                        await scanner._event_bus.emit(ScannerEvents.POSITION_CHANGED, {
                            "ts_code": sig.ts_code, "action": "buy",
                            "reason": sig.reason, "strategy": sig.strategy_name,
                            "price": order.filled_price, "shares": shares,
                            "source": "signal_manager",
                        })
                except Exception as _e:
                    pass
                logger.info(f"[EXEC] 买入 {sig.ts_code} {shares}股@{order.filled_price:.2f} ({sig.strategy_name})")
            else:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"下单失败: {msg}", sig)
                logger.warning(f"[EXEC] 买入被拒 {sig.ts_code}: {msg}")

    # ==================== 日志 ====================
    
    def _add_timeline_log(self, action, ts_code, stock_name, strategy, reason, sig):
        """添加执行日志到时间线(含blocked状态)"""
        self.timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "ts_code": ts_code,
            "stock_name": stock_name,
            "strategy": strategy,
            "reason": reason,
            "decision_detail": getattr(sig, "decision_detail", {}),
            "layer_trace": getattr(sig, "layer_trace", {}),
        })
        # 审计日志(异步)
        asyncio.create_task(self._write_audit_log(action, ts_code, stock_name, strategy, reason))
    
    async def _write_audit_log(self, action: str, ts_code: str, stock_name: str,
                                strategy: str, reason: str):
        """写入审计日志(append-only, TTL 90天)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            await mongo_manager.db["audit_log"].insert_one({
                "timestamp": datetime.now().isoformat(),
                "account_id": self._scanner.account_id,
                "action": action,
                "ts_code": ts_code,
                "stock_name": stock_name,
                "strategy": strategy,
                "reason": reason,
                "sentiment": self.current_sentiment.get("period", ""),
                "position_ratio": getattr(self._scanner, '_current_position_ratio', None),
                "sell_logic_mode": self._scanner.SELL_LOGIC_MODE,
            })
        except Exception as _e:
            pass
