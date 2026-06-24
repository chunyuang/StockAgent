"""
ScannerUtils — Scanner工具方法集合

从MarketScanner拆分出来(Phase3.1)。
负责:
- 安全round
- Redis事件推送(Stream+Pub/Sub)
- Position/Signal对象序列化
- 关键因子提取
- 交易摘要报告生成
"""

import json
import logging
import math
import time
from datetime import datetime
from typing import Dict, List, Any, Tuple

from nodes.market_monitor.scanner import ScanSignal

logger = logging.getLogger("scanner_utils")


class ScannerUtils:
    """
    Scanner工具方法集合(全部静态/无状态)
    
    用法:
        ScannerUtils.safe_round(v, 2)
        await ScannerUtils.publish_scanner_event("signal", {...})
        dict_repr = ScannerUtils.position_to_dict(pos, risk_getter)
    """
    
    @staticmethod
    def safe_round(v, digits=2) -> float:
        """安全round, 处理None/NaN/inf"""
        if v is None:
            return None
        try:
            if math.isnan(v) or math.isinf(v):
                return None
            return round(v, digits)
        except (TypeError, ValueError):
            return None
    
    @staticmethod
    async def publish_scanner_event(event_type: str, data: Dict) -> None:
        """推送scanner事件到Redis
        
        【Phase2.1:Signal/Position用Redis Stream(不可丢), 其他用Pub/Sub(允许丢)】
        - scanner:signal → Redis Stream(maxlen=1000)
        - scanner:position → Redis Stream(maxlen=5000)
        - scanner:timeline → Redis Pub/Sub(允许丢,1秒后还有下一帧)
        - scanner:status → Redis Pub/Sub(允许丢)
        """
        try:
            from core.managers import redis_manager
            if not redis_manager.client:
                return
            
            data["timestamp"] = datetime.now().strftime("%H:%M:%S")
            payload = json.dumps(data, ensure_ascii=False, default=str)
            
            if event_type in ("signal", "position"):
                stream_key = f"scanner:{event_type}"
                await redis_manager.client.xadd(
                    stream_key,
                    {"data": payload},
                    maxlen=5000 if event_type == "position" else 1000
                )
            else:
                channel = f"scanner:{event_type}"
                await redis_manager.client.publish(channel, payload)
        except Exception as e:
            logger.debug(f"[PUSH] Redis推送失败(可忽略): {e}")
    
    @staticmethod
    def position_to_dict(p, risk_getter=None) -> Dict:
        """Position对象转dict
        
        Args:
            p: Position对象
            risk_getter: callable(strategy_key) → risk_dict
        """
        risk = risk_getter(p.strategy) if risk_getter else {}
        sl_pct = risk.get("stop_loss_pct", 0.03) * 100
        tp_pct = risk.get("take_profit_pct", 0.07) * 100
        
        # 止损止盈价
        sl_price = round(p.avg_cost * (1 - risk.get("stop_loss_pct", 0.03)), 2) if risk else None
        tp_price = round(p.avg_cost * (1 + risk.get("take_profit_pct", 0.07)), 2) if risk else None
        mv = round((p.current_price or 0) * p.total_qty, 2)
        profit_amt = round(((p.current_price or 0) - (p.avg_cost or 0)) * p.total_qty, 2)
        
        # 【v2.9.98g】统一使用_get_strategy_display_name获取策略中文名
        strategy_cn = ScannerUtils._get_strategy_display_name(p.strategy)
        
        return {
            "ts_code": p.ts_code, "stock_name": p.stock_name,
            "strategy": p.strategy, "strategy_name": strategy_cn, "shares": p.total_qty,
            "available_qty": p.available_qty,
            "cost_price": round(p.avg_cost, 2),
            "current_price": round(p.current_price, 2),
            "profit_pct": round(p.profit_pct, 2),
            "profit_amount": profit_amt,
            "market_value": mv,
            "today_buy": p.today_buy_qty,
            "stop_loss_pct": round(sl_pct, 1),
            "take_profit_pct": round(tp_pct, 1),
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "distance_to_stop": round(p.profit_pct + sl_pct, 1),
        }
    
    @staticmethod
    def signal_to_dict(s: ScanSignal, signal_expire_seconds: int = 300) -> Dict:
        """ScanSignal对象转dict"""
        d = {
            "ts_code": s.ts_code, "stock_name": s.stock_name,
            "strategy": s.strategy, "strategy_name": s.strategy_name,
            "signal_type": s.signal_type, "price": ScannerUtils.safe_round(s.price),
            "pct_chg": ScannerUtils.safe_round(s.pct_chg),
            "volume_ratio": ScannerUtils.safe_round(s.volume_ratio),
            "turnover_rate": ScannerUtils.safe_round(s.turnover_rate),
            "is_limit_up": s.is_limit_up,
            "limit_up_count": s.limit_up_count,
            "confidence": s.confidence, "reason": s.reason,
            "scan_time": s.scan_time, "factors": s.factors,
            "signal_status": s.signal_status,
            "created_at": s.created_at,
            "expire_remaining": max(0, signal_expire_seconds - (time.time() - s.created_at)) if s.created_at > 0 else -1,
            "key_factors": ScannerUtils.extract_key_factors(s),
        }
        if s.decision_detail:
            d["decision_detail"] = s.decision_detail
        if s.layer_trace:
            d["layer_trace"] = s.layer_trace
        return d
    
    @staticmethod
    def extract_key_factors(s: ScanSignal) -> Dict[str, Any]:
        """提取信号的关键因子摘要(前端卡片展示用)"""
        factors = s.factors or {}
        key = {}
        if factors.get("circ_mv"):
            mv = factors["circ_mv"]
            key["circ_mv"] = f"{mv/10000:.0f}亿" if mv >= 10000 else f"{mv/100:.0f}万"
        if factors.get("pe") and factors["pe"] > 0:
            key["pe"] = f"PE{factors['pe']:.0f}"
        if factors.get("pb") and factors["pb"] > 0:
            key["pb"] = f"PB{factors['pb']:.1f}"
        if s.limit_up_count > 0:
            key["limit_count"] = f"{s.limit_up_count}连板"
        if factors.get("fd_amount"):
            key["fd_amount"] = f"封单{factors['fd_amount']/1000:.0f}万"
        if s.volume_ratio > 0:
            key["volume_ratio"] = f"量比{s.volume_ratio:.1f}"
        if s.turnover_rate > 0:
            key["turnover_rate"] = f"换手{s.turnover_rate:.1f}%"
        return key
    
    @staticmethod
    def generate_summary_report(scanner) -> Dict[str, Any]:
        """生成完整交易摘要报告(供API调用)【v2.9.56:提取子报告构建方法】
        
        Args:
            scanner: MarketScanner实例(读取broker/stats/timeline等)
        """
        if not scanner._broker:
            return {"error": "Broker未初始化"}
        
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "account": ScannerUtils._build_account_summary(acct, positions),
            "positions": ScannerUtils._build_position_details(scanner, positions),
            "trade_stats": ScannerUtils._build_trade_stats(scanner._timeline),
            "strategy_performance": ScannerUtils._build_strategy_performance(scanner._timeline),
            "risk_status": ScannerUtils._build_risk_status(scanner),
            "signal_stats": ScannerUtils._build_signal_stats(scanner._active_signals),
            # scanner_stats: 前端兼容字段(scan_count/total_signals/active_signals/positions)
            "scanner_stats": {**dict(scanner._stats), "scan_count": scanner._stats.get("scans", 0), "total_signals": scanner._stats.get("signals_found", 0), "active_signals": len(scanner._active_signals), "positions": len(positions)},
            "sentiment": scanner.get_current_sentiment(),
            "position_ratio": scanner.get_current_position_ratio(),
        }

    @staticmethod
    def _build_account_summary(acct, positions) -> Dict[str, Any]:
        """构建账户摘要【v2.9.56从generate_summary_report提取】"""
        return {
            "total_assets": round(acct.total_assets, 2),
            "available_cash": round(acct.available_cash, 2),
            "market_value": round(acct.market_value, 2),
            "total_profit": round(acct.total_profit, 2),
            "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
            "position_count": len(positions),
        }

    @staticmethod
    def _build_position_details(scanner, positions) -> List[Dict]:
        """构建持仓详情【v2.9.56从generate_summary_report提取】"""
        details = []
        for p in positions:
            risk = scanner._get_strategy_risk(p.strategy)
            sl_pct = risk.get("stop_loss_pct", 0.03) * 100
            tp_pct = risk.get("take_profit_pct", 0.07) * 100
            details.append({
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "strategy": p.strategy,
                "shares": p.total_qty,
                "available_qty": p.available_qty,
                "cost_price": round(p.avg_cost, 2),
                "current_price": round(p.current_price, 2),
                "profit_pct": round(p.profit_pct, 2),
                "market_value": round((p.current_price or 0) * p.total_qty, 2),
                "stop_loss_price": round(p.avg_cost * (1 - risk.get("stop_loss_pct", 0.03)), 2),
                "take_profit_price": round(p.avg_cost * (1 + risk.get("take_profit_pct", 0.07)), 2),
                "stop_loss_pct": round(sl_pct, 1),
                "take_profit_pct": round(tp_pct, 1),
                "distance_to_stop": round(p.profit_pct + sl_pct, 1),
                "is_t1_locked": p.today_buy_qty > 0,
            })
        return details

    @staticmethod
    def _build_trade_stats(timeline: list) -> Dict[str, Any]:
        """构建交易统计【v2.9.56从generate_summary_report提取】"""
        today_buys = [t for t in timeline if t.get("action") == "buy"]
        today_sells = [t for t in timeline if t.get("action") == "sell"]
        profitable_sells = [t for t in today_sells if t.get("profit_pct", 0) > 0]
        losing_sells = [t for t in today_sells if t.get("profit_pct", 0) < 0]
        return {
            "total_trades": len(today_buys) + len(today_sells),
            "buys": len(today_buys),
            "sells": len(today_sells),
            "win_trades": len(profitable_sells),
            "loss_trades": len(losing_sells),
            "win_rate": round(len(profitable_sells) / max(len(today_sells), 1) * 100, 1),
            "avg_profit_pct": round(
                sum(t.get("profit_pct", 0) for t in profitable_sells) / max(len(profitable_sells), 1), 2
            ) if profitable_sells else 0,
            "avg_loss_pct": round(
                sum(t.get("profit_pct", 0) for t in losing_sells) / max(len(losing_sells), 1), 2
            ) if losing_sells else 0,
        }

    @staticmethod
    def _build_strategy_performance(timeline: list) -> Dict[str, Any]:
        """构建策略表现【v2.9.56从generate_summary_report提取】"""
        perf = {}
        for t in timeline:
            strat = t.get("strategy", "unknown")
            if strat not in perf:
                perf[strat] = {"trades": 0, "wins": 0, "total_pnl": 0}
            perf[strat]["trades"] += 1
            if t.get("action") == "sell":
                pnl = t.get("profit_pct", 0)
                perf[strat]["total_pnl"] += pnl
                if pnl > 0:
                    perf[strat]["wins"] += 1
        return perf

    @staticmethod
    def _build_risk_status(scanner) -> Dict[str, Any]:
        """构建风控状态【v2.9.56从generate_summary_report提取, v2.9.85:None安全】"""
        cb = scanner._circuit_breaker or {}
        return {
            "circuit_breaker_active": cb.get("trading_paused", False),
            "circuit_breaker_reason": cb.get("pause_reason", ""),
            "consecutive_losses": cb.get("consecutive_losses", 0),
            "today_trades": cb.get("today_trades", 0),
            "today_losses": cb.get("today_losses", 0),
            "dry_run": scanner._dry_run,
        }

    @staticmethod
    def _build_signal_stats(active_signals: list) -> Dict[str, Any]:
        """构建信号统计【v2.9.56从generate_summary_report提取, v2.9.99:补充blocked/active状态】"""
        return {
            "total": len(active_signals),
            "new": len([s for s in active_signals if getattr(s, 'signal_status', '') == "new"]),
            "executed": len([s for s in active_signals if getattr(s, 'signal_status', '') == "executed"]),
            "skipped": len([s for s in active_signals if getattr(s, 'signal_status', '') == "skipped"]),
            "expired": len([s for s in active_signals if getattr(s, 'signal_status', '') == "expired"]),
            "filtered": len([s for s in active_signals if getattr(s, 'signal_status', '') == "filtered"]),
            "blocked": len([s for s in active_signals if getattr(s, 'signal_status', '') == "blocked"]),
            "active": len([s for s in active_signals if getattr(s, 'signal_status', '') in ("new", "executed")]),
        }

    # ==================== Phase4.3: 健康度评分 ====================
    # ==================== v2.9.24: 运行时诊断提取 ====================

    @staticmethod
    def diagnose(scanner) -> Dict[str, Any]:
        """运行时诊断摘要(关键健康指标+可操作建议)【v2.9.23→v2.9.24提取, v2.9.56:检查提取为子方法】
        
        与get_status的区别:
        - get_status: 完整状态快照(包含所有细节)
        - diagnose: 关键指标+异常检测+修复建议(前端告警用)
        
        Args:
            scanner: MarketScanner实例
        """
        issues: list = []
        now = time.time()
        
        ScannerUtils._check_risk_thread_alive(scanner, issues)
        ScannerUtils._check_quote_cache_stale(scanner, issues, now)
        ScannerUtils._check_scan_loop_errors(scanner, issues)
        ScannerUtils._check_pending_sells_backlog(scanner, issues)
        ScannerUtils._check_circuit_breaker_active(scanner, issues)
        ScannerUtils._check_risk_check_timeout(scanner, issues, now)
        
        cache_age = now - (scanner._last_realtime_update_ts or 0)
        pending_count = len(scanner._pending_sells)
        return {
            "healthy": len([i for i in issues if i["level"] == "critical"]) == 0,
            "issues": issues,
            "summary": {
                "running": scanner._is_running,
                "positions": len(scanner._broker.get_positions()) if scanner._broker else 0,
                "active_signals": len(scanner._active_signals),
                "cache_age_sec": round(cache_age, 1),
                "pending_sells": pending_count,
                "risk_thread_alive": scanner._risk_thread.is_alive() if scanner._risk_thread else False,
                "scan_errors": scanner.get_scan_error_count(),
                "trading_paused": (scanner._circuit_breaker or {}).get("trading_paused", False),
            },
        }

    @staticmethod
    def _check_risk_thread_alive(scanner, issues: list) -> None:
        """风控线程存活检查【v2.9.56从diagnose提取】"""
        if scanner._risk_running and scanner._risk_thread and not scanner._risk_thread.is_alive():
            issues.append({
                "level": "critical",
                "area": "risk_thread",
                "message": "风控线程已退出",
                "restarts": scanner._risk_thread_restarts,
                "action": "风控线程将自动重启,如持续退出请检查日志",
            })

    @staticmethod
    def _check_quote_cache_stale(scanner, issues: list, now: float) -> None:
        """行情缓存过期检查【v2.9.56从diagnose提取】"""
        cache_age = now - (scanner._last_realtime_update_ts or 0)
        if scanner._is_running and cache_age > 120:
            issues.append({
                "level": "warning",
                "area": "quote_cache",
                "message": f"行情缓存{cache_age:.0f}秒未更新",
                "action": "检查行情源(量脉/东财)连接状态",
            })

    @staticmethod
    def _check_scan_loop_errors(scanner, issues: list) -> None:
        """scan_loop连续异常检查【v2.9.56从diagnose提取】"""
        error_count = scanner.get_scan_error_count()
        if error_count > 0:
            issues.append({
                "level": "warning" if error_count < 3 else "critical",
                "area": "scan_loop",
                "message": f"扫描循环连续{error_count}次异常",
                "action": "3次以内自动恢复,超过3次scanner将停止",
            })

    @staticmethod
    def _check_pending_sells_backlog(scanner, issues: list) -> None:
        """pending_sells积压检查【v2.9.56从diagnose提取】"""
        pending_count = len(scanner._pending_sells)
        if pending_count > 5:
            issues.append({
                "level": "warning",
                "area": "pending_sells",
                "message": f"{pending_count}个挂起卖出待执行",
                "action": "检查是否多票跌停或执行超时",
            })

    @staticmethod
    def _check_circuit_breaker_active(scanner, issues: list) -> None:
        """熔断器触发检查【v2.9.56从diagnose提取】"""
        cb = scanner._circuit_breaker or {}
        if cb.get("trading_paused"):
            issues.append({
                "level": "critical",
                "area": "circuit_breaker",
                "message": f"熔断器已触发: {cb.get('pause_reason', '未知')}",
                "action": "可调用reset_circuit_breaker()重置",
            })

    @staticmethod
    def _check_risk_check_timeout(scanner, issues: list, now: float) -> None:
        """风控检查超时检查【v2.9.56从diagnose提取】"""
        last_risk = scanner._last_risk_check_ts
        if scanner._is_running and last_risk and (now - last_risk) > 10:
            issues.append({
                "level": "warning",
                "area": "risk_check",
                "message": f"风控检查{(now - last_risk):.0f}秒未执行",
                "action": "检查风控线程是否正常运行",
            })

    @staticmethod
    def build_account_info(scanner) -> Dict[str, Any]:
        """构建账户信息(兼容掘金+模拟broker)【v2.9.27:从scanner提取】"""
        default = {"total_assets": 0, "available_cash": 0, "market_value": 0, "total_profit": 0}
        if scanner._trade_mode == scanner.MODE_GM and scanner._gm_broker:
            gm_acct = scanner._gm_broker.get_account()
            return {
                "total_assets": gm_acct.get("total_assets", 0),
                "available_cash": gm_acct.get("available_cash", 0),
                "market_value": gm_acct.get("market_value", 0),
                "total_profit": 0,
            }
        elif scanner._broker:
            acct = scanner._broker.get_account()
            return {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "total_profit": round(acct.total_profit, 2),
            }
        return default

    @staticmethod
    def compute_health_score(scanner) -> Dict[str, Any]:
        """Scanner健康度评分(绿/黄/红)【v2.9.56:提取指标收集+健康判定】

        维度:
        - scan_lag: 全量扫描延迟(上次到现在)
        - risk_check_lag: 风控检查延迟
        - quote_staleness: 行情数据陈旧度
        - warnings: 告警列表

        Args:
            scanner: MarketScanner实例
        """
        metrics = ScannerUtils._collect_health_metrics(scanner)
        warnings = ScannerUtils._collect_health_warnings(scanner, metrics)
        status, is_healthy, is_warning = ScannerUtils._judge_health(metrics, warnings)

        return {
            "status": status,          # green/yellow/red
            "is_healthy": is_healthy,
            "scan_lag_seconds": round(metrics['scan_lag'], 1),
            "risk_check_lag_seconds": round(metrics['risk_lag'], 1),
            "quote_staleness_seconds": round(metrics['quote_staleness'], 1),
            "risk_thread_alive": metrics['risk_thread_alive'],
            "risk_thread_restarts": scanner.get_risk_thread_restarts(),
            "warnings": warnings,
            "event_bus_stats": scanner.get_event_bus().get_stats() if scanner.get_event_bus() else {},
        }

    @staticmethod
    def _collect_health_metrics(scanner) -> Dict[str, Any]:
        """收集健康度指标【v2.9.56从compute_health_score提取】"""
        now = time.time()
        risk_thread_alive = (
            scanner.get_risk_thread() is not None
            and scanner.get_risk_thread().is_alive()
        )
        return {
            'scan_lag': (now - scanner._last_scan_ts) if scanner._last_scan_ts > 0 else 999,
            'risk_lag': (now - scanner._last_risk_check_ts) if scanner._last_risk_check_ts > 0 else 999,
            'quote_staleness': scanner._quote_manager.get_staleness() if scanner._quote_manager else 999.0,
            'risk_thread_alive': risk_thread_alive,
            'pending_count': ScannerUtils._get_pending_sells_count(scanner),
        }

    @staticmethod
    def _get_pending_sells_count(scanner) -> int:
        """安全获取pending_sells数量【v2.9.56从compute_health_score提取】"""
        try:
            pending_data = scanner._safe_read_state("_pending_sells")
            if isinstance(pending_data, dict):
                return len(pending_data)
            raise TypeError("_safe_read_state returned non-dict")
        except (AttributeError, TypeError):
            if scanner._state_lock is None:
                return len(scanner._pending_sells)
            with scanner._state_lock:
                return len(scanner._pending_sells)

    @staticmethod
    def _collect_health_warnings(scanner, metrics: Dict) -> List[str]:
        """收集健康度告警【v2.9.56从compute_health_score提取】"""
        warnings = []
        if metrics['scan_lag'] > 600:
            warnings.append(f"扫描延迟{metrics['scan_lag']:.0f}秒")
        if metrics['risk_lag'] > 10:
            warnings.append(f"风控延迟{metrics['risk_lag']:.0f}秒")
        if metrics['quote_staleness'] > 60:
            warnings.append(f"行情陈旧{metrics['quote_staleness']:.0f}秒")
        if scanner._quote_manager and scanner._quote_manager.degrade_level > 0:
            warnings.append(f"行情降级level={scanner._quote_manager.degrade_level}")
        if metrics['pending_count'] > 0:
            warnings.append(f"跌停挂起{metrics['pending_count']}只")
        if scanner.get_circuit_breaker().get('trading_paused'):
            warnings.append("熔断器已触发")
        # EventBus异常率
        event_bus = scanner.get_event_bus()
        if event_bus:
            stats = event_bus.get_stats()
            total_errors = sum(s.get('errors', 0) for s in stats.values())
            total_handled = sum(s.get('handled', 0) for s in stats.values())
            if total_errors > 0 and total_handled > 0:
                error_rate = total_errors / (total_handled + total_errors)
                if error_rate > 0.1:
                    warnings.append(f"EventBus异常率{error_rate:.0%}({total_errors}/{total_handled+total_errors})")
        if not metrics['risk_thread_alive'] and scanner.is_risk_running():
            warnings.append("风控线程已停止")
        return warnings

    @staticmethod
    def _judge_health(metrics: Dict, warnings: List[str]) -> Tuple[str, bool, bool]:
        """健康度判定【v2.9.56从compute_health_score提取】
        
        Returns: (status, is_healthy, is_warning)
        """
        is_healthy = (
            metrics['scan_lag'] < 360 and
            metrics['risk_lag'] < 5 and
            metrics['quote_staleness'] < 30 and
            metrics['risk_thread_alive'] and
            len(warnings) == 0
        )
        is_warning = not is_healthy and (
            metrics['scan_lag'] < 600 and
            metrics['risk_lag'] < 30 and
            metrics['quote_staleness'] < 120 and
            metrics['risk_thread_alive']
        )
        if is_healthy:
            return "green", True, False
        elif is_warning:
            return "yellow", False, True
        else:
            return "red", False, False

    @staticmethod
    def format_slow_steps(steps: list) -> str:
        """格式化扫描慢步骤日志【v2.9.28:从scan_once提取】
        
        Args:
            steps: [(label, ms), ...] 分步耗时列表
        Returns:
            慢步骤日志字符串, 无慢步骤返回空字符串
        """
        slow_marks = []
        for label, ms in steps:
            if ms > 1000:
                slow_marks.append(f"\U0001f534{label}={ms:.0f}ms")
            elif ms > 100:
                slow_marks.append(f"\u26a0\ufe0f{label}={ms:.0f}ms")
        return f" | 慢步骤: {', '.join(slow_marks)}" if slow_marks else ""

    @staticmethod
    def _calc_stop_loss_status(pos, sl_price, sl_pct: float) -> Tuple[str, str]:
        """计算止损状态和描述【v2.9.98g从build_position_dict拆分】"""
        sl_price_v = sl_price if isinstance(sl_price, (int, float)) else 0
        if pos.current_price <= sl_price_v and sl_price_v > 0:
            return "broken", f"已破止损 -{sl_pct:.1f}%, 当前 {pos.profit_pct:.1f}%"
        elif pos.current_price <= sl_price_v * 1.05 and sl_price_v > 0:
            return "near", f"接近止损价 {sl_price_v:.2f}"
        return "safe", ""

    @staticmethod
    def _get_strategy_display_name(strategy: str) -> str:
        """获取策略显示名【v2.9.98g从build_position_dict+position_to_dict统一】"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
            return STRATEGY_CONFIGS.get(strategy, {}).get("display_name", strategy)
        except Exception as _e:
            return strategy

    @staticmethod
    def build_position_dict(pos, scanner, trailing_copy: Dict, risk_levels_copy: Dict) -> Dict:
        """将Broker持仓对象转换为API响应dict【v2.9.31:从get_positions提取】
        
        Args:
            pos: Broker持仓对象(Position)
            scanner: MarketScanner实例(委托获取风控参数)
            trailing_copy: 追踪止损快照(已深拷贝,线程安全)
            risk_levels_copy: 风险等级快照(已深拷贝,线程安全)
        Returns:
            持仓信息dict
        """
        risk = scanner._get_strategy_risk(pos.strategy)
        sl_price = scanner._calc_stop_loss_price(pos, risk)
        tp_price = scanner._calc_take_profit_price(pos, risk)
        sl_pct = risk.get("stop_loss_pct", 0.03) * 100
        tp_pct = risk.get("take_profit_pct", 0.07) * 100
        mv = round(pos.current_price * pos.total_qty, 2)
        profit_amt = round((pos.current_price - pos.avg_cost) * pos.total_qty, 2)
        # 【v2.9.98g】拆分止损状态+策略中文名到独立方法
        stop_loss_status, stop_loss_desc = ScannerUtils._calc_stop_loss_status(pos, sl_price, sl_pct)
        strategy_name_cn = ScannerUtils._get_strategy_display_name(pos.strategy)
        
        return {
            "ts_code": pos.ts_code,
            "stock_name": pos.stock_name or scanner._stock_name_map.get(pos.ts_code, ""),
            "strategy": pos.strategy,
            "strategy_name": strategy_name_cn,
            "shares": pos.total_qty,
            "available_qty": pos.available_qty,
            "cost_price": round(pos.avg_cost, 2),
            "current_price": round(pos.current_price, 2),
            "profit_pct": round(pos.profit_pct, 2),
            "profit_amount": profit_amt,
            "market_value": mv,
            "today_buy": pos.today_buy_qty,
            "stop_loss_pct": round(sl_pct, 1),
            "take_profit_pct": round(tp_pct, 1),
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "stop_loss_status": stop_loss_status,
            "stop_loss_desc": stop_loss_desc,
            "distance_to_stop": round(pos.profit_pct + sl_pct, 1),
            "buy_date": pos.buy_date,
            "trailing_stop": trailing_copy.get(pos.ts_code),
            "risk_level": risk_levels_copy.get(pos.ts_code, "normal"),
            "effective_stop_price": scanner._get_effective_stop_price(pos, risk),
        }
