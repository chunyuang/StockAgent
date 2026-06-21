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
from typing import Dict, List, Any, Optional, Tuple

from nodes.market_monitor.scanner import ScanSignal

# 【v2.9.94】A7 流动性过滤用到 GLOBAL_RISK，之前未 import 导致 NameError。
# 事故时间2026-06-15 13:32:08，scan #8 首次产生信号走到 A7 过滤行崩溃 → scan_loop 死三分钟。
try:
    from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
except Exception as _e:
    GLOBAL_RISK = {}

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
    def broker(self) -> Any:
        return self._scanner._broker
    
    @property
    def config(self) -> Dict:
        return self._scanner.config
    
    @property
    def active_signals(self) -> List[ScanSignal]:
        return self._scanner._active_signals
    
    @active_signals.setter
    def active_signals(self, value) -> Any:
        self._scanner._active_signals = value
    
    @property
    def timeline(self) -> List[Dict]:
        return self._scanner._timeline
    
    @property
    def stats(self) -> Dict:
        return self._scanner._stats
    
    @property
    def circuit_breaker(self) -> Dict:
        return self._scanner._circuit_breaker or {}
    
    @property
    def dry_run(self) -> bool:
        return self._scanner._dry_run
    
    @property
    def current_sentiment(self) -> Dict:
        return self._scanner._current_sentiment
    
    @property
    def realtime_cache(self) -> Dict:
        return self._scanner._realtime_cache or {}
    
    @property
    def pre_trade_checker(self) -> Any:
        return self._scanner._pre_trade_checker
    
    @property
    def slippage_model(self) -> Any:
        return self._scanner._slippage_model
    
    # ==================== 信号更新 ====================
    
    async def update_signals(self, new_signals: List[ScanSignal], scan_time: str) -> None:
        """增量更新信号 + 过期清理【v2.9.43拆分】"""
        # 1. 过期清理
        await self._expire_old_signals()
        # 2. 增量合并
        added = self._merge_new_signals(new_signals)
        if not added:
            return
        # 3. 推送+执行+持久化
        await self._process_new_signals(added, scan_time)

    async def _expire_old_signals(self) -> None:
        """过期信号清理【v2.9.43从update_signals提取】"""
        scanner = self._scanner
        SIGNAL_EXPIRE_SECONDS = scanner.SIGNAL_EXPIRE_SECONDS
        now = time.time()
        for s in self.active_signals:
            if s.created_at > 0 and (now - s.created_at) > SIGNAL_EXPIRE_SECONDS:
                if s.signal_status == "new":
                    s.signal_status = "expired"
                    logger.debug(f"[SIGNAL] 过期: {s.ts_code} {s.strategy_name} ({now - s.created_at:.0f}s)")
                    try:
                        await scanner._publish_scanner_event("signal_expired", {
                            "ts_code": s.ts_code,
                            "strategy": s.strategy,
                            "expired_after": round(now - s.created_at, 0),
                        })
                    except Exception as _e:
                        logger.debug(f"event publish failed: {_e}")
        self.active_signals = [s for s in self.active_signals
                                if s.signal_status not in ("expired",) or s.created_at == 0]

    def _merge_new_signals(self, new_signals: List[ScanSignal]) -> List[ScanSignal]:
        """增量合并新信号【v2.9.43从update_signals提取】"""
        now = time.time()
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
                # 【v2.9.95d】为"信号已存在被静默跳过"补 timeline，否则前端看不到原因
                try:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        sig.strategy_name, "信号已在进行中, 本轮不重复下单", sig)
                except Exception as _e:
                    pass
                for s in self.active_signals:
                    if s.ts_code + "|" + s.strategy == key:
                        s.price = sig.price
                        s.pct_chg = sig.pct_chg
                        s.volume_ratio = sig.volume_ratio
                        s.turnover_rate = sig.turnover_rate
                        s.scan_time = sig.scan_time
                        break
        return added

    async def _persist_signal_history(self, signals: List[ScanSignal], scan_time: str) -> None:
        """将扫描信号写入MongoDB，供非交易时间/重启后回看。"""
        if not signals:
            return
        try:
            from core.managers import mongo_manager
            if not getattr(mongo_manager, "is_initialized", False):
                return
            scanner = self._scanner
            now = datetime.now()
            trade_date = str(getattr(scanner, "_trade_date", "") or now.strftime("%Y%m%d"))
            account_id = getattr(scanner, "account_id", "default") or "default"
            docs = []
            for s in signals:
                docs.append({
                    "account_id": account_id,
                    "trade_date": int(trade_date) if str(trade_date).isdigit() else trade_date,
                    "ts_code": s.ts_code,
                    "stock_name": s.stock_name,
                    "strategy": s.strategy,
                    "strategy_name": s.strategy_name,
                    "signal_type": s.signal_type,
                    "price": s.price,
                    "pct_chg": s.pct_chg,
                    "volume_ratio": s.volume_ratio,
                    "turnover_rate": s.turnover_rate,
                    "reason": s.reason,
                    "scan_time": scan_time or s.scan_time,
                    "created_at": s.created_at,
                    "signal_status": s.signal_status,
                    "factors": s.factors,
                    "decision_detail": s.decision_detail,
                    "layer_trace": s.layer_trace,
                    "updated_at": now,
                })
            for doc in docs:
                await mongo_manager.db["scanner_signals"].update_one(
                    {
                        "account_id": doc["account_id"],
                        "trade_date": doc["trade_date"],
                        "ts_code": doc["ts_code"],
                        "strategy": doc["strategy"],
                    },
                    {"$set": doc, "$setOnInsert": {"created_doc_at": now}},
                    upsert=True,
                )
        except Exception as e:
            logger.debug(f"[SIGNAL] 持久化历史信号失败: {e}")

    async def _process_new_signals(self, added: List[ScanSignal], scan_time: str) -> None:
        """推送+执行+持久化新信号【v2.9.43从update_signals提取】"""
        scanner = self._scanner
        self.stats["signals_found"] += len(added)
        logger.info(f"[SIGNAL] 新增{len(added)}个信号: "
                     f"{', '.join(s.ts_code for s in added[:5])}")
        await self._push_signals(added)
        # EventBus信号生成事件
        try:
            if scanner._event_bus:
                from nodes.market_monitor.scanner_event_bus import ScannerEvents
                await scanner.event_bus.emit(ScannerEvents.SIGNAL_GENERATED, {
                    "signal_count": len(added),
                    "signals": [{
                        "ts_code": s.ts_code,
                        "strategy": s.strategy_name,
                        "pct_chg": round(s.pct_chg, 1) if s.pct_chg else 0,
                    } for s in added[:5]],
                })
        except Exception as _e:
            logger.debug(f"event publish failed: {_e}")
        await self.execute_signals(added)
        await self._persist_signal_history(added, scan_time)
        if self.broker:
            try:
                await self.broker.save_state()
            except Exception as _e:
                logger.debug(f"broker save failed: {_e}")
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
            logger.debug(f"event publish failed: {_e}")

    async def _push_signals(self, signals: List[ScanSignal]) -> None:
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
    
    async def execute_signals(self, signals: List[ScanSignal]) -> None:
        """执行信号(SimulatedBroker撮合)【v2.9.43拆分】"""
        if self.dry_run:
            self._handle_dry_run(signals)
            return
        # 【v2.9.96】交易时间闸锁: 只能在交易时段下单(MORNING/AFTERNOON/LATE_TRADING)
        # 事故案例 6/16 9:28: 手动 scan_once(force=True) 穿越了交易时段检查,
        # 生成了10笔未开盘时的"实际交易". 这里是下单环节的最后一道防线!
        try:
            from nodes.market_monitor.market_phase import MarketPhase
            phase = MarketPhase.classify()
            trading_phases = {MarketPhase.MORNING, MarketPhase.AFTERNOON, MarketPhase.LATE_TRADING}
            if phase not in trading_phases:
                for sig in signals:
                    sig.signal_status = "blocked"
                    sig.layer_trace = sig.layer_trace or {}
                    sig.layer_trace["execution"] = {
                        "mode": "non_trading_hours",
                        "reason": f"当前阶段={phase}, 非交易时间不执行真实下单",
                        "phase": phase,
                    }
                    try:
                        self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                            sig.strategy_name, f"非交易时间({phase}), 不下单", sig)
                    except Exception as _e:
                        pass
                logger.warning(f"[EXEC] 非交易时间({phase}), 跳过{len(signals)}个信号的下单")
                return
        except Exception as _e:
            logger.debug(f"[EXEC] 交易时间闸锁检查异常仅记录: {_e}")
        for sig in signals:
            eligible, reason = self._check_signal_eligibility(sig)
            if not eligible:
                if reason == "circuit_breaker" or reason == "max_positions":
                    break  # 全局阻挡, 后续也不执行
                continue  # 单票阻挡, 继续下一个
            await self._execute_single_buy(sig)

    def _handle_dry_run(self, signals: List[ScanSignal]) -> None:
        """调试模式: 只记录不执行【v2.9.43从execute_signals提取】"""
        scanner = self._scanner
        for sig in signals:
            sig.signal_status = "skipped"
            pm = scanner._position_manager
            would_shares = pm.calc_would_buy_shares(sig) if pm else 0
            sig.layer_trace["execution"] = {
                "mode": "dry_run",
                "reason": "调试模式, 不执行交易",
                "would_buy_shares": would_shares,
                "would_buy_amount": round(sig.price * would_shares, 2),
            }
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, "调试模式, 未实际下单", sig)
            logger.info(f"[DRY-RUN] 跳过买入 {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")

    def _check_signal_eligibility(self, sig: ScanSignal) -> tuple:
        """信号执行前检查(返回eligible, reason)【v2.9.43从execute_signals提取】"""
        scanner = self._scanner
        # 异动信号只观察不自动买入
        if "anomaly" in sig.strategy:
            sig.signal_status = "skipped"
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, "异动信号, 仅观察不自动交易", sig)
            logger.info(f"[EXEC] 异动信号仅观察: {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")
            return False, "anomaly"
        # 去重: 已有持仓跳过
        if self.broker and any(p.ts_code == sig.ts_code for p in self.broker.get_positions()):
            sig.signal_status = "skipped"
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, "已有持仓, 跳过", sig)
            existing = next((p for p in self.broker.get_positions() if p.ts_code == sig.ts_code), None)
            if existing:
                pos_pct = getattr(existing, 'profit_pct', 0) or 0
                pos_qty = getattr(existing, 'total_qty', 0) or 0
                block_reason = (
                    f"已持仓·{sig.ts_code} {pos_qty}股 现盈{pos_pct:+.1f}% "
                    f"({existing.strategy or ''}策略持有中)"
                )
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, block_reason, sig)
                logger.info(f"[EXEC] {block_reason}")
            else:
                logger.info(f"[EXEC] {sig.ts_code} 已有持仓, 跳过")
            return False, "duplicate"
        # 熔断检查(checked inline, 不await)
        cb = self.circuit_breaker
        if cb.get("trading_paused", False):
            pause_reason = cb.get("pause_reason", "未知")
            today_trades = cb.get("today_trades", 0)
            today_losses = cb.get("today_losses", 0)
            consecutive = cb.get("consecutive_losses", 0)
            block_reason = (
                f"风控熔断·{pause_reason} "
                f"今日交易{today_trades}笔(亏损{today_losses}笔) "
                f"连亏{consecutive}笔"
            )
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, block_reason, sig)
            logger.info(f"[EXEC] {block_reason}")
            return False, "circuit_breaker"
        # 最大持仓数
        MAX_POSITIONS = scanner.MAX_POSITIONS
        if self.broker and len(self.broker.get_positions()) >= MAX_POSITIONS:
            curr_count = len(self.broker.get_positions())
            block_reason = (
                f"持仓已满·{curr_count}/{MAX_POSITIONS}只 "
                f"无法新增{sig.ts_code}({sig.strategy_name})"
            )
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, block_reason, sig)
            logger.info(f"[EXEC] {block_reason}")
            return False, "max_positions"
        # 价格异常
        if sig.price <= 0:
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, f"价格异常(price={sig.price})", sig)
            return False, "invalid_price"
        
        # 【v2.9.92x】策略级选股过滤(与回测params对齐)
        eligible, filter_reason = self._check_strategy_params_filter(sig)
        if not eligible:
            return False, filter_reason
        
        return True, ""

    def _check_strategy_params_filter(self, sig) -> tuple:
        """【v2.9.92x】策略级选股过滤(与回测params对齐)
        
        A4: 首板换手率/市值限制
        A5: 半路10点后禁止买入
        A6: 龙头回调幅度限制
        """
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        from datetime import datetime
        
        strategy = getattr(sig, 'strategy', '') or ''
        cfg = STRATEGY_CONFIGS.get(strategy, {})
        params = cfg.get('params', {})
        name = cfg.get('name', strategy)
        
        # A5: 半路追涨10点后禁止买入
        if strategy == 'halfway_chase':
            allow_after_10am = params.get('allow_after_10am', False)
            if not allow_after_10am:
                now = datetime.now()
                if now.hour >= 10 and now.minute > 0:
                    block_reason = (
                        f"时间过滤·半路追涨10点后禁止 "
                        f"当前{now.strftime('%H:%M')} "
                        f"涨{getattr(sig, 'pct_chg', 0):+.1f}%"
                    )
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        name, block_reason, sig)
                    return False, "time_filter"
        
        # A4: 首板打板换手率/市值限制
        if strategy == 'first_limit_up':
            tr = getattr(sig, 'turnover_rate', 0) or 0
            min_tr = params.get('min_turnover_rate', 0)
            max_tr = params.get('max_turnover_rate', 999)
            if min_tr > 0 and tr < min_tr:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    name, f"过滤·换手{tr:.1f}%<下限{min_tr}% (首板需高换手保证流动性)", sig)
                return False, "turnover_filter"
            if max_tr < 999 and tr > max_tr:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    name, f"过滤·换手{tr:.1f}%>上限{max_tr}% (首板换手过高=接力盘混乱)", sig)
                return False, "turnover_filter"
            # 市值限制(从实时数据或MongoDB读取)
            min_mcap = params.get('min_circulation_market_cap', 0)
            max_mcap = params.get('max_circulation_market_cap', 999999)
            if min_mcap > 0 or max_mcap < 999999:
                circ_mv = getattr(sig, 'circ_mv', 0) or 0  # 流通市值(亿元)
                if circ_mv <= 0:
                    # 尝试从信号数据获取
                    circ_mv = getattr(sig, 'circulation_market_cap', 0) or 0
                if circ_mv > 0:
                    if min_mcap > 0 and circ_mv < min_mcap:
                        self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                            name, f"流通市值{circ_mv:.0f}亿<{min_mcap}亿", sig)
                        return False, "mcap_filter"
                    if max_mcap < 999999 and circ_mv > max_mcap:
                        self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                            name, f"流通市值{circ_mv:.0f}亿>{max_mcap}亿", sig)
                        return False, "mcap_filter"
        
        # A6: 龙头低吸回调幅度限制
        if strategy == 'dragon_head':
            # 从信号reason中提取回调幅度(或使用pct_chg)
            pct = abs(getattr(sig, 'pct_chg', 0) or 0)
            min_correction = params.get('min_correction_pct', 0) * 100  # 0.05 → 5%
            max_correction = params.get('max_correction_pct', 1) * 100   # 0.22 → 22%
            # 简化判断: 用跌幅近似回调幅度(负pct_chg=回调)
            sig_pct = getattr(sig, 'pct_chg', 0) or 0
            if sig_pct > 0:
                # 龙头低吸应该是买跌的，正涨幅说明不是回调
                pass  # 不过滤，可能是信号逻辑已经筛选
            elif sig_pct < 0:
                correction = abs(sig_pct)
                if min_correction > 0 and correction < min_correction:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        name, f"回调{correction:.1f}%<{min_correction:.1f}%", sig)
                    return False, "correction_filter"
                if correction > max_correction:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        name, f"回调{correction:.1f}%>{max_correction:.1f}%", sig)
                    return False, "correction_filter"
        
        # A4(续): 跌停翘板换手率限制
        if strategy == 'limit_down_qiao':
            tr = getattr(sig, 'turnover_rate', 0) or 0
            min_tr = params.get('min_turnover_rate', 0)
            if min_tr > 0 and tr < min_tr:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    name, f"换手率{tr:.1f}%<{min_tr}%", sig)
                return False, "turnover_filter"
        
        # A7: 流动性门槛(与回测GLOBAL_RISK.liquidity_threshold对齐)
        # 成交额<500万的股票流动性不足，可能无法卖出
        liquidity_threshold = GLOBAL_RISK.get('liquidity_threshold', 500)  # 万元
        amount = getattr(sig, 'factors', {}).get('amount', 0) or 0  # 成交额(万元)
        if amount <= 0:
            # 尝试从实时数据估算: price * volume
            vol = getattr(sig, 'factors', {}).get('volume', 0) or 0
            if vol > 0 and sig.price > 0:
                amount = sig.price * vol / 10000  # 粗估万元
        if liquidity_threshold > 0 and amount > 0 and amount < liquidity_threshold:
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                name, f"流动性不足(成交额{amount:.0f}万<{liquidity_threshold}万)", sig)
            return False, "liquidity_filter"
        
        return True, ""

    async def _execute_single_buy(self, sig: ScanSignal) -> Optional[Dict]:
        """执行单票买入(编排方法)"""
        scanner = self._scanner
        acct = self.broker.get_account()
        position_ratio = scanner._position_manager.calc_position_ratio(sig) if scanner._position_manager else 0.2
        max_amount = acct.available_cash * position_ratio

        shares = self._calc_buy_shares(sig, max_amount)
        if shares is None:
            return

        self.broker.update_realtime(sig.ts_code, sig.price)
        if not self._check_buy_quality(sig, shares):
            return

        adjusted_price = self._apply_buy_slippage(sig, shares)
        decision_trace = self._build_decision_trace(sig, shares, position_ratio, max_amount, acct, adjusted_price)
        detailed_reason = self._format_decision_reason(sig, decision_trace)
        # 【v2.9.80修复】用滑点调整价更新broker实时价格, 使撮合更接近真实成交
        self.broker.update_realtime(sig.ts_code, adjusted_price)
        ok, msg, order = self.broker.place_order(
            ts_code=sig.ts_code, stock_name=sig.stock_name,
            side="buy", quantity=shares, price=sig.price,
            order_type="market", strategy=sig.strategy, reason=detailed_reason,
            decision_trace=decision_trace)
        if ok:
            await self._post_buy_success(sig, order, shares, position_ratio, max_amount, acct)
        else:
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, f"下单失败: {msg}", sig)
            logger.warning(f"[EXEC] 买入被拒 {sig.ts_code}: {msg}")

    def _build_decision_trace(self, sig, shares, position_ratio, max_amount, acct, adjusted_price) -> dict:
        """构建完整决策轨迹: 选股参数+风控参数+L1-L9+情绪+仓位+账户【v2.9.96】"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        scanner = self._scanner
        strategy_key = sig.strategy or ''
        cfg = STRATEGY_CONFIGS.get(strategy_key, {})
        params = cfg.get('params', {})
        risk_params = cfg.get('riskParams', {})
        layer_trace = getattr(sig, 'layer_trace', {}) or {}
        sentiment = self.current_sentiment or {}
        sent_score = sentiment.get('score', 50)
        sent_period = sentiment.get('period', 'chaos')
        factors = getattr(sig, 'factors', {}) or {}
        
        trace = {
            "version": "v2.9.96",
            "stock": {
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name,
                "strategy": strategy_key,
                "strategy_name": sig.strategy_name,
                "scan_time": sig.scan_time,
            },
            "market_data": {
                "price": sig.price,
                "filled_price": adjusted_price,
                "pct_chg": sig.pct_chg,
                "volume_ratio": sig.volume_ratio,
                "turnover_rate": sig.turnover_rate,
                "is_limit_up": sig.is_limit_up,
                "limit_up_count": sig.limit_up_count,
                "open": factors.get("open"),
                "high": factors.get("high"),
                "low": factors.get("low"),
                "pre_close": factors.get("pre_close"),
                "circ_mv": factors.get("circ_mv"),
                "ma5": factors.get("ma5"),
                "rsi_6": factors.get("rsi_6"),
            },
            "selection_params": {
                "strategy": strategy_key,
                "min_rise_pct": params.get("min_rise_pct"),
                "max_rise_pct": params.get("max_rise_pct"),
                "min_volume_ratio": params.get("min_volume_ratio"),
                "max_volume_ratio": params.get("max_volume_ratio"),
                "min_turnover_rate": params.get("min_turnover_rate"),
                "max_turnover_rate": params.get("max_turnover_rate"),
                "min_circulation_market_cap": params.get("min_circulation_market_cap"),
                "max_circulation_market_cap": params.get("max_circulation_market_cap"),
                "max_open_rise_pct": params.get("max_open_rise_pct"),
                "min_close_rise_pct": params.get("min_close_rise_pct"),
                "allow_after_10am": params.get("allow_after_10am"),
                "opening_pct_min": params.get("opening_pct_min"),
                "opening_pct_max": params.get("opening_pct_max"),
                "min_consecutive_limit": params.get("min_consecutive_limit"),
                "min_correction_pct": params.get("min_correction_pct"),
                "max_correction_pct": params.get("max_correction_pct"),
                "next_day_open_sell_pct": params.get("next_day_open_sell_pct"),
            },
            "risk_params": {
                "stop_loss_pct": risk_params.get("stop_loss_pct"),
                "take_profit_pct": risk_params.get("take_profit_pct"),
                "trailing_stop_pct": risk_params.get("trailing_stop_pct"),
                "max_hold_days": risk_params.get("max_hold_days"),
                "slippage_pct": risk_params.get("slippage_pct"),
                "hold_protection_threshold": risk_params.get("hold_protection_threshold"),
            },
            "layers": {
                "L1_force_empty": layer_trace.get("L1_force_empty", {}),
                "L2_special_period": layer_trace.get("L2_special_period", {}),
                "L3_sentiment": layer_trace.get("L3_sentiment", {}),
                "L4_premarket": layer_trace.get("L4_premarket", {}),
                "L5_auction": layer_trace.get("L5_auction", {}),
                "L6_strategy": layer_trace.get("L6_strategy", {}),
                "L7_ranking": layer_trace.get("L7_ranking", {}),
                "L8_ma60": layer_trace.get("L8_ma60", {}),
                "L8_position": layer_trace.get("L8_position", {}),
                "L9_sector": layer_trace.get("L9_sector", {}),
            },
            "sentiment": {
                "score": sent_score,
                "period": sent_period,
                "phase_name": {"rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}.get(sent_period, sent_period),
                "position_ratio_factor": position_ratio,
            },
            "account_context": {
                "available_cash_before": round(acct.available_cash, 2),
                "total_assets_before": round(acct.total_assets, 2),
                "position_count_before": len(self.broker.get_positions()) if self.broker else 0,
                "max_positions": scanner.MAX_POSITIONS,
                "max_position_ratio": GLOBAL_RISK.get("max_position_ratio", 0.7),
                "single_position_cap": GLOBAL_RISK.get("max_single_position_ratio", 0.35),
                "calculated_position_ratio": position_ratio,
                "max_amount": round(max_amount, 2),
                "buy_amount": round(adjusted_price * shares, 2),
                "buy_shares": shares,
                "circuit_breaker": {
                    "paused": self.circuit_breaker.get("trading_paused", False),
                    "consecutive_losses": self.circuit_breaker.get("consecutive_losses", 0),
                    "today_trades": self.circuit_breaker.get("today_trades", 0),
                    "today_losses": self.circuit_breaker.get("today_losses", 0),
                },
            },
        }
        trace["decision_steps"] = [
            {"step": "1. 信号入池", "logic": "扫描器从全市场候选中识别到策略信号", "params": {"strategy": strategy_key}, "observed": {"reason": sig.reason, "scan_time": sig.scan_time}, "result": "通过，进入自动交易评估"},
            {"step": "2. 策略参数检查", "logic": "按当前策略配置检查涨幅、量比、换手、市值、开盘/收盘涨幅、连板/回调等阈值", "params": trace["selection_params"], "observed": {"pct_chg": sig.pct_chg, "volume_ratio": sig.volume_ratio, "turnover_rate": sig.turnover_rate, "circ_mv": factors.get("circ_mv")}, "result": "策略筛选通过"},
            {"step": "3. L1-L9全局过滤", "logic": "依次检查强制空仓、特殊时期、情绪周期、盘前过滤、竞价过滤、策略筛选、排序去重、大盘/仓位、行业集中度", "params": {}, "observed": trace["layers"], "result": "通过所有已启用过滤层"},
            {"step": "4. 情绪与仓位系数", "logic": "根据情绪周期映射仓位系数，决定本票可用资金比例", "params": {"sentiment_phase": sent_period}, "observed": trace["sentiment"], "result": f"仓位系数{position_ratio*100:.0f}%"},
            {"step": "5. 风控参数载入", "logic": "载入该策略止损、止盈、追踪止损、最大持有天数、滑点等风控配置", "params": trace["risk_params"], "observed": {}, "result": "风控参数已绑定到后续持仓"},
            {"step": "6. 买入股数计算", "logic": "根据可用现金×仓位系数得到最大买入金额，再按100股手数取整", "params": {"max_amount": round(max_amount, 2), "lot_size": 100}, "observed": {"available_cash": round(acct.available_cash, 2), "price": sig.price, "shares": shares}, "result": f"计划买入{shares}股"},
            {"step": "7. 执行质量检查", "logic": "检查资金、持仓、下单质量、滑点与撮合前置条件", "params": {}, "observed": {"raw_price": sig.price, "adjusted_price": adjusted_price}, "result": "通过，提交订单"},
            {"step": "8. 下单撮合", "logic": "以调整后价格更新实时价并提交市价订单，成交后写入broker_orders", "params": {"order_type": "market"}, "observed": {"filled_price_estimate": adjusted_price, "buy_amount": round(adjusted_price * shares, 2)}, "result": "等待Broker成交结果"},
        ]
        return trace

    def _format_decision_reason(self, sig, trace: dict) -> str:
        """从决策轨迹构建一行简要reason(详细信息在decision_trace JSON中)【v2.9.96】"""
        parts = [sig.reason or ""]
        sp = trace.get("selection_params", {})
        rp = trace.get("risk_params", {})
        sent = trace.get("sentiment", {})
        acct_ctx = trace.get("account_context", {})
        
        # 选股参数(关键阈值)
        sel_parts = []
        if sp.get("min_volume_ratio") is not None:
            vr = sig.volume_ratio or 0
            sel_parts.append(f"量比{vr:.2f}\u2208[{sp['min_volume_ratio']},{sp.get('max_volume_ratio',9)}]")
        if sp.get("min_turnover_rate") is not None:
            tr = sig.turnover_rate or 0
            sel_parts.append(f"换手{tr:.1f}\u2208[{sp['min_turnover_rate']},{sp.get('max_turnover_rate',999)}]")
        if sp.get("min_circulation_market_cap") is not None:
            cm = (sig.factors or {}).get('circ_mv', 0) / 10000 if (sig.factors or {}).get('circ_mv') else 0
            sel_parts.append(f"流通{cm:.0f}亿\u2208[{sp['min_circulation_market_cap']},{sp.get('max_circulation_market_cap',999)}]亿")
        if sel_parts:
            parts.append("📋选股·" + " ".join(sel_parts))
        
        # 风控参数
        if rp.get("stop_loss_pct") is not None:
            risk_bits = [f"止损{abs(rp['stop_loss_pct'])*100:.1f}%", f"止盈{rp.get('take_profit_pct',0)*100:.0f}%"]
            if rp.get("trailing_stop_pct"):
                risk_bits.append(f"追踪{rp['trailing_stop_pct']*100:.0f}%")
            if rp.get("max_hold_days"):
                risk_bits.append(f"持{rp['max_hold_days']}天")
            parts.append("🛡️风控·" + "/".join(risk_bits))
        
        # 情绪+仓位
        if sent.get("phase_name"):
            parts.append(f"🌡️{sent['phase_name']}{sent.get('score',0):.0f}分·仓位系数{(sent.get('position_ratio_factor',0) or 0)*100:.0f}%")
        
        # 账户
        if acct_ctx.get("buy_shares"):
            parts.append(f"💰{acct_ctx['buy_shares']}股¥{acct_ctx.get('buy_amount',0):.0f} 持仓{acct_ctx.get('position_count_before',0)+1}/{acct_ctx.get('max_positions',10)}")
        
        return " | ".join(p for p in parts if p)

    def _calc_buy_shares(self, sig: ScanSignal, max_amount: float) -> Optional[int]:
        """计算买入股数(含科创板200股门槛)"""
        if sig.ts_code.startswith('688'):
            shares = int(max_amount / sig.price / 200) * 200
            if shares <= 0 and max_amount > 0:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"科创板资金不足200股(需≥{sig.price*200:.0f}元)", sig)
                return None
        else:
            shares = int(max_amount / sig.price / 100) * 100
        if shares <= 0:
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, f"资金不足({max_amount:.0f}元<{sig.price*100:.0f}元)", sig)
            return None
        return shares

    def _check_buy_quality(self, sig: ScanSignal, shares: int) -> bool:
        """执行质量检查"""
        if not self.pre_trade_checker:
            return True
        self.pre_trade_checker._broker = self.broker
        ok_pre, pre_reason = self.pre_trade_checker.check_buy(
            ts_code=sig.ts_code, price=sig.price, quantity=shares,
            stock_name=sig.stock_name, strategy=sig.strategy)
        if not ok_pre:
            self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                sig.strategy_name, f"执行质量检查拒绝: {pre_reason}", sig)
            logger.info(f"[EXEC] 买入被拒: {sig.ts_code} {pre_reason}")
            return False
        return True

    def _apply_buy_slippage(self, sig: ScanSignal, shares: int) -> float:
        """滑点估算与调整"""
        daily_vol = self.realtime_cache.get(sig.ts_code, {}).get("volume", 0)
        slippage = self.slippage_model.estimate(
            price=sig.price, quantity=shares,
            daily_volume=daily_vol * 100 if daily_vol else 0,
            side="buy", reason=sig.reason)
        adjusted_price = self.slippage_model.apply_slippage(sig.price, slippage)
        if abs(slippage) > 0.001:
            logger.info(f"[EXEC] 滑点调整: {sig.ts_code} {sig.price:.2f}→{adjusted_price:.2f} ({slippage*100:.3f}%)")
        return adjusted_price

    def _build_buy_timeline_entry(
        self, sig, order, shares, position_ratio, max_amount, acct
    ) -> Dict:
        """构建买入时间线索目【v2.9.62提取】"""
        return {
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
                    "position_count_before": len(self.broker.get_positions()) if self.broker else 0,
                },
            },
        }

    async def _emit_buy_events(self, sig, shares, order) -> None:
        """买入事件推送(Redis+EventBus)【v2.9.62提取】"""
        scanner = self._scanner
        await scanner._publish_scanner_event("signal", {
            "signals": [scanner._signal_to_dict(sig)],
        })
        await scanner._publish_scanner_event("timeline", {
            "item": self.timeline[-1],
        })
        # EventBus持仓变更事件
        try:
            from nodes.market_monitor.scanner_event_bus import ScannerEvents
            if scanner._event_bus:
                await scanner._event_bus.emit(ScannerEvents.POSITION_CHANGED, {
                    "ts_code": sig.ts_code, "action": "buy",
                    "reason": sig.reason, "strategy": sig.strategy_name,
                    "price": order.filled_price, "shares": shares,
                    "source": "signal_manager",
                })
        except Exception as _e:
            logger.debug(f"event publish failed: {_e}")

    async def _post_buy_success(self, sig, order, shares, position_ratio, max_amount, acct) -> None:
        """买入成功后善后(timeline+统计+事件推送)【v2.9.43提取, v2.9.62重构】"""
        self.timeline.append(
            self._build_buy_timeline_entry(sig, order, shares, position_ratio, max_amount, acct)
        )
        sig.signal_status = "executed"
        self.stats["trades_executed"] += 1
        await self._emit_buy_events(sig, shares, order)
        logger.info(f"[EXEC] 买入 {sig.ts_code} {shares}股@{order.filled_price:.2f} ({sig.strategy_name})")

    # ==================== 日志 ====================
    
    def _add_timeline_log(self, action, ts_code, stock_name, strategy, reason, sig) -> None:
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
                                strategy: str, reason: str) -> None:
        """写入审计日志(append-only, TTL 90天)
        
        字段规范(v2.9.80统一):
        - timestamp: datetime对象(MongoDB TTL索引要求Date类型)
        - time_str: 人类可读字符串
        - action: 操作类型
        - ts_code/stock_name/strategy/reason: 标准字段
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            now = datetime.now()
            # 【v2.9.82】推断level: 止损/熔断=critical, 其他=info
            is_critical = any(kw in action for kw in ["stop_loss", "circuit_breaker", "error", "risk_sell"])
            level = "critical" if is_critical else "info"
            await mongo_manager.db["audit_log"].insert_one({
                "timestamp": now,
                "time_str": now.strftime("%Y-%m-%d %H:%M:%S"),
                "account_id": self._scanner.account_id,
                "action": action,
                "ts_code": ts_code,
                "stock_name": stock_name,
                "strategy": strategy,
                "reason": reason,
                "level": level,
                "sentiment": self.current_sentiment.get("period", ""),
                "position_ratio": self._scanner._current_position_ratio,
                "sell_logic_mode": self._scanner.SELL_LOGIC_MODE,
            })
        except Exception as _e:
            logger.debug(f"event publish failed: {_e}")
